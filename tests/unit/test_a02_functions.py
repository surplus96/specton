"""A02 기능 설계 노드 (TC-A02). 실제 LLM 없이 stub 응답으로 검증한다."""

import json
from typing import Any

import pytest

from specton.config import Settings
from specton.contracts import DesignState, FunctionDraft, Requirement
from specton.llm.errors import LLMContractError, LLMRefusalError, LLMTimeoutError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.a02_functions import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    A02Output,
    input_data,
    run,
)
from specton.nodes.common import unwrap_data
from specton.packs.examples import load_examples


def _settings() -> Settings:
    return Settings(_env_file=None)


def _req(req_id: str, text: str, *, type_: str = "FR", category: str | None = None) -> Requirement:
    return Requirement.model_validate(
        {
            "id": req_id,
            "source_id": f"INV-0{req_id[-2:]}",
            "source_ref": {"kind": "xlsx", "sheet": "requirements", "row": int(req_id[-2:]) + 1},
            "text": text,
            "original_text": text,
            "type": type_,
            "nfr_category": category,
            "analysis_version": 1,
        }
    )


def _state() -> DesignState:
    return DesignState(
        run_id="run-1",
        requirements=(
            _req("REQ-01", "창고 담당자는 창고를 등록·조회·수정할 수 있어야 한다."),
            _req("REQ-02", "확정 수불은 한 번만 취소할 수 있다."),
            _req(
                "REQ-03",
                "조회 전용 사용자는 조회만 수행한다.",
                type_="NFR",
                category="security",
            ),
        ),
    )


def _function(name: str, req_ids: tuple[str, ...], **extra: Any) -> FunctionDraft:
    return FunctionDraft.model_validate(
        {"name": name, "description": f"{name}을 처리한다", "req_ids": req_ids, **extra}
    )


def _valid_output() -> A02Output:
    return A02Output(
        functions=(
            _function("창고 관리", ("REQ-01",)),
            _function("수불 취소", ("REQ-02", "REQ-03")),
        )
    )


def _raw(functions: list[dict[str, Any]]) -> str:
    """출력 모델을 거치지 않은 LLM 응답. 형식 위반을 재현할 때 쓴다."""
    return json.dumps({"functions": functions}, ensure_ascii=False)


# 정상 응답


def test_assigns_function_ids_and_leaves_crud_empty() -> None:
    client, transport = stub_client(reply(_valid_output()))

    result = run(client, _state(), _settings(), pack="inventory")

    assert [f.id for f in result.output] == ["FUNC-01", "FUNC-02"]
    assert [f.req_ids for f in result.output] == [("REQ-01",), ("REQ-02", "REQ-03")]
    assert all(f.entity_ops == () for f in result.output)
    assert len(transport.sent) == 1
    assert [c.outcome for c in result.calls] == ["ok"]


def test_request_uses_design_model_prompt_version_and_few_shot() -> None:
    settings = _settings()
    client, transport = stub_client(reply(_valid_output()))

    run(client, _state(), settings, pack="inventory")

    (request,) = transport.sent
    assert (request.stage, request.prompt_version, request.model) == (
        "A02",
        PROMPT_VERSION,
        settings.design_model,
    )
    # system, few-shot(user·assistant), 실제 입력
    assert [m.role for m in request.messages] == ["system", "user", "assistant", "user"]
    sent = json.loads(unwrap_data(request.messages[-1].content))
    assert [r["id"] for r in sent["requirements"]] == ["REQ-01", "REQ-02", "REQ-03"]


def test_input_hides_run_metadata() -> None:
    (first, *_) = input_data(_state())["requirements"]

    assert set(first) == {"id", "type", "nfr_category", "text"}


def test_low_or_missing_priority_never_removes_a_function() -> None:
    output = A02Output(
        functions=(
            _function("창고 관리", ("REQ-01",)),
            _function(
                "수불 취소",
                ("REQ-02",),
                priority="Won't",
                priority_source="explicit",
                priority_rationale="확정 수불은 한 번만 취소할 수 있다.",
            ),
        )
    )
    client, _ = stub_client(reply(output))

    result = run(client, _state(), _settings(), pack="inventory")

    assert [(f.name, f.priority, f.priority_source) for f in result.output] == [
        ("창고 관리", None, "unspecified"),
        ("수불 취소", "Won't", "explicit"),
    ]


# 계약 오류: 재요청 후 통과하거나 LLMContractError


def test_unknown_requirement_reference_is_sent_back_for_retry() -> None:
    bad = A02Output(functions=(_function("창고 관리", ("REQ-01", "REQ-99")),))
    client, transport = stub_client(reply(bad), reply(_valid_output()))

    result = run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2
    retry_note = transport.sent[1].messages[-1].content
    assert "REQ-99" in retry_note
    assert [f.id for f in result.output] == ["FUNC-01", "FUNC-02"]


def test_unknown_requirement_reference_that_persists_fails_the_node() -> None:
    bad = A02Output(functions=(_function("창고 관리", ("REQ-99",)),))
    client, transport = stub_client(reply(bad), reply(bad), reply(bad))

    with pytest.raises(LLMContractError) as caught:
        run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 3
    assert [c.outcome for c in caught.value.calls] == ["invalid_output"] * 3


