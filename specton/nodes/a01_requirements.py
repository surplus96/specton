"""A01 요구사항 분석 노드 (04 문서, REQ-04, TC-A01).

추출된 원문 블록(`DesignState.source_requirements`)을 읽어 요구사항 초안으로 나누고 분류한다.
- 추출 확인에서 제외한 블록과 원문 문장이 없는 블록은 넣지 않는다 (`analysable`, ADR-0015).
- 한 블록에 요구가 여러 개면 나눈다(분할). 블록마다 적어도 요구사항 하나에 연결돼야 한다.
- FR/NFR을 정하고 NFR이면 `nfr_category`를 붙인다. 데이터 정합성 요구는 FR이다 (05 문서).
- 모호한 표현은 품질 경고로 남기고, 사용자에게 물을 것은 `question`에 쓴다.
- 요구사항 ID·원문 연결(source_id·source_ref·source_text)·parent_id는 코드가 채운다.
  나눈 요구사항의 부모는 원문이므로 parent_id는 비워 두고 source_id로 잇는다.
- 입력에 없는 블록을 가리키거나, 블록을 빠뜨리거나, 요구사항 하나가 블록 여러 개를 가리키면
  재요청한다.
- 요구사항 문장에 원문에 없는 수치가 있으면 재요청하지 않고 품질 경고(`added_number`)로 남긴다
  (숫자 표기 차이로 오탐이 날 수 있어 사람이 확인한다).
"""

import re
from collections.abc import Mapping
from typing import Any, Self

from pydantic import Field, model_validator

from specton.config import Settings
from specton.contracts import DesignState
from specton.contracts.base import Contract
from specton.contracts.requirements import (
    QualityIssue,
    Requirement,
    RequirementDraft,
    SourceRequirement,
)
from specton.llm.client import LLMClient
from specton.nodes.common import NodeRun, assign_ids, build_request
from specton.packs.examples import load_examples

PROMPT_VERSION = "a01-v1"
SYSTEM_PROMPT = """\
너는 업무 시스템의 요구사항 분석가다.
고객 문서에서 추출한 원문 블록을 읽고 요구사항 문장으로 정리한다.

할 일:
- 블록 하나에 서로 다른 요구가 여러 개 있으면 요구사항을 나눈다. 번호 목록(①, 1., -)의 항목이
  서로 다른 기능이나 조건이면 각각 하나의 요구사항이다. 같은 요구를 다르게 쓴 것은 나누지 않는다.
- 모든 블록은 적어도 요구사항 하나의 source_block_ids에 들어가야 한다. 블록을 빠뜨리지 않는다.
- 요구사항 하나는 블록 하나에서만 만든다. source_block_ids에는 블록 ID를 하나만 쓴다.
- text는 원문의 뜻을 그대로 옮긴 한 문장 또는 두 문장이다.
  원문에 없는 조건·수치·대상을 더하지 않는다.
- type은 FR(기능) 또는 NFR(비기능)이다.
  성능·보안·가용성·사용성처럼 시스템 품질을 정하는 요구는 NFR이고
  nfr_category를 쓴다(애매하면 other).
  데이터가 지켜야 할 값의 조건(예: 재고는 0 미만이 될 수 없다)은 FR이다.
- 나눈 요구사항에는 parent_hint에 나누기 전 요구의 짧은 단서를 쓴다. 나누지 않았으면 null이다.
- 확인할 것은 quality_issues에 남긴다. kind는 아래 값 중 하나만 쓰고, message에 이유를 쓰고,
  사용자에게 확인해야 하면 question에 질문 한 문장을 쓴다.
  - ambiguous: 뜻이 둘 이상으로 읽힌다.
  - missing_value: 기준 값이나 값 목록이 없다(예: 빠르게, 적절히, 우선순위 값 종류).
  - missing_target: 누가 무엇에 하는지 대상이 빠졌다.
  - not_a_requirement: 블록 안에 요구사항이 아닌 단락(작업 지시, 담당자 배정, 문서 안내)이 있다.
    그 단락은 text에 옮기지 않는다. 블록 전체가 요구사항이 아니면 그 블록의 내용을 줄여 text에 쓰고
    이 kind를 남긴다.

출력하지 않는 것: 요구사항 ID, 원문 ID(source_id), 위치, 우선순위, 기능·엔티티."""

_NUMBER = re.compile(r"\d+")
ADDED_NUMBER = "added_number"  # 코드가 붙이는 품질 경고 kind


class A01Output(Contract):
    """A01 LLM 출력. 계약의 RequirementDraft로만 구성한다."""

    requirements: tuple[RequirementDraft, ...] = Field(min_length=1)


