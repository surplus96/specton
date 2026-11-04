"""A01 요구사항 분석 노드 (TC-A01). 실제 LLM 없이 stub 응답으로 검증한다."""

import json
from typing import Any

import pytest

from specton.config import Settings
from specton.contracts import DesignState
from specton.contracts.requirements import RequirementDraft, SourceRequirement
from specton.llm.errors import LLMContractError, LLMRefusalError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.a01_requirements import (
    ADDED_NUMBER,
    PROMPT_VERSION,
    A01Output,
    _checked_against,
    _numbers_not_in,
    input_data,
    run,
)
from specton.nodes.common import unwrap_data
from specton.packs.examples import load_examples


def _settings() -> Settings:
    return Settings(_env_file=None)


def _block(row: int, text: str, source_id: str | None = None) -> SourceRequirement:
    return SourceRequirement(
        document_id="doc-1",
        block_id=f"xlsx:요구사항:{row}",
        source_id=source_id,
        source_ref={"file_format": "xlsx", "sheet": "요구사항", "row": row},
        source_text=text,
        source_acceptance_level="필수",
    )


def _state() -> DesignState:
    return DesignState(
        run_id="run-1",
        source_requirements=(
            _block(2, "창고를 등록·조회한다. 화면은 3초 안에 열려야 한다.", "SFR-001"),
            _block(3, "현재고는 0 미만이 될 수 없다.", "SFR-002"),
        ),
    )


def _draft(blocks: list[str], text: str, **kw: Any) -> RequirementDraft:
    return RequirementDraft.model_validate(
        {"source_block_ids": blocks, "text": text, "type": "FR", **kw}
    )


def _normal() -> A01Output:
    return A01Output(
        requirements=(
            _draft(["xlsx:요구사항:2"], "창고를 등록·조회한다.", parent_hint="창고"),
            _draft(
                ["xlsx:요구사항:2"],
                "창고 화면은 3초 안에 열려야 한다.",
                type="NFR",
                nfr_category="performance",
                parent_hint="창고",
            ),
            _draft(["xlsx:요구사항:3"], "현재고는 0 미만이 될 수 없다."),
        )
    )


def test_a01_splits_and_links_requirements_to_source() -> None:
    client, transport = stub_client(reply(_normal()))

    result = run(client, _state(), _settings(), pack="inventory")

    assert [r.id for r in result.output] == ["REQ-01", "REQ-02", "REQ-03"]
    first, second, third = result.output
    # 나눈 두 요구사항은 같은 원문을 가리키고 parent_id는 비운다 (부모는 원문)
    assert first.source_id == second.source_id == "SFR-001"
    assert first.parent_id is None and second.parent_id is None
    assert first.source_text == "창고를 등록·조회한다. 화면은 3초 안에 열려야 한다."
    assert first.draft_text == first.text
    assert second.nfr_category == "performance"
    assert third.source_acceptance_level == "필수"
    assert third.source_ref.row == 3
    assert len(transport.sent) == 1
    assert result.calls[0].prompt_version == PROMPT_VERSION


def test_a01_sends_only_block_text_and_extra() -> None:
    client, transport = stub_client(reply(_normal()))

    run(client, _state(), _settings(), pack="inventory")

    data = json.loads(unwrap_data(transport.sent[0].messages[-1].content))
    assert data == input_data(_state())
    assert set(data["source_blocks"][0]) == {"block_id", "text", "acceptance_level", "extra"}


def test_a01_retries_when_a_block_is_dropped() -> None:
    """분할 원문 누락: 입력 블록을 하나라도 빠뜨리면 재요청한다."""
    dropped = A01Output(requirements=(_draft(["xlsx:요구사항:2"], "창고를 등록·조회한다."),))
    client, transport = stub_client(reply(dropped), reply(_normal()))

    run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2


def test_a01_flags_a_number_not_in_source() -> None:
    """원문 없는 조건 추가: 원문에 없는 수치는 재요청 대신 품질 경고로 남긴다."""
    added = A01Output(
        requirements=(
            _draft(["xlsx:요구사항:2"], "창고 화면은 30초 안에 열려야 한다."),
            _draft(["xlsx:요구사항:3"], "현재고는 0 미만이 될 수 없다."),
        )
    )
    client, transport = stub_client(reply(added))

    result = run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 1
    assert [q.kind for q in result.output[0].quality_issues] == [ADDED_NUMBER]
    assert "30" in result.output[0].quality_issues[0].message
    assert result.output[1].quality_issues == ()


@pytest.mark.parametrize(
    ("text", "source", "added"),
    [
        ("3초", "30초", ["3"]),  # 부분 문자열로 통과시키지 않는다
        ("100건", "1000건", ["100"]),
        ("2026-10-01", "2026.10.1", []),  # 앞의 0 차이는 같게 본다
        ("1,000건", "1000건", []),  # 천 단위 쉼표
        ("0.5초", "0.5초", []),
    ],
)
def test_a01_number_check(text: str, source: str, added: list[str]) -> None:
    assert _numbers_not_in(text, source) == added


def test_a01_retries_when_one_requirement_points_to_two_blocks() -> None:
    """Requirement의 원문 위치는 하나라서 블록 둘을 가리키면 재요청한다."""
    merged = A01Output(
        requirements=(_draft(["xlsx:요구사항:2", "xlsx:요구사항:3"], "창고와 재고를 관리한다."),)
    )
    client, transport = stub_client(reply(merged), reply(_normal()))

    run(client, _state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2


def test_a01_raises_after_repeated_unknown_block() -> None:
    """계약 오류: 입력에 없는 블록을 계속 가리키면 LLMContractError로 끝난다."""
    unknown = A01Output(requirements=(_draft(["xlsx:요구사항:99"], "없는 블록"),))
    client, _ = stub_client(reply(unknown), reply(unknown), reply(unknown))

    with pytest.raises(LLMContractError):
        run(client, _state(), _settings(), pack="inventory")


def test_a01_raises_refusal() -> None:
    client, _ = stub_client(refusal())

    with pytest.raises(LLMRefusalError):
        run(client, _state(), _settings(), pack="inventory")


def test_a01_requires_source_blocks() -> None:
    client, _ = stub_client()

    with pytest.raises(ValueError, match="원문 블록"):
        run(client, DesignState(run_id="run-1"), _settings(), pack="inventory")


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_a01_examples_load_and_cover_their_blocks(pack: str) -> None:
    for example in load_examples(pack, "A01", A01Output):
        assert isinstance(example.input, dict)
        blocks = {b["block_id"] for b in example.input["source_blocks"]}
        used = {b for r in example.output.requirements for b in r.source_block_ids}
        assert used == blocks
        # 예시도 노드 자체 검사(블록 하나·누락 없음)를 통과해야 한다
        texts = {b["block_id"]: b["text"] for b in example.input["source_blocks"]}
        _checked_against(texts).model_validate(example.output.model_dump())
