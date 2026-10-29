"""TC-A04: A04 관계 설계 노드.

A03 결과가 아직 없으므로 재고 관리 엔티티를 직접 만들어 쓴다 (고정 응답, 08 문서).

A03이 완성된 뒤에도 고정 엔티티를 쓴다. 실제 A03 결과로 테스트하면 A03이 바뀔 때마다
이 테스트가 같이 깨지고, 실제 LLM을 불러 결과가 매번 다르며 비용도 든다. 깨졌을 때
A03 문제인지 A04 문제인지 구분하기도 어렵다. 고정 엔티티로 A04만 따로 검사한다.
"""

import json
import re

import pytest

from specton.config import Settings
from specton.contracts import DesignState, Entity, Relationship, RelationshipDraft, Requirement
from specton.llm.client import LLMClient
from specton.llm.errors import LLMContractError, LLMRefusalError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.a04_relationships import A04Output, input_data, run
from specton.nodes.common import NodeRun, unwrap_data
from specton.packs.examples import load_examples


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
                "id": f"{entity_id}-A1",
                "name": f"{name}코드",
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
    entities=[
        _entity("ENT-01", "창고", "REQ-01"),
        _entity("ENT-02", "품목", "REQ-02"),
        _entity("ENT-03", "입고", "REQ-01"),
        _entity("ENT-04", "거래처", "REQ-02"),
        _entity("ENT-05", "품목분류", "REQ-03"),
    ],
)


TEXTS = {r.id: r.text for r in STATE.requirements}


