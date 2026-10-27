"""A04 관계 설계 (04 문서, REQ-08).

A03 엔티티 사이의 관계(방향·카디널리티·선택 여부·식별 여부)를 LLM이 판단한다.
LLM은 엔티티를 이름으로 가리키고, 코드가 이름을 엔티티 ID로 바꾸고 관계 ID를 붙인다.
FK·연결 테이블은 모델 정리(#12)가 관계에서 파생하므로 여기서 만들지 않는다.
"""

from typing import Any

from specton.config import Settings
from specton.contracts import DesignState, Relationship, RelationshipDraft
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
- identifying: 자식이 부모 없이는 식별되지 않으면 true.
- FK 속성이나 키 컬럼을 만들지 않는다.
- req_ids에는 근거 요구사항 ID를, rationale에는 판단 근거를 한두 문장으로 적는다.
- 요구사항에 근거가 없는 관계는 만들지 않는다."""


class A04Output(Contract):
    relationships: tuple[RelationshipDraft, ...]


def run(
    client: LLMClient,
    state: DesignState,
    settings: Settings,
    *,
    pack: str,
    token_budget: int | None = None,
) -> NodeRun[tuple[Relationship, ...]]:
    """현재 엔티티·요구사항으로 관계를 설계하고 코드가 ID를 붙인다."""
    request = build_request(
        settings,
        role="design",
        stage="A04",
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        data=_relationship_data(state),
        examples=load_examples(pack, "A04", A04Output),
    )
    result = client.complete(request, A04Output, token_budget=token_budget)
    drafts = result.output.relationships
    entity_ids = {e.name: e.id for e in state.entities}
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


def _relationship_data(state: DesignState) -> dict[str, Any]:
    """엔티티는 이름·설명·속성만 넘긴다. ID는 LLM이 쓰지 않으므로 빼고, 이름으로 가리키게 한다."""
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
