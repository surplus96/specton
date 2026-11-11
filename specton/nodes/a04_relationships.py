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

from specton.codegen.key_constraints import fk_nullability_matches
from specton.config import Settings
from specton.contracts import Cardinality, DesignState, Relationship, RelationshipDraft
from specton.contracts.base import Contract
from specton.llm.client import LLMClient
from specton.nodes.common import (
    USER_REQUEST_RULE,
    NodeRun,
    assign_ids,
    build_request,
    with_design_rework,
    with_user_request,
)
from specton.packs.examples import load_examples

PROMPT_VERSION = "a04-v9"
SYSTEM_PROMPT = """\
너는 데이터 모델 관계 설계자다. 주어진 엔티티 사이의 관계를 요구사항에 근거해 판단한다.
- parent_name·child_name에는 입력 엔티티의 name을 그대로 쓴다.
- cardinality: 부모 1건에 자식이 최대 1건이면 1:1, 여러 건이면 1:N, 양쪽 모두 여러 건이면 N:M.
- N:M은 연결 엔티티를 만들지 않고 N:M 관계 하나로 적는다.
- 같은 엔티티끼리의 관계(자기참조, 예: 상위 부서)는 parent_name과 child_name에 같은 이름을 쓴다.
- optional: 자식이 부모 없이 존재할 수 있으면 true.
- identifying: 자식이 부모 없이는 식별되지 않으면 true. 자기참조와 N:M에는 쓰지 않는다.
- FK 속성이나 키 컬럼을 만들지 않는다.
- 거래가 갱신할 잔액·재고가 복합 키로 식별되면 전체 키를 따라 변경 대상을 식별할 수 있는지 본다.
  상위 품목·로트만 가리키는 것으로 하위 위치별 잔액까지 식별됐다고 가정하지 않는다.
  다른 관계 경로로 전체 대상을 식별할 수 있으면 중복 관계를 강요하지 않는다.
  입력 속성이 부족하면 rationale에 한계를 밝히고 존재하지 않는 속성·배정 정책을 지어내지 않는다.
- fk_bindings는 부모의 키 속성과 같은 사실을 표현하는 자식의 기존 업무 속성에만 쓴다.
  parent_attribute_name·child_attribute_name에 각각 입력 속성 name을 적는다. 이름·타입이
  같다는 이유만으로 선언하지 않는다. 선언하지 않은 FK 칸은 정리 코드가 새로 만든다.
  상속된 키나 다른 관계에서 만든 칸을 이름으로 추측해 바인딩하지 않는다.
  필수·식별 FK의 자식 칸은 모두 nullable=false다. 선택 단일 FK는 nullable=true여야 한다.
  선택 복합 FK는 한 칸 이상 NULL을 허용해야 한다. 다른 필수 FK와 공유하는 칸은 NOT NULL을
  유지할 수 있고, 나머지 칸의 NULL로 선택 참조의 부재를 표현한다 (MATCH SIMPLE).
  충돌을 숨기려고 재사용 선언을 빼지 않는다. 재사용하려고 요구사항의 선택·식별 의미를 바꾸거나
  존재하는 업무 속성을 바꾸지 않는다. 타입·NULL·키의 최종 검사는 정리 코드도 수행한다.
- 현재 FK는 즉시 검사하므로 필수 관계가 순환하면 최초 데이터를 넣을 수 없다. 기본값·대표값 선택을
  소속 관계와 반대 방향의 필수 FK로 무조건 만들지 않는다. 원문 의미에 맞는 선택 상태나
  자식의 기본 여부 등 순환 없는 표현을 검토하고, 선택성 변경으로 제약을 몰래 완화하지 않는다.
- req_ids에는 근거 요구사항 ID를 적는다.
- rationale은 req_ids 요구사항 문장에서 근거 부분을 큰따옴표로 그대로 인용하고,
  판단 설명을 한 문장 덧붙인다.
  예: "하나의 재고거래 문서에는 하나 이상의 품목 내역을 등록한다." 내역은 문서에 속한다.
- 같은 두 엔티티 사이에도 의미가 다르면 관계를 따로 적는다.
- 요구사항에 근거가 없는 관계는 만들지 않는다.
- rework_context가 있으면 직전 관계·지적을 현재 엔티티·요구사항과 대조해 수정한다.
  A03이 엔티티·키를 바꿨을 수 있으므로 옛 ID·관계를 그대로 복사하지 않는다.
  충돌을 숨기려고 업무상 필요한 관계를 삭제하거나 의미·방향을 임의로 바꾸지 않는다.
  사전·명명 지원 부족은 관계 의미를 바꿔 해결하지 않는다. 출력 형식은 최초 설계와 같다."""
