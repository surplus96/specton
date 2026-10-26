"""계약 모델이 docs/api/openapi.json 초안과 같은지 확인한다 (06 문서)."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from specton.contracts import (
    Error,
    ErrorCode,
    ExtractionResponse,
    Interrupt,
    RequirementsResponse,
    ResumeRequest,
    ReviewResponse,
    RunStatus,
    RunSummary,
    RunView,
    SseEvent,
    SseEventData,
)
from specton.contracts.base import Contract

OPENAPI = json.loads(
    (Path(__file__).parents[2] / "docs" / "api" / "openapi.json").read_text(encoding="utf-8")
)
SCHEMAS: dict[str, Any] = OPENAPI["components"]["schemas"]

MODELS: dict[str, type[Contract]] = {
    "Error": Error,
    "SseEvent": SseEvent,
    "SseEventData": SseEventData,
    "Interrupt": Interrupt,
    "RunStatus": RunStatus,
    "RunSummary": RunSummary,
    "RunView": RunView,
    "ResumeRequest": ResumeRequest,
    "ExtractionResponse": ExtractionResponse,
    "RequirementsResponse": RequirementsResponse,
    "ReviewResponse": ReviewResponse,
}


def _enum_values(prop: dict[str, Any]) -> list[str] | None:
    if "enum" in prop:
        return list(prop["enum"])
    return None


@pytest.mark.parametrize("name", sorted(MODELS))
def test_fields_and_required_match_openapi(name: str) -> None:
    spec = SCHEMAS[name]
    generated = MODELS[name].model_json_schema()

    assert set(generated["properties"]) == set(spec["properties"])
    assert set(generated.get("required", [])) == set(spec["required"])


def test_run_state_matches_openapi_enum() -> None:
    expected = SCHEMAS["RunStatus"]["properties"]["status"]["enum"]
    generated = RunStatus.model_json_schema()
    ref = generated["properties"]["status"]["$ref"].split("/")[-1]

    assert generated["$defs"][ref]["enum"] == expected
    assert SCHEMAS["RunSummary"]["properties"]["status"]["enum"] == expected


def test_interrupt_kind_and_review_decision_match_openapi() -> None:
    kinds = SCHEMAS["Interrupt"]["properties"]["kind"]["enum"]
    generated = Interrupt.model_json_schema()
    ref = generated["properties"]["kind"]["$ref"].split("/")[-1]
    assert generated["$defs"][ref]["enum"] == kinds

    decisions = SCHEMAS["ReviewResponse"]["properties"]["decision"]["enum"]
    assert ReviewResponse.model_json_schema()["properties"]["decision"]["enum"] == decisions


def test_resume_request_selects_response_by_kind() -> None:
    body = {
        "interrupt_id": "int-1",
        "expected_revision": 2,
        "response": {"kind": "review", "decision": "revise", "feedback": "근거 확인 필요"},
    }
    assert isinstance(ResumeRequest.model_validate(body).response, ReviewResponse)

    body["response"] = {
        "kind": "requirements",
        "answers": [{"req_id": "REQ-01", "action": "split", "texts": ["a", "b"]}],
    }
    assert isinstance(ResumeRequest.model_validate(body).response, RequirementsResponse)


@pytest.mark.parametrize(
    "response",
    [
        {"kind": "review", "decision": "maybe", "feedback": ""},
        {"kind": "unknown"},
        {"kind": "extraction", "confirmed": True},
    ],
)
def test_invalid_resume_response_is_rejected(response: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ResumeRequest.model_validate(
            {"interrupt_id": "int-1", "expected_revision": 0, "response": response}
        )


def test_run_status_example_with_interrupt() -> None:
    status = RunStatus.model_validate(
        {
            "run_id": str(uuid4()),
            "status": "awaiting_review",
            "revision": 2,
            "stage": "review",
            "interrupt": {"interrupt_id": "int-1", "kind": "review", "message": "최종 검토 대기"},
        }
    )
    assert status.error is None
    assert status.interrupt is not None


def test_error_example_uses_documented_shape() -> None:
    error = Error.model_validate(
        {
            "code": ErrorCode.RUN_REVISION_CONFLICT,
            "message": "다른 revision입니다.",
            "run_id": "r-1",
            "retryable": False,
        }
    )
    assert error.model_dump()["code"] == "RUN_REVISION_CONFLICT"


def test_run_summary_requires_created_at() -> None:
    with pytest.raises(ValidationError):
        RunSummary.model_validate({"run_id": str(uuid4()), "status": "queued", "revision": 0})


def test_run_view_section_is_limited() -> None:
    with pytest.raises(ValidationError):
        RunView.model_validate(
            {"run_id": str(uuid4()), "revision": 0, "section": "other", "items": []}
        )


def test_sse_event_encodes_documented_wire_format() -> None:
    event = SseEvent.model_validate(
        {
            "id": 12,
            "event": "interrupt",
            "data": {
                "run_id": "example",
                "revision": 2,
                "stage": "review",
                "message": "최종 검토 대기",
                "payload": {"interrupt_id": "int-example"},
            },
        }
    )

    lines = event.encode().split("\n")

    assert lines[0] == "id: 12"
    assert lines[1] == "event: interrupt"
    assert json.loads(lines[2].removeprefix("data: "))["payload"] == {"interrupt_id": "int-example"}
    assert event.encode().endswith("\n\n")


def test_sse_event_type_is_limited_to_documented_kinds() -> None:
    with pytest.raises(ValidationError):
        SseEvent.model_validate(
            {"id": 1, "event": "progress", "data": {"run_id": "r", "revision": 0, "message": "m"}}
        )


def test_error_codes_cover_run_failure_causes() -> None:
    run_failures = {
        "LLM_REFUSED",
        "LLM_OUTPUT_INVALID",
        "LLM_UNAVAILABLE",
        "BUDGET_EXCEEDED",
        "EXTRACTION_FAILED",
    }

    assert run_failures <= {c.value for c in ErrorCode}


def test_sse_event_types_and_error_codes_match_openapi() -> None:
    generated = SseEvent.model_json_schema()
    ref = generated["properties"]["event"]["$ref"].split("/")[-1]
    assert generated["$defs"][ref]["enum"] == SCHEMAS["SseEvent"]["properties"]["event"]["enum"]
    assert [c.value for c in ErrorCode] == SCHEMAS["ErrorCode"]["enum"]
