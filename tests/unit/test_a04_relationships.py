"""TC-A04: A04 관계 설계 노드.

A03 결과가 아직 없으므로 재고 관리 엔티티를 직접 만들어 쓴다 (고정 응답, 08 문서).
"""

"""
테스트는 일부러 계속 고정된 가짜 데이터를 쓴다. 진짜 A03 결과로 테스트하면 이런 문제가 생긴다.

R4가 A03을 고칠 때마다 내 테스트가 같이 깨질 수 있다. A04에 문제가 없는 상황에도
A03은 진짜 LLM을 부르기 때문에 매번 결과가 다르고 돈도 든다.
테스트가 깨졌을 때 A03 문제인지 A04 문제인지 구분하기 어렵다.
가짜 데이터를 쓰면 "A04만" 따로 검사할 수 있다.
"""

import json

import pytest

from specton.config import Settings
from specton.contracts import DesignState, Entity, Relationship, RelationshipDraft, Requirement
from specton.llm.client import LLMClient
from specton.llm.errors import LLMContractError, LLMRefusalError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.a04_relationships import A04Output, run
from specton.nodes.common import NodeRun, unwrap_data


def _requirement(req_id: str, text: str) -> Requirement:
    return Requirement(
        id=req_id,
        source_ref={"kind": "csv", "row": 2},
        text=text,
        original_text=text,
        type="FR",
        analysis_version=1,
    )


def _entity(entity_id: str, name: str, req_id: str) -> Entity:
    return Entity(
        id=entity_id,
        pack="inventory",
        name=name,
        description=f"{name} 정보",
        attributes=[
            {
                "id": f"{entity_id}-A1",  # ← ENT-01-A1 같은 속성 ID 형식
                "name": f"{name}코드",    # ← "창고코드" 같은 속성 이름
                "data_type": "varchar",
                "length": 20,
                "is_key": True,
                "nullable": False,
                "req_ids": [req_id],
            }
        ],
        req_ids=[req_id],
    )


STATE = DesignState(
    run_id="run-1",
    requirements=[
        _requirement("REQ-01", "입고는 하나의 창고로 들어온다"),
        _requirement("REQ-02", "품목은 여러 거래처에서 공급받고, 거래처는 여러 품목을 공급한다"),
        _requirement("REQ-03", "품목 분류는 상위 분류를 가질 수 있다"),
        _requirement("REQ-04", "입고 시 거래처는 입력하지 않을 수 있다"),
    ],
    entities=[   # A03 작업이 끝나면 맞춰야 할 부분 ,엔티티와 id 부분
        _entity("ENT-01", "창고", "REQ-01"),
        _entity("ENT-02", "품목", "REQ-02"),
        _entity("ENT-03", "입고", "REQ-01"),
        _entity("ENT-04", "거래처", "REQ-02"),
        _entity("ENT-05", "품목분류", "REQ-03"),
    ],
)


def _rel(
    parent: str, child: str, cardinality: str, req_id: str, *, optional: bool = False
) -> RelationshipDraft:
    """LLM이 답할 관계 하나. 엔티티는 이름으로 가리킨다."""
    return RelationshipDraft(
        parent_name=parent,
        child_name=child,
        cardinality=cardinality,
        optional=optional,
        rationale=f"{req_id} 요구사항에 근거한다",
        req_ids=[req_id],
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


def _run(client: LLMClient) -> NodeRun[tuple[Relationship, ...]]:
    return run(client, STATE, _settings(), pack="inventory")


# 정상 응답


def test_code_assigns_ids_and_turns_names_into_entity_ids() -> None:
    client, transport = stub_client(
        reply(A04Output(relationships=(_rel("창고", "입고", "1:N", "REQ-01"),)))
    )

    [rel] = _run(client).output

    assert rel.id == "REL-01"
    assert (rel.parent, rel.child) == ("ENT-01", "ENT-03")   # 엔티티와 id 부분
    assert (rel.cardinality, rel.optional, rel.req_ids) == ("1:N", False, ("REQ-01",))
    request = transport.sent[0]
    assert (request.stage, request.model) == ("A04", _settings().design_model)


def test_many_to_many_stays_one_relationship() -> None:
    client, _ = stub_client(
        reply(A04Output(relationships=(_rel("품목", "거래처", "N:M", "REQ-02"),)))
    )

    [rel] = _run(client).output

    assert (rel.parent, rel.child, rel.cardinality) == ("ENT-02", "ENT-04", "N:M")  # 엔티티와 id 부분


def test_self_reference_points_to_the_same_entity() -> None:
    client, _ = stub_client(
        reply(
            A04Output(relationships=(_rel("품목분류", "품목분류", "1:N", "REQ-03", optional=True),))
        )
    )

    [rel] = _run(client).output

    assert rel.parent == rel.child == "ENT-05"  # 엔티티와 id 부분
    assert rel.optional is True


def test_several_relationships_get_ids_in_order() -> None:
    client, _ = stub_client(
        reply(
            A04Output(
                relationships=(
                    _rel("창고", "입고", "1:N", "REQ-01"),
                    _rel("거래처", "입고", "1:N", "REQ-04", optional=True),
                )
            )
        )
    )

    rels = _run(client).output

    assert [r.id for r in rels] == ["REL-01", "REL-02"]
    assert [r.optional for r in rels] == [False, True]


def test_llm_sees_entity_names_but_not_entity_ids() -> None:
    client, transport = stub_client(reply(A04Output(relationships=())))

    _run(client)

    sent = unwrap_data(transport.sent[0].messages[-1].content)
    data = json.loads(sent)
    assert [e["name"] for e in data["entities"]] == ["창고", "품목", "입고", "거래처", "품목분류"]
    assert [r["id"] for r in data["requirements"]] == ["REQ-01", "REQ-02", "REQ-03", "REQ-04"]
    assert "ENT-" not in sent   # 엔티티와 id 부분


# 형식 오류·거절


def test_invalid_output_is_retried() -> None:
    client, transport = stub_client(
        reply("{}"), reply(A04Output(relationships=(_rel("창고", "입고", "1:N", "REQ-01"),)))
    )

    [rel] = _run(client).output

    assert rel.id == "REL-01"
    assert len(transport.sent) == 2


def test_invalid_output_three_times_raises_contract_error() -> None:
    client, transport = stub_client(reply("{}"), reply("{}"), reply("{}"))

    with pytest.raises(LLMContractError):
        _run(client)

    assert len(transport.sent) == 3


def test_refusal_is_raised_without_retry() -> None:
    client, transport = stub_client(refusal())

    with pytest.raises(LLMRefusalError):
        _run(client)

    assert len(transport.sent) == 1