SYSTEM_PROMPT += "\n\n" + USER_REQUEST_RULE

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
    feedback: str | None = None,
    defer_binding_conflicts: bool = False,
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
        data=with_user_request(with_design_rework(input_data(state), state), feedback),
        examples=load_examples(pack, "A04", A04Output, root=settings.pack_root),
    )
    entity_ids = {e.name: e.id for e in state.entities}
    attributes = {e.name: {a.name: a.id for a in e.attributes} for e in state.entities}
    output_model = _checked_against(
        entity_ids.keys(),
        {r.id: r.text for r in state.requirements},
        attributes=attributes,
        # 그래프는 A03에서 만든 기존 속성의 NULL 충돌을 정리 규칙 지적으로 돌려보낸다.
        # 이름·참조·인용 검사는 그대로 적용하며 속성/관계 의미는 바꾸지 않는다.
        nullability=None
        if defer_binding_conflicts
        else {e.name: {a.name: a.nullable for a in e.attributes} for e in state.entities},
        primary_keys={
            e.name: frozenset(a.name for a in e.attributes if a.is_key) for e in state.entities
        },
    )
    result = client.complete(request, output_model, token_budget=token_budget)
    drafts = result.output.relationships
    ids = assign_ids("REL", len(drafts))
    relationships = tuple(
        Relationship.model_validate(
            {
                **d.model_dump(exclude={"parent_name", "child_name", "fk_bindings"}),
                "fk_bindings": tuple(
                    {
                        "parent_attribute_id": attributes[d.parent_name][b.parent_attribute_name],
                        "child_attribute_id": attributes[d.child_name][b.child_attribute_name],
                    }
                    for b in d.fk_bindings
                )
                if d.fk_bindings
                else None,
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
            {
                **e.model_dump(
                    mode="json",
                    include={
                        "name": True,
                        "description": True,
                        "attributes": {"__all__": {"name", "data_type", "is_key", "nullable"}},
                    },
                ),
                **(
                    {
                        "unique_keys": [
                            [next(a.name for a in e.attributes if a.id == attr) for attr in group]
                            for group in e.unique_keys
                        ]
                    }
                    if e.unique_keys
                    else {}
                ),
            }
            for e in state.entities
        ],
        "requirements": [
            r.model_dump(mode="json", include={"id", "text", "type"}) for r in state.requirements
        ],
    }


def _checked_against(
    entity_names: Collection[str],
    texts: Mapping[str, str],
    *,
    attributes: Mapping[str, Mapping[str, str]] | None = None,
    nullability: Mapping[str, Mapping[str, bool]] | None = None,
    primary_keys: Mapping[str, frozenset[str]] | None = None,
) -> type[A04Output]:
    """이번 입력으로 검사하는 출력 모델. 어기면 형식 오류처럼 재요청 대상이 된다.

    - parent_name·child_name은 입력에 있는 엔티티 이름만 허용한다.
    - 명시적 FK 재사용은 기존 속성을 참조하며 자식 속성의 NULL 조건이 관계와 맞아야 한다.
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
            _check_binding_inputs(self.relationships, attributes, nullability, primary_keys)
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


def _check_binding_inputs(
    relationships: tuple[RelationshipDraft, ...],
    attributes: Mapping[str, Mapping[str, str]] | None,
    nullability: Mapping[str, Mapping[str, bool]] | None,
    primary_keys: Mapping[str, frozenset[str]] | None,
) -> None:
    """기존 속성 참조와 입력에서 알 수 있는 NULL 호환성을 재요청 전에 검사한다."""
    for relation in relationships:
        for binding in relation.fk_bindings or ():
            if attributes is None or (
                binding.parent_attribute_name not in attributes[relation.parent_name]
                or binding.child_attribute_name not in attributes[relation.child_name]
            ):
                raise ValueError(f"FK 재사용은 부모·자식의 기존 속성만 참조합니다: {binding}")
        if nullability is not None and relation.fk_bindings:
            _check_binding_nullability(relation, relationships, nullability, primary_keys)


def _check_binding_nullability(
    relation: RelationshipDraft,
    relationships: tuple[RelationshipDraft, ...],
    nullability: Mapping[str, Mapping[str, bool]],
    primary_keys: Mapping[str, frozenset[str]] | None,
) -> None:
    values = [
        nullability[relation.child_name][b.child_attribute_name] for b in relation.fk_bindings or ()
    ]
    if relation.optional and not relation.identifying:
        # 상속 PK의 실제 구성은 정리 단계에서 확정한다. 추측해 정상 응답을 거절하지 않는다.
        keys = primary_keys.get(relation.parent_name) if primary_keys is not None else None
        if not keys or any(
            r.identifying and r.child_name == relation.parent_name for r in relationships
        ):
            return
        bound = {b.parent_attribute_name for b in relation.fk_bindings or ()}
        values.extend(True for _ in keys - bound)  # 미선언 키는 정리에서 NULL 허용 칸으로 파생
    if not fk_nullability_matches(
        values, optional=relation.optional, identifying=relation.identifying
    ):
        raise ValueError(
            f"FK 재사용 NULL 조건 불일치: {relation.parent_name}→{relation.child_name}. "
            "필수 FK는 모두 NOT NULL, 선택 FK는 NULL 가능 칸이 필요합니다. "
            "업무 의미와 명시적 바인딩을 함께 유지하세요"
        )


def _quotes_requirements(rel: RelationshipDraft, texts: Mapping[str, str]) -> bool:
    """인용이 하나 이상 있고, 모든 인용이 그 관계의 req_ids 문장 중 하나에 들어 있는지."""
    quotes = [_normalize(q) for q in _QUOTE.findall(rel.rationale)]
    pool = [texts[req_id] for req_id in rel.req_ids]
    return bool(quotes) and all(any(q in text for text in pool) for q in quotes)


def _normalize(text: str) -> str:
    """줄바꿈·연속 공백 차이만 무시한다 (review/merge.py의 `_normalize`와 같은 기준)."""
    return " ".join(text.split())
