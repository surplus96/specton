"""A04 관계 설계 (04 문서, REQ-08).

A03 엔티티 사이의 관계(방향·카디널리티·선택 여부·식별 여부)를 LLM이 판단한다.
LLM은 엔티티를 이름으로 가리키고, 코드가 이름을 엔티티 ID로 바꾸고 관계 ID를 붙인다.
FK·연결 테이블은 모델 정리(#12)가 관계에서 파생하므로 여기서 만들지 않는다.
- 없는 엔티티 이름이나 입력에 없는 REQ ID를 가리키면 공통 client가 재요청한다.
- rationale은 그 관계가 참조한 요구사항 문장을 큰따옴표로 인용해야 한다. 아니면 재요청한다.
- 엔티티가 없거나 이름이 겹치면 입력 상태의 문제이므로 LLM을 부르지 않고 멈춘다.
"""

import re
from collections.abc import Collection, Mapping
from typing import Any, Self

from pydantic import model_validator

from specton.config import Settings
from specton.contracts import Cardinality, DesignState, Relationship, RelationshipDraft
from specton.contracts.base import Contract
from specton.llm.client import LLMClient
from specton.nodes.common import NodeRun, assign_ids, build_request
from specton.packs.examples import load_examples

PROMPT_VERSION = "a04-v1"
SYSTEM_PROMPT = """\
너는 데이터 모델 관계 설계자다. 주어진 엔티티 사이의 관계를 요구사항에 근거해 판단한다.
- parent_name·child_name에는 입력 엔티티의 name을 그대로 쓴다.
- cardinality: 부모 1건에 자식이 최대 1건이면 1:1, 여러 건이면 1:N, 양쪽 모두 여러 건이면 N:M.
- N:M은 연결 엔티티를 만들지 않고 N:M 관계 하나로 적는다.
- 같은 엔티티끼리의 관계(자기참조, 예: 상위 부서)는 parent_name과 child_name에 같은 이름을 쓴다.
- optional: 자식이 부모 없이 존재할 수 있으면 true.
- identifying: 자식이 부모 없이는 식별되지 않으면 true. 자기참조와 N:M에는 쓰지 않는다.
- FK 속성이나 키 컬럼을 만들지 않는다.
- req_ids에는 근거 요구사항 ID를 적는다.
- rationale은 req_ids 요구사항 문장에서 근거 부분을 큰따옴표로 그대로 인용하고,
  판단 설명을 한 문장 덧붙인다.
  예: "하나의 수불 문서에는 하나 이상의 품목 내역을 등록한다." 내역은 문서에 속한다.
- 같은 두 엔티티 사이에도 의미가 다르면 관계를 따로 적는다.
- 요구사항에 근거가 없는 관계는 만들지 않는다."""

_QUOTE = re.compile(r'"([^"]+)"')


class A04Output(Contract):
    relationships: tuple[RelationshipDraft, ...]

    @model_validator(mode="after")
    def _check_identifying(self) -> Self:
        invalid = [
            f"{r.parent_name}→{r.child_name}"
            for r in self.relationships
            if r.identifying
            and (r.parent_name == r.child_name or r.cardinality is Cardinality.MANY_TO_MANY)
        ]
        if invalid:
            raise ValueError("자기참조·N:M 관계는 identifying일 수 없습니다: " + ", ".join(invalid))
        return self


