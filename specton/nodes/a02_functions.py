"""A02 기능 설계 노드 (04 문서, REQ-06, TC-A02).

확인된 요구사항을 기능으로 나누거나 묶고, 기능마다 설명·우선순위·근거·req_ids를 받는다.
- 기능 ID는 코드가 붙인다. CRUD(`entity_ops`)는 A03가 채우므로 출력에 없다.
- req_ids는 이번 입력에 있는 요구사항만, 우선순위 근거는 그 요구 문장의 인용만 허용한다.
  어기면 공통 client가 재요청한다.
- 우선순위는 명시값만 `explicit`, 추정은 `inferred`(근거 필수), 없으면 null (ADR-0006).
  우선순위로 기능을 빼지 않는다.
"""

from collections.abc import Mapping
from typing import Any, Self

from pydantic import Field, model_validator

from specton.config import Settings
from specton.contracts import DesignState, Function, FunctionDraft, PrioritySource
from specton.contracts.base import Contract
from specton.llm.client import LLMClient
from specton.nodes.common import NodeRun, assign_ids, build_request
from specton.packs.examples import load_examples

PROMPT_VERSION = "a02-v1"
SYSTEM_PROMPT = """\
너는 업무 시스템의 기능 설계자다. 확인된 요구사항을 사용자가 수행하는 기능 단위로 정리한다.

할 일:
- 같은 사용자가 같은 대상에 대해 함께 수행하는 요구사항은 한 기능으로 묶는다.
- 성격이 다른 작업(예: 등록과 취소, 처리와 조회)은 기능을 나눈다.
- 기능마다 name(짧은 명사형), description(무엇을 어떤 조건으로 하는지 1~2문장), req_ids를 쓴다.
- req_ids에는 그 기능이 충족하는 요구사항의 id만 입력에서 골라 적는다.
- 기능에 연결할 수 없는 요구사항은 억지로 기능을 만들어 붙이지 않는다.
- 권한·감사·보존 같은 비기능 요구는 따로 모아 기능을 만들지 않는다. 그 요구가 제약하는 업무 기능의
  description에 조건을 쓰고 req_ids에 함께 적는다.

우선순위(MoSCoW: Must, Should, Could, Won't):
- 요구사항 문장에 우선순위가 명시돼 있으면 그 값을 priority에, priority_source는 explicit로 쓴다.
- 명시가 없으면 priority는 null, priority_source는 unspecified로 둔다. 이것이 기본이다.
- 요구 문장에 분명한 근거가 있을 때만 추정하고 priority_source를 inferred로 쓴다.
- explicit·inferred에는 priority_rationale에 근거가 된 요구 문장을 그대로 인용한다.
- 우선순위가 낮거나 미정이어도 기능을 빼지 않는다.

출력하지 않는 것: 기능 ID, 엔티티·테이블·컬럼, CRUD."""


class A02Output(Contract):
    """A02 LLM 출력. 계약의 FunctionDraft로만 구성한다."""

    functions: tuple[FunctionDraft, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_functions(self) -> Self:
        names = [f.name for f in self.functions]
        duplicated = sorted({n for n in names if names.count(n) > 1})
        if duplicated:
            raise ValueError(f"기능 이름이 중복됩니다: {', '.join(duplicated)}")
        unsupported = [
            f.name
            for f in self.functions
            if f.priority_source is not PrioritySource.UNSPECIFIED and not f.priority_rationale
        ]
        if unsupported:
            raise ValueError(
                f"우선순위 근거(priority_rationale)가 없습니다: {', '.join(unsupported)}"
            )
        return self


def run(
    client: LLMClient,
    state: DesignState,
    settings: Settings,
    *,
    pack: str,
    token_budget: int | None = None,
) -> NodeRun[tuple[Function, ...]]:
    """요구사항으로 기능을 설계하고 코드가 ID를 붙인 Function을 돌려준다."""
    if not state.requirements:
        raise ValueError("A02: 기능을 설계할 요구사항이 없습니다")
    request = build_request(
        settings,
        role="design",
        stage="A02",
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        data=input_data(state),
        examples=load_examples(pack, "A02", A02Output),
    )
    output_model = _checked_against({r.id: r.text for r in state.requirements})
    result = client.complete(request, output_model, token_budget=token_budget)
    drafts = result.output.functions
    ids = assign_ids("FUNC", len(drafts))
    functions = tuple(
        Function.model_validate({**d.model_dump(), "id": i})
        for d, i in zip(drafts, ids, strict=True)
    )
    return NodeRun(output=functions, calls=result.calls)


def input_data(state: DesignState) -> dict[str, Any]:
    """LLM에 보여 줄 요구사항. 원문 위치·버전 같은 실행 메타데이터는 넣지 않는다.

    few-shot 예시의 `input`도 이 모양으로 쓴다.
    """
    return {
        "requirements": [
            {"id": r.id, "type": r.type.value, "nfr_category": r.nfr_category, "text": r.text}
            for r in state.requirements
        ]
    }


def _checked_against(texts: Mapping[str, str]) -> type[A02Output]:
    """이번 입력으로 검사하는 출력 모델. 어기면 형식 오류처럼 재요청 대상이 된다.

    - req_ids는 입력에 있는 요구사항만 허용한다.
    - priority_rationale은 그 기능이 참조한 요구사항 문장을 그대로 인용해야 한다.
    """

    class CheckedA02Output(A02Output):
        @model_validator(mode="after")
        def _check_against_input(self) -> Self:
            referenced = {req_id for f in self.functions for req_id in f.req_ids}
            unknown = sorted(referenced - texts.keys())
            if unknown:
                raise ValueError(f"입력에 없는 요구사항을 참조했습니다: {', '.join(unknown)}")
            unquoted = [
                f.name
                for f in self.functions
                if f.priority_rationale
                and not any(f.priority_rationale in texts[r] for r in f.req_ids)
            ]
            if unquoted:
                raise ValueError(
                    "priority_rationale이 참조한 요구사항 문장의 인용이 아닙니다: "
                    + ", ".join(unquoted)
                )
            return self

    return CheckedA02Output