def _rel(
    parent: str,
    child: str,
    cardinality: str,
    req_id: str,
    *,
    optional: bool = False,
    identifying: bool = False,
    rationale: str | None = None,
) -> RelationshipDraft:
    """LLM이 답할 관계 하나. 엔티티는 이름으로, 근거는 요구사항 문장 인용으로 쓴다."""
    return RelationshipDraft(
        parent_name=parent,
        child_name=child,
        cardinality=cardinality,
        optional=optional,
        identifying=identifying,
        rationale=rationale if rationale is not None else f'"{TEXTS[req_id]}" 관계 판단 근거다.',
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
    assert (rel.parent, rel.child) == ("ENT-01", "ENT-03")
    assert (rel.cardinality, rel.optional, rel.req_ids) == ("1:N", False, ("REQ-01",))
    request = transport.sent[0]
    assert (request.stage, request.model) == ("A04", _settings().design_model)


def test_many_to_many_stays_one_relationship() -> None:
    client, _ = stub_client(
        reply(A04Output(relationships=(_rel("품목", "거래처", "N:M", "REQ-02"),)))
    )

    [rel] = _run(client).output

    assert (rel.parent, rel.child, rel.cardinality) == ("ENT-02", "ENT-04", "N:M")


def test_self_reference_points_to_the_same_entity() -> None:
    client, _ = stub_client(
        reply(
            A04Output(relationships=(_rel("품목분류", "품목분류", "1:N", "REQ-03", optional=True),))
        )
    )

    [rel] = _run(client).output

    assert rel.parent == rel.child == "ENT-05"
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
    assert "ENT-" not in sent


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


def test_fk_field_in_output_is_retried() -> None:
    """TC-F08: LLM이 FK 컬럼을 넣으면 출력 계약 위반으로 다시 요청한다."""
    draft = _rel("창고", "입고", "1:N", "REQ-01")
    with_fk = {**draft.model_dump(mode="json"), "fk_column": "창고코드"}
    client, transport = stub_client(
        reply(json.dumps({"relationships": [with_fk]}, ensure_ascii=False)),
        reply(A04Output(relationships=(draft,))),
    )

    [result] = _run(client).output

    assert result.id == "REL-01"
    assert len(transport.sent) == 2


# 없는 참조 (근거 부족)


def test_unknown_entity_name_is_sent_back_for_retry() -> None:
    client, transport = stub_client(
        reply(A04Output(relationships=(_rel("창고", "출고", "1:N", "REQ-01"),))),
        reply(A04Output(relationships=(_rel("창고", "입고", "1:N", "REQ-01"),))),
    )

    [rel] = _run(client).output

    assert rel.child == "ENT-03"
    assert len(transport.sent) == 2
    assert "입력에 없는 엔티티를 참조했습니다: 출고" in transport.sent[1].messages[-1].content


def test_unknown_entity_name_that_persists_fails_the_node() -> None:
    wrong = reply(A04Output(relationships=(_rel("창고", "출고", "1:N", "REQ-01"),)))
    client, transport = stub_client(wrong, wrong, wrong)

    with pytest.raises(LLMContractError, match="출고") as caught:
        _run(client)

    assert len(transport.sent) == 3
    assert len(caught.value.calls) == 3


def test_unknown_req_id_that_persists_fails_the_node() -> None:
    unknown = _rel("창고", "입고", "1:N", "REQ-99", rationale='"없는 요구사항" 판단.')
    wrong = reply(A04Output(relationships=(unknown,)))
    client, _ = stub_client(wrong, wrong, wrong)

    with pytest.raises(LLMContractError, match="REQ-99"):
        _run(client)


# 근거 인용


def test_quote_may_differ_only_in_whitespace() -> None:
    rationale = '"품목 분류는  상위 분류를\n가질 수 있다" 상위 분류가 없는 분류도 있다.'
    client, transport = stub_client(
        reply(
            A04Output(
                relationships=(
                    _rel(
                        "품목분류", "품목분류", "1:N", "REQ-03", optional=True, rationale=rationale
                    ),
                )
            )
        )
    )

    [rel] = _run(client).output

    assert rel.rationale == rationale
    assert len(transport.sent) == 1


def test_rationale_without_quote_is_sent_back_for_retry() -> None:
    no_quote = _rel("창고", "입고", "1:N", "REQ-01", rationale="입고는 창고에 속한다.")
    client, transport = stub_client(
        reply(A04Output(relationships=(no_quote,))),
        reply(A04Output(relationships=(_rel("창고", "입고", "1:N", "REQ-01"),))),
    )

    [rel] = _run(client).output

    assert rel.id == "REL-01"
    assert len(transport.sent) == 2
    assert "큰따옴표로 인용하지 않았습니다: 창고→입고" in transport.sent[1].messages[-1].content


def test_quote_from_another_requirement_is_sent_back_for_retry() -> None:
    other = _rel("창고", "입고", "1:N", "REQ-01", rationale=f'"{TEXTS["REQ-02"]}" 다른 문장이다.')
    client, transport = stub_client(
        reply(A04Output(relationships=(other,))),
        reply(A04Output(relationships=(_rel("창고", "입고", "1:N", "REQ-01"),))),
    )

    _run(client)

    assert len(transport.sent) == 2


def test_quote_that_stays_wrong_fails_the_node() -> None:
    made_up = _rel("창고", "입고", "1:N", "REQ-01", rationale='"입고는 창고에 속한다" 판단.')
    wrong = reply(A04Output(relationships=(made_up,)))
    client, transport = stub_client(wrong, wrong, wrong)

    with pytest.raises(LLMContractError, match="창고→입고"):
        _run(client)

    assert len(transport.sent) == 3


# identifying·중복 쌍


@pytest.mark.parametrize(
    ("parent", "child", "cardinality", "req_id"),
    [("품목분류", "품목분류", "1:N", "REQ-03"), ("품목", "거래처", "N:M", "REQ-02")],
)
def test_identifying_self_reference_or_many_to_many_is_retried(
    parent: str, child: str, cardinality: str, req_id: str
) -> None:
    client, transport = stub_client(
        reply(
            A04Output.model_construct(
                relationships=(_rel(parent, child, cardinality, req_id, identifying=True),)
            )
        ),
        reply(A04Output(relationships=(_rel(parent, child, cardinality, req_id),))),
    )

    [rel] = _run(client).output

    assert rel.identifying is False
    assert len(transport.sent) == 2
    assert "identifying일 수 없습니다" in transport.sent[1].messages[-1].content


def test_two_relationships_between_the_same_pair_are_both_kept() -> None:
    """같은 두 엔티티 사이에도 의미가 다른 관계가 있을 수 있어 막지 않는다."""
    client, _ = stub_client(
        reply(
            A04Output(
                relationships=(
                    _rel("거래처", "입고", "1:N", "REQ-04", optional=True),
                    _rel("거래처", "입고", "1:N", "REQ-02"),
                )
            )
        )
    )

    rels = _run(client).output

    assert [(r.id, r.parent, r.child) for r in rels] == [
        ("REL-01", "ENT-04", "ENT-03"),
        ("REL-02", "ENT-04", "ENT-03"),
    ]


# 입력 상태 문제 (LLM 호출 전)


def test_no_entities_stops_before_calling_the_llm() -> None:
    client, transport = stub_client()
    state = STATE.model_copy(update={"entities": ()})

    with pytest.raises(ValueError, match="엔티티가 없습니다"):
        run(client, state, _settings(), pack="inventory")

    assert not transport.sent


def test_duplicate_entity_names_stop_before_calling_the_llm() -> None:
    client, transport = stub_client()
    entities = (*STATE.entities, _entity("ENT-06", "창고", "REQ-01"))
    state = STATE.model_copy(update={"entities": entities})

    with pytest.raises(ValueError, match="엔티티 이름이 중복됩니다: 창고"):
        run(client, state, _settings(), pack="inventory")

    assert not transport.sent


# few-shot 예시


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_pack_examples_match_the_output_model_and_input_shape(pack: str) -> None:
    examples = load_examples(pack, "A04", A04Output)
    expected = input_data(STATE)
    entity_keys = set(expected["entities"][0])
    attribute_keys = set(expected["entities"][0]["attributes"][0])
    requirement_keys = set(expected["requirements"][0])

    assert examples
    for example in examples:
        assert isinstance(example.input, dict)
        assert set(example.input) == set(expected)
        assert all(set(e) == entity_keys for e in example.input["entities"])
        assert all(
            set(a) == attribute_keys for e in example.input["entities"] for a in e["attributes"]
        )
        assert all(set(r) == requirement_keys for r in example.input["requirements"])
        names = {e["name"] for e in example.input["entities"]}
        req_ids = {r["id"] for r in example.input["requirements"]}
        for rel in example.output.relationships:
            assert {rel.parent_name, rel.child_name} <= names
            assert set(rel.req_ids) <= req_ids


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_pack_examples_quote_their_requirements(pack: str) -> None:
    """few-shot은 본보기다. 예시가 인용 규칙을 어기면 모델도 그대로 따라 한다."""
    for example in load_examples(pack, "A04", A04Output):
        assert isinstance(example.input, dict)
        texts = {r["id"]: r["text"] for r in example.input["requirements"]}
        for rel in example.output.relationships:
            quotes = re.findall(r'"([^"]+)"', rel.rationale)
            assert quotes, rel.rationale
            assert all(any(q in texts[i] for i in rel.req_ids) for q in quotes), rel.rationale
