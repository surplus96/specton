from types import SimpleNamespace
from typing import Any, cast

import httpx2
import openai
import pytest
from openai import OpenAI
from pydantic import BaseModel, SecretStr

from specton.config import Settings
from specton.llm import openai_transport
from specton.llm.client import LLMClient
from specton.llm.errors import LLMAPIError, LLMTimeoutError
from specton.llm.openai_transport import OpenAITransport, openai_client
from specton.llm.types import LLMRequest, Message

API_REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


class Answer(BaseModel):
    label: str
    score: int


class FakeResponses:
    """SDK의 client.responses 자리를 대신한다. 받은 인자를 기록하고 준비한 결과를 돌려준다."""

    def __init__(self, result: object) -> None:
        self._result = result
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> object:
        self.kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def fake_sdk(result: object) -> tuple[OpenAI, FakeResponses]:
    responses = FakeResponses(result)
    return cast(OpenAI, SimpleNamespace(responses=responses)), responses


def sdk_response(
    text: str = "", refusal: str | None = None, usage: tuple[int, int] | None = (7, 3)
) -> SimpleNamespace:
    part = (
        SimpleNamespace(type="refusal", refusal=refusal)
        if refusal is not None
        else SimpleNamespace(type="output_text", text=text)
    )
    return SimpleNamespace(
        output=[SimpleNamespace(type="reasoning"), SimpleNamespace(type="message", content=[part])],
        output_text=text,
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]) if usage else None,
    )


def make_request(effort: str | None = "medium") -> LLMRequest:
    return LLMRequest.model_validate(
        {
            "stage": "A01",
            "prompt_version": "a01-v1",
            "model": "gpt-6.1-sol",
            "messages": [
                Message(role="system", content="규칙"),
                Message(role="user", content="요구사항"),
            ],
            "max_output_tokens": 500,
            "reasoning_effort": effort,
        }
    )


def test_sends_structured_output_request() -> None:
    sdk, responses = fake_sdk(sdk_response('{"label": "FR", "score": 1}'))

    OpenAITransport(sdk).send(make_request(), Answer)

    sent = responses.kwargs
    assert sent["model"] == "gpt-6.1-sol"
    assert sent["input"] == [
        {"role": "system", "content": "규칙"},
        {"role": "user", "content": "요구사항"},
    ]
    assert sent["max_output_tokens"] == 500
    assert sent["reasoning"] == {"effort": "medium"}
    assert sent["store"] is False
    assert sent["text"]["format"]["type"] == "json_schema"
    assert sent["text"]["format"]["strict"] is True
    assert sent["text"]["format"]["name"] == "Answer"


def test_omits_reasoning_when_not_set() -> None:
    sdk, responses = fake_sdk(sdk_response("{}"))

    OpenAITransport(sdk).send(make_request(effort=None), Answer)

    assert responses.kwargs["reasoning"] is openai.omit


def test_returns_text_and_token_usage() -> None:
    sdk, _ = fake_sdk(sdk_response('{"label": "FR", "score": 1}'))

    raw = OpenAITransport(sdk).send(make_request(), Answer)

    assert raw.text == '{"label": "FR", "score": 1}'
    assert raw.refusal is None
    assert (raw.input_tokens, raw.output_tokens) == (7, 3)


def test_returns_refusal_without_text() -> None:
    sdk, _ = fake_sdk(sdk_response(refusal="거절"))

    raw = OpenAITransport(sdk).send(make_request(), Answer)

    assert raw.refusal == "거절"
    assert raw.text is None


def test_missing_usage_counts_as_zero_tokens() -> None:
    sdk, _ = fake_sdk(sdk_response("{}", usage=None))

    raw = OpenAITransport(sdk).send(make_request(), Answer)

    assert (raw.input_tokens, raw.output_tokens) == (0, 0)


@pytest.mark.parametrize(
    ("sdk_error", "expected"),
    [
        (openai.APITimeoutError(request=API_REQUEST), LLMTimeoutError),
        (openai.APIConnectionError(request=API_REQUEST), LLMAPIError),
        (
            openai.BadRequestError(
                "bad", response=httpx2.Response(400, request=API_REQUEST), body=None
            ),
            LLMAPIError,
        ),
    ],
)
def test_sdk_errors_become_llm_errors(sdk_error: Exception, expected: type[Exception]) -> None:
    sdk, _ = fake_sdk(sdk_error)

    with pytest.raises(expected) as caught:
        OpenAITransport(sdk).send(make_request(), Answer)

    assert "A01" in str(caught.value)


def test_works_end_to_end_through_llm_client() -> None:
    sdk, _ = fake_sdk(sdk_response('{"label": "NFR", "score": 2}'))
    client = LLMClient(OpenAITransport(sdk), max_structured_retries=2)

    result = client.complete(make_request(), Answer)

    assert result.output == Answer(label="NFR", score=2)
    assert result.total_tokens == 10


def test_openai_client_requires_api_key() -> None:
    with pytest.raises(LLMAPIError):
        openai_client(Settings(_env_file=None, openai_api_key=None))


def test_openai_client_applies_timeout_and_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, Any] = {}

    def fake_openai(**kwargs: Any) -> object:
        created.update(kwargs)
        return SimpleNamespace(responses=FakeResponses(sdk_response("{}")))

    monkeypatch.setattr(openai_transport, "OpenAI", fake_openai)
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("sk-test"),
        llm_timeout_seconds=30,
        llm_api_retries=1,
    )

    client = openai_client(settings)

    assert isinstance(client, LLMClient)
    assert created == {"api_key": "sk-test", "timeout": 30, "max_retries": 1}
