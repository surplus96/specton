from collections.abc import Callable, Iterator

import pytest
from pydantic import BaseModel

from specton.contracts.api import ErrorCode
from specton.llm.client import LLMClient
from specton.llm.errors import (
    LLMAPIError,
    LLMBudgetExceededError,
    LLMContractError,
    LLMError,
    LLMRefusalError,
    LLMTimeoutError,
)
from specton.llm.stub import StubTransport, refusal, reply, stub_client
from specton.llm.types import LLMRequest, Message


class Answer(BaseModel):
    label: str
    score: int


def make_request() -> LLMRequest:
    return LLMRequest(
        stage="A01",
        prompt_version="a01-v1",
        model="test-model",
        messages=(Message(role="user", content="요구사항을 분류하라"),),
        max_output_tokens=100,
    )


def ticking_clock(*ticks: float) -> Callable[[], float]:
    values: Iterator[float] = iter(ticks)
    return lambda: next(values)


def test_returns_validated_output_with_one_call_record() -> None:
    client, transport = stub_client(
        reply(Answer(label="FR", score=3), input_tokens=12, output_tokens=5)
    )

    result = client.complete(make_request(), Answer)

    assert result.output == Answer(label="FR", score=3)
    assert [c.outcome for c in result.calls] == ["ok"]
    assert result.total_tokens == 17
    assert len(transport.sent) == 1


def test_retries_with_validation_errors_then_succeeds() -> None:
    client, transport = stub_client(reply('{"label": "FR"}'), reply(Answer(label="FR", score=1)))

    result = client.complete(make_request(), Answer)

    assert result.output.score == 1
    assert [c.outcome for c in result.calls] == ["invalid_output", "ok"]
    assert [c.attempt for c in result.calls] == [1, 2]
    retried = transport.sent[1].messages
    assert retried[-2] == Message(role="assistant", content='{"label": "FR"}')
    assert retried[-1].role == "user"
    assert "score" in retried[-1].content


def test_raises_contract_error_after_retries_are_used_up() -> None:
    client, transport = stub_client(reply("not json"), reply("{}"), reply('{"label": 1}'))

    with pytest.raises(LLMContractError) as caught:
        client.complete(make_request(), Answer)

    assert len(caught.value.calls) == 3
    assert all(c.outcome == "invalid_output" for c in caught.value.calls)
    assert len(transport.sent) == 3


def test_zero_retries_means_a_single_attempt() -> None:
    client, transport = stub_client(reply("{}"), max_structured_retries=0)

    with pytest.raises(LLMContractError):
        client.complete(make_request(), Answer)

    assert len(transport.sent) == 1


def test_refusal_is_not_retried() -> None:
    client, transport = stub_client(refusal())

    with pytest.raises(LLMRefusalError) as caught:
        client.complete(make_request(), Answer)

    assert [c.outcome for c in caught.value.calls] == ["refused"]
    assert len(transport.sent) == 1


@pytest.mark.parametrize(
    ("error", "outcome"),
    [(LLMTimeoutError("timed out"), "timeout"), (LLMAPIError("bad request"), "api_error")],
)
def test_transport_failures_keep_their_type_and_call_record(error: LLMError, outcome: str) -> None:
    client, _ = stub_client(error)

    with pytest.raises(type(error)) as caught:
        client.complete(make_request(), Answer)

    assert [c.outcome for c in caught.value.calls] == [outcome]


def test_budget_stops_retry_before_next_call() -> None:
    client, transport = stub_client(
        reply("{}", input_tokens=15, output_tokens=5), reply(Answer(label="FR", score=1))
    )

    with pytest.raises(LLMBudgetExceededError) as caught:
        client.complete(make_request(), Answer, token_budget=20)

    assert len(caught.value.calls) == 1
    assert len(transport.sent) == 1


def test_call_record_has_stage_model_version_and_duration() -> None:
    transport = StubTransport([reply(Answer(label="NFR", score=2))])
    client = LLMClient(transport, max_structured_retries=2, clock=ticking_clock(10.0, 10.25))

    record = client.complete(make_request(), Answer).calls[0]

    assert (record.stage, record.prompt_version, record.model) == ("A01", "a01-v1", "test-model")
    assert record.duration_ms == 250


def test_retry_prompt_does_not_echo_input_values() -> None:
    client, transport = stub_client(
        reply('{"label": "FR", "score": "CONFIDENTIAL-42"}'), reply(Answer(label="FR", score=1))
    )

    client.complete(make_request(), Answer)

    assert "CONFIDENTIAL-42" not in transport.sent[1].messages[-1].content


def test_stub_fails_loudly_when_called_more_than_prepared() -> None:
    transport = StubTransport([])

    with pytest.raises(AssertionError):
        transport.send(make_request(), Answer)


def test_negative_retry_count_is_rejected() -> None:
    with pytest.raises(ValueError):
        LLMClient(StubTransport([]), max_structured_retries=-1)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LLMRefusalError, "LLM_REFUSED"),
        (LLMTimeoutError, "LLM_UNAVAILABLE"),
        (LLMAPIError, "LLM_UNAVAILABLE"),
        (LLMContractError, "LLM_OUTPUT_INVALID"),
        (LLMBudgetExceededError, "BUDGET_EXCEEDED"),
        (LLMError, "INTERNAL"),
    ],
)
def test_each_error_maps_to_an_api_error_code(error: type[LLMError], code: str) -> None:
    assert error.code == code
    assert code in {c.value for c in ErrorCode}
