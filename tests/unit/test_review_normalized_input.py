"""리뷰어 입력의 정리 결과 요약(`normalized`) (#12, A08 재확인). 공통 변경 확인 전 초안.

전달만 확인한다. 고정 응답(stub)이라 실제 LLM이 부분 종속을 찾거나 스냅샷을 오탐하지 않는지는
검증하지 않는다.
"""

import json
from typing import Any, ClassVar

import pytest

from specton.codegen.model import Normalized, NormalizedModel
from specton.codegen.naming import NamingRules, TermInfo
from specton.codegen.normalize import PackRef, normalize
from specton.config import Settings
from specton.contracts import DesignState, Entity, Relationship, Requirement
from specton.llm.stub import reply, stub_client
from specton.review.normalized_view import normalized_view
from specton.review.perspective import Perspective
from specton.review.reviewer import (
    CombinedReviewOutput,
    MissingReviewInput,
    ReviewOutput,
    review_combined,
    review_perspective,
)


class _Words:
    """테스트용 사전. 실제 팩에는 이 단어들이 아직 없다(#12 계획 3-3)."""

    digest = "test"
    words: ClassVar[dict[str, str]] = {
        "수불문서": "SUBUL_DOC",
        "문서번호": "DOC_NO",
        "품목": "ITEM",
        "품목코드": "ITEM_CD",
        "수불내역": "SUBUL_DSCTN",
        "내역순번": "DSCTN_SN",
        "수량": "QTY",
    }

    def term(self, logical_name: str) -> TermInfo | None:
        return None

    def compose(self, logical_name: str) -> str | None:
        return self.words.get(logical_name)


RULES = NamingRules(max_bytes=63, reserved_words=frozenset())
TEXT = "하나의 수불 문서에는 하나 이상의 품목 내역을 등록한다."