def test_crud_or_ids_in_llm_output_are_rejected() -> None:
    with_crud = _raw(
        [
            {
                "name": "창고 관리",
                "description": "창고를 관리한다",
                "req_ids": ["REQ-01"],
                "id": "FUNC-07",
                "entity_ops": [{"entity_id": "ENT-01", "operations": ["C"]}],
            }
        ]
    )
    client, transport = stub_client(reply(with_crud), reply(_valid_output()))

    run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2


def test_empty_function_list_is_not_accepted_as_success() -> None:
    client, transport = stub_client(reply(_raw([])), reply(_valid_output()))

    run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2


def test_duplicate_function_names_are_rejected() -> None:
    duplicated = _raw(
        [
            {"name": "창고 관리", "description": "a", "req_ids": ["REQ-01"]},
            {"name": "창고 관리", "description": "b", "req_ids": ["REQ-02"]},
        ]
    )
    client, transport = stub_client(reply(duplicated), reply(_valid_output()))

    run(client, _state(), _settings(), pack="inventory")

    assert "중복" in transport.sent[1].messages[-1].content


# 근거 부족


def test_inferred_priority_without_rationale_is_rejected() -> None:
    no_rationale = _raw(
        [
            {
                "name": "수불 취소",
                "description": "확정 수불을 취소한다",
                "req_ids": ["REQ-02"],
                "priority": "Must",
                "priority_source": "inferred",
            }
        ]
    )
    client, transport = stub_client(reply(no_rationale), reply(_valid_output()))

    run(client, _state(), _settings(), pack="inventory")

    assert "priority_rationale" in transport.sent[1].messages[-1].content


def test_rationale_that_is_not_a_quote_of_its_requirement_is_rejected() -> None:
    made_up = _raw(
        [
            {
                "name": "수불 취소",
                "description": "확정 수불을 취소한다",
                "req_ids": ["REQ-02"],
                "priority": "Must",
                "priority_source": "inferred",
                "priority_rationale": "취소는 업무상 매우 중요하다",
            }
        ]
    )
    client, transport = stub_client(reply(made_up), reply(_valid_output()))

    run(client, _state(), _settings(), pack="inventory")

    assert "인용이 아닙니다" in transport.sent[1].messages[-1].content


def test_rationale_quoting_another_functions_requirement_is_rejected() -> None:
    wrong_source = _raw(
        [
            {
                "name": "창고 관리",
                "description": "창고를 관리한다",
                "req_ids": ["REQ-01"],
                "priority": "Must",
                "priority_source": "inferred",
                "priority_rationale": "확정 수불은 한 번만 취소할 수 있다.",
            }
        ]
    )
    client, transport = stub_client(reply(wrong_source), reply(_valid_output()))

    run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2


def test_priority_value_without_source_is_rejected() -> None:
    guessed = _raw(
        [{"name": "창고 관리", "description": "a", "req_ids": ["REQ-01"], "priority": "Must"}]
    )
    client, transport = stub_client(reply(guessed), reply(_valid_output()))

    run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2


# 실패 전달


def test_refusal_is_raised_without_retry() -> None:
    client, transport = stub_client(refusal())

    with pytest.raises(LLMRefusalError):
        run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 1


def test_timeout_is_raised_not_turned_into_empty_result() -> None:
    client, _ = stub_client(LLMTimeoutError("응답 없음"))

    with pytest.raises(LLMTimeoutError):
        run(client, _state(), _settings(), pack="inventory")


def test_no_requirements_fails_before_calling_the_llm() -> None:
    client, transport = stub_client()

    with pytest.raises(ValueError, match="요구사항"):
        run(client, DesignState(run_id="run-1"), _settings(), pack="inventory")

    assert transport.sent == ()


# 프롬프트


def test_prompt_does_not_promise_unimplemented_unlinked_marking() -> None:
    assert "미연결은 코드가 표시" not in SYSTEM_PROMPT


def test_prompt_attaches_nfr_to_business_functions() -> None:
    assert "비기능 요구는 따로 모아 기능을 만들지 않는다" in SYSTEM_PROMPT


# few-shot 예시


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_pack_examples_match_the_output_model_and_input_shape(pack: str) -> None:
    examples = load_examples(pack, "A02", A02Output)

    assert examples
    for example in examples:
        assert isinstance(example.input, dict)
        expected_keys = set(input_data(_state())["requirements"][0])
        assert all(set(r) == expected_keys for r in example.input["requirements"])
        known = {r["id"] for r in example.input["requirements"]}
        assert {i for f in example.output.functions for i in f.req_ids} <= known


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_pack_examples_never_make_an_nfr_only_function(pack: str) -> None:
    """few-shot은 본보기다. 비기능 요구만 모은 기능을 보여 주면 모델이 그대로 따라 한다."""
    for example in load_examples(pack, "A02", A02Output):
        assert isinstance(example.input, dict)
        types = {r["id"]: r["type"] for r in example.input["requirements"]}
        for function in example.output.functions:
            assert any(types[r] == "FR" for r in function.req_ids), function.name