def run(
    client: LLMClient,
    state: DesignState,
    settings: Settings,
    *,
    pack: str,
    token_budget: int | None = None,
    analysis_version: int = 1,
) -> NodeRun[tuple[Requirement, ...]]:
    """원문 블록을 요구사항으로 나누고 코드가 ID·원문 연결을 붙인 Requirement를 돌려준다."""
    blocks = {b.block_id: b for b in state.source_requirements if b.analysable}
    if not blocks:
        raise ValueError("A01: 분석할 원문 블록이 없습니다")
    request = build_request(
        settings,
        role="design",
        stage="A01",
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        data=input_data(state),
        examples=load_examples(pack, "A01", A01Output, root=settings.pack_root),
    )
    output_model = _checked_against({k: _text(b) for k, b in blocks.items()})
    result = client.complete(request, output_model, token_budget=token_budget)
    drafts = result.output.requirements
    ids = assign_ids("REQ", len(drafts))
    requirements = tuple(
        _to_requirement(
            _flag_added_numbers(d, blocks), i, blocks[d.source_block_ids[0]], analysis_version
        )
        for d, i in zip(drafts, ids, strict=True)
    )
    return NodeRun(output=requirements, calls=result.calls)


def input_data(state: DesignState) -> dict[str, Any]:
    """LLM에 보여 줄 원문 블록. 위치·추출 상태 같은 실행 메타데이터는 넣지 않는다.

    few-shot 예시의 `input`도 이 모양으로 쓴다.
    """
    return {
        "source_blocks": [
            {
                "block_id": b.block_id,
                "text": _text(b),
                "acceptance_level": b.source_acceptance_level,
                "extra": dict(b.source_extra),
            }
            for b in state.source_requirements
            if b.analysable
        ]
    }


def _to_requirement(
    draft: RequirementDraft, req_id: str, block: SourceRequirement, analysis_version: int
) -> Requirement:
    """초안에 코드가 ID와 원문 연결을 붙인다. parent_hint는 저장할 칸이 없어 쓰지 않는다."""
    return Requirement.model_validate(
        {
            "id": req_id,
            "source_id": block.source_id,
            "source_ref": block.source_ref,
            "parent_id": None,
            "text": draft.text,
            "draft_text": draft.text,
            "source_text": block.source_text,
            "source_acceptance_level": block.source_acceptance_level,
            "type": draft.type,
            "nfr_category": draft.nfr_category,
            "quality_issues": draft.quality_issues,
            "analysis_version": analysis_version,
        }
    )


def _checked_against(texts: Mapping[str, str]) -> type[A01Output]:
    """이번 입력으로 검사하는 출력 모델. 어기면 형식 오류처럼 재요청 대상이 된다.

    - source_block_ids는 입력에 있는 블록 하나만 허용한다(Requirement의 원문 위치는 하나다).
    - 입력 블록은 모두 요구사항 하나 이상에 연결돼야 한다(분할 원문 누락 검출).
    """

    class CheckedA01Output(A01Output):
        @model_validator(mode="after")
        def _check_against_input(self) -> Self:
            multi = [r.text for r in self.requirements if len(r.source_block_ids) != 1]
            if multi:
                raise ValueError("요구사항 하나는 블록 하나만 가리켜야 합니다: " + "; ".join(multi))
            referenced = {b for r in self.requirements for b in r.source_block_ids}
            unknown = sorted(referenced - texts.keys())
            if unknown:
                raise ValueError(f"입력에 없는 블록을 가리켰습니다: {', '.join(unknown)}")
            missing = sorted(texts.keys() - referenced)
            if missing:
                raise ValueError(f"요구사항으로 옮기지 않은 블록이 있습니다: {', '.join(missing)}")
            return self

    return CheckedA01Output


def _flag_added_numbers(
    draft: RequirementDraft, blocks: Mapping[str, SourceRequirement]
) -> RequirementDraft:
    """원문 없는 조건 추가 검출: 원문에 없는 수치가 있으면 품질 경고를 붙인다."""
    added = _numbers_not_in(draft.text, _text(blocks[draft.source_block_ids[0]]))
    if not added:
        return draft
    issue = QualityIssue(
        kind=ADDED_NUMBER,
        message=f"원문에 없는 수치가 문장에 있습니다: {', '.join(added)}",
        question="이 수치가 원문에 있는 조건이 맞습니까?",
    )
    return draft.evolve(quality_issues=(*draft.quality_issues, issue))


def _numbers(text: str) -> set[str]:
    """숫자 묶음 집합. 천 단위 쉼표는 지우고 앞의 0은 떼어 「01」과 「1」을 같게 본다.

    소수점·날짜 구분 기호는 나눠서 본다(0.5 → 0, 5 / 2026.10.1 → 2026, 10, 1).
    """
    plain = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return {n.lstrip("0") or "0" for n in _NUMBER.findall(plain)}


def _text(block: SourceRequirement) -> str:
    """분석할 블록의 원문 문장. `analysable` 블록만 들어오므로 비어 있지 않다."""
    if block.source_text is None:
        raise ValueError(f"A01: 원문 문장이 없는 블록 {block.block_id}은 분석하지 않습니다")
    return block.source_text


def _numbers_not_in(text: str, source: str) -> list[str]:
    """문장에 있는 수치 중 원문 수치 집합에 없는 것 (「3」과 「30」을 다르게 본다)."""
    return sorted(_numbers(text) - _numbers(source))