def run(
    client: LLMClient,
    state: DesignState,
    settings: Settings,
    *,
    pack: str,
    token_budget: int | None = None,
) -> NodeRun[tuple[Relationship, ...]]:
    """현재 엔티티·요구사항으로 관계를 설계하고 코드가 ID를 붙인다."""
    if not state.entities:
        raise ValueError("A04: 관계를 설계할 엔티티가 없습니다")
    names = [e.name for e in state.entities]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise ValueError(f"A04: 엔티티 이름이 중복됩니다: {', '.join(duplicated)}")
    request = build_request(
        settings,
        role="design",
        stage="A04",
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        data=input_data(state),
        examples=load_examples(pack, "A04", A04Output),
    )
    entity_ids = {e.name: e.id for e in state.entities}
    output_model = _checked_against(entity_ids.keys(), {r.id: r.text for r in state.requirements})
    result = client.complete(request, output_model, token_budget=token_budget)
    drafts = result.output.relationships
    ids = assign_ids("REL", len(drafts))
    relationships = tuple(
        Relationship.model_validate(
            {
                **d.model_dump(exclude={"parent_name", "child_name"}),
                "id": i,
                "parent": entity_ids[d.parent_name],
                "child": entity_ids[d.child_name],
            }
        )
        for d, i in zip(drafts, ids, strict=True)
    )
    return NodeRun(output=relationships, calls=result.calls)


def input_data(state: DesignState) -> dict[str, Any]:
    """LLM에 보여 줄 엔티티·요구사항. few-shot 예시의 `input`도 이 모양으로 쓴다.

    엔티티는 이름·설명·속성만 넘긴다. ID는 LLM이 쓰지 않으므로 빼고, 이름으로 가리키게 한다.
    """
    return {
        "entities": [
            e.model_dump(
                mode="json",
                include={
                    "name": True,
                    "description": True,
                    "attributes": {"__all__": {"name", "data_type", "is_key", "nullable"}},
                },
            )
            for e in state.entities
        ],
        "requirements": [
            r.model_dump(mode="json", include={"id", "text", "type"}) for r in state.requirements
        ],
    }


def _checked_against(entity_names: Collection[str], texts: Mapping[str, str]) -> type[A04Output]:
    """이번 입력으로 검사하는 출력 모델. 어기면 형식 오류처럼 재요청 대상이 된다.

    - parent_name·child_name은 입력에 있는 엔티티 이름만 허용한다.
    - req_ids는 입력에 있는 요구사항만 허용한다.
    - rationale의 큰따옴표 인용은 그 관계의 req_ids 요구사항 문장(LLM에 보낸 text)에 있어야 한다.
    """
    normalized = {req_id: _normalize(text) for req_id, text in texts.items()}

    class CheckedA04Output(A04Output):
        @model_validator(mode="after")
        def _check_against_input(self) -> Self:
            names = {n for r in self.relationships for n in (r.parent_name, r.child_name)}
            unknown_names = sorted(names - set(entity_names))
            if unknown_names:
                raise ValueError(f"입력에 없는 엔티티를 참조했습니다: {', '.join(unknown_names)}")
            referenced = {req_id for r in self.relationships for req_id in r.req_ids}
            unknown_reqs = sorted(referenced - normalized.keys())
            if unknown_reqs:
                raise ValueError(f"입력에 없는 요구사항을 참조했습니다: {', '.join(unknown_reqs)}")
            unquoted = [
                f"{r.parent_name}→{r.child_name}"
                for r in self.relationships
                if not _quotes_requirements(r, normalized)
            ]
            if unquoted:
                raise ValueError(
                    "rationale이 참조한 요구사항 문장을 큰따옴표로 인용하지 않았습니다: "
                    + ", ".join(unquoted)
                )
            return self

    return CheckedA04Output


def _quotes_requirements(rel: RelationshipDraft, texts: Mapping[str, str]) -> bool:
    """인용이 하나 이상 있고, 모든 인용이 그 관계의 req_ids 문장 중 하나에 들어 있는지."""
    quotes = [_normalize(q) for q in _QUOTE.findall(rel.rationale)]
    pool = [texts[req_id] for req_id in rel.req_ids]
    return bool(quotes) and all(any(q in text for text in pool) for q in quotes)


def _normalize(text: str) -> str:
    """줄바꿈·연속 공백 차이만 무시한다 (review/merge.py의 `_normalize`와 같은 기준)."""
    return " ".join(text.split())