def _attr(attr_id: str, name: str, data_type: str = "varchar", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": attr_id, "name": name, "data_type": data_type}
    if data_type == "varchar":
        base["length"] = 20
    if kw.get("is_key"):
        base["nullable"] = False
    return {**base, "req_ids": ["REQ-01"], **kw}


def _entity(entity_id: str, name: str, *attrs: dict[str, Any]) -> Entity:
    return Entity(
        id=entity_id,
        pack="inventory",
        name=name,
        description=f"{name} 정보",
        attributes=list(attrs),
        req_ids=["REQ-01"],
    )


def _rel(rel_id: str, parent: str, child: str, **kw: Any) -> Relationship:
    base: dict[str, Any] = {
        "id": rel_id,
        "parent": parent,
        "child": child,
        "cardinality": "1:N",
        "optional": False,
        "rationale": f'"{TEXT}"',
        "req_ids": ["REQ-01"],
    }
    return Relationship.model_validate({**base, **kw})


def _design() -> DesignState:
    """수불문서 → 수불내역(식별), 품목 → 수불내역(비식별). 부모 키는 A03 속성에 넣지 않는다."""
    return DesignState(
        run_id="run-1",
        requirements=[
            Requirement(
                id="REQ-01",
                source_ref={"file_format": "csv", "row": 2},
                text=TEXT,
                draft_text=TEXT,
                type="FR",
                analysis_version=1,
            )
        ],
        entities=[
            _entity("ENT-doc", "수불문서", _attr("ATTR-doc-no", "문서번호", is_key=True)),
            _entity("ENT-item", "품목", _attr("ATTR-item-cd", "품목코드", is_key=True)),
            _entity(
                "ENT-line",
                "수불내역",
                _attr("ATTR-line-sn", "내역순번", "integer", is_key=True),
                _attr("ATTR-line-qty", "수량", "numeric", precision=10, scale=3),
            ),
        ],
        relationships=[
            _rel("REL-01", "ENT-doc", "ENT-line", identifying=True),
            _rel("REL-02", "ENT-item", "ENT-line"),
        ],
    )


def _model(design: DesignState) -> NormalizedModel:
    result = normalize(design, pack=PackRef("inventory", "test"), lexicon=_Words(), rules=RULES)
    assert isinstance(result, Normalized), result
    return result.model


def _normalized_state() -> DesignState:
    design = _design()
    return design.evolve(normalized=_model(design))


def _perspective(*inputs: str, reviewer_id: str = "A08") -> Perspective:
    return Perspective.model_validate(
        {
            "reviewer_id": reviewer_id,
            "name": "시험 관점",
            "prompt_version": "test-v1",
            "instructions": "정규화를 본다",
            "checklist": ["복합키 일부에만 달린 속성"],
            "inputs": list(inputs),
            "false_positive_guards": ["근거 없으면 지적하지 않는다"],
        }
    )


def _sent_data(transport: Any) -> dict[str, Any]:
    """요청의 마지막 메시지에 담긴 입력 데이터(JSON)."""
    content = transport.sent[0].messages[-1].content
    start = content.index("{")
    parsed: dict[str, Any] = json.JSONDecoder().raw_decode(content[start:])[0]
    return parsed


# ── 요약 보기 ─────────────────────────────────────────────────────────


def test_view_keeps_ids_sources_and_keys_but_not_physical_names_or_types() -> None:
    model = _model(_design())
    view = normalized_view(model)
    line = next(t for t in view["tables"] if t["entity_id"] == "ENT-line")
    assert set(line) == {"id", "name", "entity_id", "columns", "primary_key", "unique_keys"}
    for column in line["columns"]:
        assert set(column) in ({"id", "name", "attribute_id"}, {"id", "name", "relationship_id"})
    sources = {
        c["name"]: c.get("attribute_id") or c.get("relationship_id") for c in line["columns"]
    }
    assert sources == {
        "내역순번": "ATTR-line-sn",
        "수량": "ATTR-line-qty",
        "문서번호": "REL-01",  # 식별 관계로 물려받은 키
        "품목코드": "REL-02",  # 비식별 FK
    }
    names = {c["id"]: c["name"] for c in line["columns"]}
    assert [names[c] for c in line["primary_key"]] == ["문서번호", "내역순번"]
    text = json.dumps(view, ensure_ascii=False)
    assert "doc_no" not in text and "varchar" not in text  # 물리명·타입은 빼고 보낸다


def test_view_keeps_fk_column_pairs_in_model_order() -> None:
    model = _model(_design())
    view = normalized_view(model)
    assert [
        (
            f["relationship_id"],
            f["table_id"],
            f["columns"],
            f["parent_table_id"],
            f["parent_columns"],
        )
        for f in view["foreign_keys"]
    ] == [
        (
            fk.relationship_id,
            fk.table_id,
            list(fk.columns),
            fk.parent_table_id,
            list(fk.parent_columns),
        )
        for fk in model.foreign_keys
    ]


def test_view_is_deterministic() -> None:
    assert normalized_view(_model(_design())) == normalized_view(_model(_design()))


# ── 전달 ─────────────────────────────────────────────────────────────


def test_perspective_that_selects_normalized_receives_the_view() -> None:
    state = _normalized_state()
    assert state.normalized is not None
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(
        client,
        _perspective("requirements", "entities", "relationships", "normalized"),
        state,
        Settings(_env_file=None),
    )

    data = _sent_data(transport)
    assert list(data) == ["requirements", "entities", "relationships", "normalized"]
    assert data["normalized"] == normalized_view(state.normalized)
    assert [r["id"] for r in data["relationships"]] == ["REL-01", "REL-02"]


@pytest.mark.parametrize("mode", ["parallel", "combined"])
def test_missing_normalized_stops_before_calling_the_llm(mode: str) -> None:
    client, transport = stub_client(reply(ReviewOutput(findings=())))
    needs = _perspective("requirements", "normalized")
    with pytest.raises(MissingReviewInput, match="normalized"):
        if mode == "parallel":
            review_perspective(client, needs, _design(), Settings(_env_file=None))
        else:
            others = _perspective("requirements", reviewer_id="A05")
            review_combined(client, [others, needs], _design(), Settings(_env_file=None))
    assert not transport.sent  # LLM을 부르지 않았다


@pytest.mark.parametrize("with_normalized", [False, True])
def test_perspective_without_normalized_keeps_the_same_input(with_normalized: bool) -> None:
    """정리 결과를 고르지 않은 관점은 정리 결과가 있든 없든 입력이 같다."""
    state = _normalized_state() if with_normalized else _design()
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(
        client, _perspective("requirements", "entities"), state, Settings(_env_file=None)
    )

    assert list(_sent_data(transport)) == ["requirements", "entities"]


def test_combined_mode_sends_normalized_once_for_all_perspectives() -> None:
    """combined는 관점들의 섹션을 합쳐 한 번 보낸다. 한 관점이 고르면 모두 같은 요청에서 본다.

    공통 변경 확인 항목(계획 2-2)이라 지금 동작을 고정해 둔다.
    """
    state = _normalized_state()
    output = CombinedReviewOutput.model_validate(
        {
            "perspectives": [
                {"reviewer_id": "A05", "findings": []},
                {"reviewer_id": "A08", "findings": []},
            ]
        }
    )
    client, transport = stub_client(reply(output))

    review_combined(
        client,
        [_perspective("requirements", reviewer_id="A05"), _perspective("entities", "normalized")],
        state,
        Settings(_env_file=None),
    )

    assert list(_sent_data(transport)) == ["requirements", "entities", "normalized"]


@pytest.mark.parametrize("reviewer", ["A05", "A06"])
def test_relationship_review_receives_actual_derived_fk_pairs(reviewer):
    from specton.review.perspective import PERSPECTIVES_DIR, load_perspective

    state = _normalized_state()
    client, transport = stub_client(reply(ReviewOutput(findings=())))
    review_perspective(
        client,
        load_perspective(PERSPECTIVES_DIR / f"{reviewer}.yaml"),
        state,
        Settings(_env_file=None),
    )
    data = _sent_data(transport)
    assert state.normalized is not None
    assert data["normalized"] == normalized_view(
        state.normalized, include_fk_names=reviewer == "A06"
    )
    # 모델에서 파생한 FK 컬럼도 빠짐없이 전달한다. A03 속성 목록에 없어도 추적 가능하다.
    for fk in state.normalized.foreign_keys:
        sent = next(f for f in data["normalized"]["foreign_keys"] if f["id"] == fk.id)
        assert sent["columns"] == list(fk.columns)
        assert sent["parent_columns"] == list(fk.parent_columns)


def test_relation_only_review_before_normalization_does_not_claim_normalized_input():
    client, transport = stub_client(reply(ReviewOutput(findings=())))
    review_perspective(
        client, _perspective("requirements", "relationships"), _design(), Settings(_env_file=None)
    )
    assert "normalized" not in _sent_data(transport)


def test_named_fk_endpoints_show_two_direct_references_without_inventing_a_join() -> None:
    view = normalized_view(_model(_design()), include_fk_names=True)
    edges = {fk["relationship_id"]: fk for fk in view["foreign_keys"]}
    assert len(edges) == 2
    assert edges["REL-01"]["child"]["name"] == "수불내역"
    assert edges["REL-01"]["parent"]["name"] == "수불문서"
    assert edges["REL-02"]["child"]["entity_id"] == "ENT-line"
    assert edges["REL-02"]["parent"]["entity_id"] == "ENT-item"
    # FK 증거는 키뿐이다. 내역에 있는 수량을 부모에서 제공한다고 만들어내지 않는다.
    assert [c["name"] for c in edges["REL-02"]["child"]["columns"]] == ["품목코드"]
    assert edges["REL-02"]["child"]["columns"][0]["relationship_id"] == "REL-02"
    assert edges["REL-02"]["parent"]["columns"][0]["attribute_id"] == "ATTR-item-cd"


def test_missing_reference_is_not_inferred_from_entity_names() -> None:
    state = _design().evolve(relationships=[_design().relationships[0]])
    view = normalized_view(_model(state), include_fk_names=True)
    assert any(t.get("entity_id") == "ENT-item" for t in view["tables"])
    assert not any(f["parent"].get("entity_id") == "ENT-item" for f in view["foreign_keys"])


def test_named_composite_fk_preserves_all_column_pairs_in_order() -> None:
    state = _design()
    doc = state.entities[0].model_copy(
        update={
            "attributes": [
                *state.entities[0].attributes,
                _entity(
                    "unused", "품목", _attr("ATTR-doc-item", "품목코드", is_key=True)
                ).attributes[0],
            ],
        }
    )
    state = state.evolve(
        entities=[doc, *state.entities[1:]], relationships=[state.relationships[0]]
    )
    model = _model(state)
    fk = normalized_view(model, include_fk_names=True)["foreign_keys"][0]
    assert len(fk["columns"]) == 2
    assert [c["id"] for c in fk["child"]["columns"]] == fk["columns"]
    assert [c["id"] for c in fk["parent"]["columns"]] == fk["parent_columns"]
    assert [c["name"] for c in fk["child"]["columns"]] == [
        c["name"] for c in fk["parent"]["columns"]
    ]


def test_combined_a06_receives_named_endpoints_without_changing_stored_model() -> None:
    from specton.review.perspective import PERSPECTIVES_DIR, load_perspective

    state = _normalized_state()
    before = state.model_dump(mode="json")
    output = CombinedReviewOutput.model_validate(
        {"perspectives": [{"reviewer_id": "A06", "findings": []}]}
    )
    client, transport = stub_client(reply(output))
    review_combined(
        client,
        [load_perspective(PERSPECTIVES_DIR / "A06.yaml")],
        state,
        Settings(_env_file=None),
    )
    assert state.normalized is not None
    assert _sent_data(transport)["normalized"] == normalized_view(
        state.normalized, include_fk_names=True
    )
    assert state.model_dump(mode="json") == before
