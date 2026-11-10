"""TC-F09·TC-N01: 모델 정리(#12) — 결과 모델, 관계 유형별 FK·연결 테이블, 출력 검사.

입력은 **테스트 안에서 만든 고정 엔티티·관계**다. 이름은 inventory 팩 용어(창고코드 등)를 참고했고,
사전 조회(`Lexicon`)는 이 파일의 임시 사전이다. 정리 규칙만 보려고 팩 파일과 떼어 놓았다.
실제 팩 사전 연결과 두 팩 실행은 `test_codegen_naming.py`에서 본다.

테스트 이름의 D 번호는 계획서 v4의 결정 번호다. 결정이 바뀌면 그 테스트를 고친다.
"""

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from specton.codegen.model import (
    Column,
    ForeignKey,
    Normalized,
    NormalizedModel,
    NormalizeFailed,
    ProblemCode,
    Table,
    problem,
)
from specton.codegen.naming import NamingRules, TermInfo
from specton.codegen.normalize import PackRef, check_output, normalize
from specton.contracts import DesignState, Entity, Relationship, Requirement
from specton.contracts.base import SqlType
from specton.packs.build import read_yaml

ROOT = Path(__file__).resolve().parents[2]
PACK = PackRef(name="inventory", version="test")
# 길이 한도는 팩에서 읽는다 (상수 하드코딩 금지).
# 예약어는 실제 목록 대신 테스트용 작은 목록이다 (실제 목록은 test_codegen_naming.py, D10).
RULES = NamingRules(
    max_bytes=read_yaml(ROOT / "domain_packs/common/naming.yaml")["physical_name"]["max_bytes"],
    reserved_words=frozenset({"end", "order", "user"}),
)
# 자기참조 접두어. 실제로는 naming.yaml column.self_reference_prefix에서 읽는다
# (파일에서 읽는 경로는 test_codegen_naming.py). 여기서는 사전 조회만 보려고 값을 직접 넣는다.
RULES_SELF = replace(RULES, self_reference_prefix="상위")


def _copy(obj: Any, **changes: Any) -> Any:
    """결과 모델(Pydantic)의 일부 값을 바꾼 사본. 검사를 일부러 어기는 모델을 만들 때 쓴다."""
    return obj.model_copy(update=changes)


class FixtureLexicon:
    """임시 사전. 용어는 팩 terms.yaml의 물리명을 옮겨 적었고, 엔티티 이름 조합은 테스트용이다."""

    digest = "fixture"

    def __init__(
        self, terms: dict[str, TermInfo] | None = None, words: dict[str, str] | None = None
    ) -> None:
        self.terms = {
            "창고코드": TermInfo("WRHUS_CD", "코드C10"),
            "창고명": TermInfo("WRHUS_NM", "명V200"),
            "거래일시": TermInfo("DLNG_DT", "연월일시분초D", time_precision=0),
            **(terms or {}),
        }
        self.words = {
            "창고": "WRHUS",
            "입고": "WRHSG",
            "입고번호": "WRHSG_NO",
            "입고수량": "WRHSG_QTY",
            "거래처": "BCNC",
            "사업자번호": "BZMN_NO",
            "지점순번": "BRNCH_SN",
            "상위": "UP",
            "출고": "DLVR",
            "출고번호": "DLVR_NO",
            "내역순번": "DSCTN_SN",
            "내역": "DSCTN",
            **(words or {}),
        }

    def term(self, logical_name: str) -> TermInfo | None:
        return self.terms.get(logical_name)

    def compose(self, logical_name: str) -> str | None:
        return self.words.get(logical_name)


LEXICON = FixtureLexicon()


def _req(req_id: str) -> Requirement:
    return Requirement(
        id=req_id,
        source_ref={"file_format": "csv", "row": 2},
        text=f"{req_id} 문장",
        draft_text=f"{req_id} 문장",
        type="FR",
        analysis_version=1,
    )


def _attr(attr_id: str, name: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": attr_id,
        "name": name,
        "data_type": "varchar",
        "length": 10,
        "req_ids": ["REQ-01"],
    }
    if kw.get("is_key"):
        base["nullable"] = False
    return {**base, **kw}


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
        "rationale": '"REQ-02 문장" 근거',
        "req_ids": ["REQ-02"],
    }
    return Relationship.model_validate({**base, **kw})


WAREHOUSE = _entity(
    "ENT-wh",
    "창고",
    _attr("ATTR-wh-cd", "창고코드", is_key=True),
    _attr("ATTR-wh-nm", "창고명", length=200),
)
RECEIPT = _entity(
    "ENT-rc",
    "입고",
    _attr("ATTR-rc-no", "입고번호", is_key=True),
    _attr("ATTR-rc-qty", "입고수량", data_type="numeric", length=None, precision=15, scale=3),
    _attr("ATTR-rc-dt", "거래일시", data_type="timestamp", length=None, nullable=False),
)
SUPPLIER = _entity(  # 복합 PK 부모 (D12)
    "ENT-sp",
    "거래처",
    _attr("ATTR-sp-bz", "사업자번호", is_key=True),
    _attr("ATTR-sp-br", "지점순번", data_type="integer", length=None, is_key=True),
)


def _design(entities: list[Entity], relationships: list[Relationship]) -> DesignState:
    return DesignState(
        run_id="run-1",
        requirements=[_req("REQ-01"), _req("REQ-02"), _req("REQ-03")],
        entities=entities,
        relationships=relationships,
    )


LINE = _entity(  # 식별 관계 연쇄의 손자 (inventory A04 INV-005 수불문서 → 수불내역 모양)
    "ENT-ln",
    "내역",
    _attr("ATTR-ln-sn", "내역순번", data_type="integer", length=None, is_key=True),
)

BASE = _design([WAREHOUSE, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-rc")])


def _ok(
    design: DesignState, lexicon: FixtureLexicon = LEXICON, rules: NamingRules = RULES
) -> NormalizedModel:
    result = normalize(design, pack=PACK, lexicon=lexicon, rules=rules)
    assert isinstance(result, Normalized), result
    return result.model


def _failed(
    design: DesignState, lexicon: FixtureLexicon = LEXICON, rules: NamingRules = RULES
) -> NormalizeFailed:
    result = normalize(design, pack=PACK, lexicon=lexicon, rules=rules)
    assert isinstance(result, NormalizeFailed), result
    assert result.problems
    return result


def _table(model: NormalizedModel, entity_id: str) -> Table:
    return next(t for t in model.tables if t.entity_id == entity_id)


def _col(table: Table, col_id: str) -> Column:
    return next(c for c in table.columns if c.id == col_id)


def _codes(result: NormalizeFailed) -> set[tuple[ProblemCode, str | None]]:
    return {(p.code, p.decision) for p in result.problems}


# ── 정상 ──────────────────────────────────────────────────────────────


def test_one_to_many_adds_parent_key_to_child_as_fk() -> None:
    model = _ok(BASE)
    warehouse, receipt = _table(model, "ENT-wh"), _table(model, "ENT-rc")
    (fk,) = model.foreign_keys

    assert fk.table_id == receipt.id and fk.parent_table_id == warehouse.id
    assert fk.parent_columns == warehouse.primary_key
    (fk_col_id,) = fk.columns
    fk_col = _col(receipt, fk_col_id)
    assert fk_col.physical_name == "wrhus_cd"  # D4 제안: 부모 키 물리명, DDL은 소문자
    assert fk_col.name == "창고코드"
    assert fk_col.relationship_id == "REL-01" and fk_col.attribute_id is None
    assert not fk_col.nullable  # optional=false → NOT NULL
    assert fk_col.domain == "코드C10"
    # 파생 객체는 원래 관계의 req_ids를 물려받는다
    assert fk_col.req_ids == ("REQ-02",) and fk.req_ids == ("REQ-02",)
    # 비식별이라 자식 PK는 자기 키만
    assert receipt.primary_key == (receipt.columns[0].id,)
    assert [c.physical_name for c in receipt.columns] == [
        "wrhsg_no",
        "wrhsg_qty",
        "dlng_dt",
        "wrhus_cd",
    ]
    assert model.pack == "inventory" and model.pack_version == "test" and model.rules_version


def test_optional_one_to_many_allows_null_fk() -> None:
    model = _ok(_design([WAREHOUSE, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-rc", optional=True)]))
    receipt = _table(model, "ENT-rc")
    assert _col(receipt, model.foreign_keys[0].columns[0]).nullable


def test_d12_composite_parent_key_gives_fk_column_group_in_parent_key_order() -> None:
    model = _ok(_design([SUPPLIER, RECEIPT], [_rel("REL-01", "ENT-sp", "ENT-rc")]))
    supplier, receipt = _table(model, "ENT-sp"), _table(model, "ENT-rc")
    (fk,) = model.foreign_keys

    assert len(supplier.primary_key) == 2  # 복합 PK 묶음
    assert fk.parent_columns == supplier.primary_key
    assert [_col(receipt, c).physical_name for c in fk.columns] == ["bzmn_no", "brnch_sn"]
    assert [_col(receipt, c).data_type for c in fk.columns] == ["varchar", "integer"]


def test_unique_attribute_becomes_single_column_group() -> None:
    warehouse = WAREHOUSE.evolve(
        attributes=[
            WAREHOUSE.attributes[0].model_dump(),
            {**WAREHOUSE.attributes[1].model_dump(), "is_unique": True},
        ]
    )
    model = _ok(_design([warehouse, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-rc")]))
    table = _table(model, "ENT-wh")
    assert table.unique_keys == ((table.columns[1].id,),)


def test_time_precision_and_domain_come_from_pack_term() -> None:
    receipt = _table(_ok(BASE), "ENT-rc")
    dt = next(c for c in receipt.columns if c.name == "거래일시")
    assert (dt.data_type, dt.time_precision, dt.domain) == ("timestamp", 0, "연월일시분초D")
    qty = next(c for c in receipt.columns if c.name == "입고수량")
    assert (qty.precision, qty.scale, qty.time_precision, qty.domain) == (15, 3, None, None)


def _fk(model: NormalizedModel, rel_id: str) -> ForeignKey:
    (fk,) = (f for f in model.foreign_keys if f.relationship_id == rel_id)
    return fk


def _names(table: Table, col_ids: tuple[str, ...]) -> list[str]:
    return [_col(table, c).physical_name for c in col_ids]


@pytest.mark.parametrize("optional", [False, True])
def test_d8_one_to_one_adds_unique_group_on_fk(optional: bool) -> None:
    rel = _rel("REL-01", "ENT-wh", "ENT-rc", cardinality="1:1", optional=optional)
    model = _ok(_design([WAREHOUSE, RECEIPT], [rel]))
    receipt, fk = _table(model, "ENT-rc"), _fk(model, "REL-01")
    assert receipt.unique_keys == (fk.columns,)
    assert receipt.primary_key == (receipt.columns[0].id,)  # 비식별이라 PK는 그대로
    assert _col(receipt, fk.columns[0]).nullable is optional


def test_identifying_puts_parent_key_columns_before_own_key_in_child_pk() -> None:
    rel = _rel("REL-01", "ENT-wh", "ENT-rc", identifying=True)
    model = _ok(_design([WAREHOUSE, RECEIPT], [rel]))
    warehouse, receipt, fk = _table(model, "ENT-wh"), _table(model, "ENT-rc"), _fk(model, "REL-01")
    assert _names(receipt, receipt.primary_key) == ["wrhus_cd", "wrhsg_no"]
    assert receipt.primary_key[:1] == fk.columns
    fk_col = _col(receipt, fk.columns[0])
    assert not fk_col.nullable and fk_col.references == warehouse.primary_key[0]
    assert receipt.unique_keys == ()


@pytest.mark.parametrize("child_rel_first", [False, True])
def test_d14_identifying_chain_uses_final_parent_key(child_rel_first: bool) -> None:
    """창고 → 입고 → 내역 식별 연쇄. 손자 FK는 입고의 확정된 PK(창고코드 + 입고번호) 전체를 받는다.

    관계 ID 순서가 위상 순서와 반대여도(손자 쪽 관계가 REL-01) 결과 모양은 같아야 한다.
    """
    upper, lower = ("REL-02", "REL-01") if child_rel_first else ("REL-01", "REL-02")
    rels = [
        _rel(upper, "ENT-wh", "ENT-rc", identifying=True),
        _rel(lower, "ENT-rc", "ENT-ln", identifying=True),
    ]
    model = _ok(_design([LINE, RECEIPT, WAREHOUSE], list(reversed(rels))))
    receipt, line, fk = _table(model, "ENT-rc"), _table(model, "ENT-ln"), _fk(model, lower)
    assert fk.parent_columns == receipt.primary_key
    assert [_col(line, c).references for c in fk.columns] == list(receipt.primary_key)
    assert _names(line, line.primary_key) == ["wrhus_cd", "wrhsg_no", "dsctn_sn"]
    assert _ok(_design([WAREHOUSE, RECEIPT, LINE], rels)) == model


def test_d14_child_with_two_identifying_parents_orders_pk_by_relationship_id() -> None:
    rels = [
        _rel("REL-01", "ENT-sp", "ENT-ln", identifying=True),
        _rel("REL-02", "ENT-wh", "ENT-ln", identifying=True),
    ]
    model = _ok(_design([WAREHOUSE, SUPPLIER, LINE], rels))
    line = _table(model, "ENT-ln")
    assert _names(line, line.primary_key) == ["bzmn_no", "brnch_sn", "wrhus_cd", "dsctn_sn"]


@pytest.mark.parametrize("own_key", [False, True])
def test_identifying_one_to_one_adds_unique_only_when_pk_has_more_than_fk(own_key: bool) -> None:
    """식별 1:1: 자기 키가 없으면 PK = FK라 이미 유일하다. 있으면 FK 묶음에 UNIQUE가 필요하다."""
    attrs = [_attr("ATTR-ln-nm", "창고명", length=200)]
    if own_key:
        attrs.insert(0, LINE.attributes[0].model_dump())
    line = _entity("ENT-ln", "내역", *attrs)
    rel = _rel("REL-01", "ENT-wh", "ENT-ln", cardinality="1:1", identifying=True)
    model = _ok(_design([WAREHOUSE, line], [rel]))
    table, fk = _table(model, "ENT-ln"), _fk(model, "REL-01")
    assert table.primary_key[: len(fk.columns)] == fk.columns
    assert table.unique_keys == ((fk.columns,) if own_key else ())


def test_d4_self_reference_adds_prefixed_fk_to_same_table() -> None:
    """maintenance A04 MNT-002 모양(설비 → 상위 설비). 접두어는 주입값, 약어는 사전에서 찾는다."""
    design = _design([WAREHOUSE], [_rel("REL-01", "ENT-wh", "ENT-wh", optional=True)])
    model = _ok(design, rules=RULES_SELF)
    warehouse, fk = _table(model, "ENT-wh"), _fk(model, "REL-01")
    assert fk.table_id == fk.parent_table_id == warehouse.id
    col = _col(warehouse, fk.columns[0])
    assert (col.name, col.physical_name, col.nullable, col.references) == (
        "상위창고코드",
        "up_wrhus_cd",
        True,
        warehouse.primary_key[0],
    )


def test_many_to_many_creates_one_junction_table_keyed_by_both_sides() -> None:
    design = _design(
        [WAREHOUSE, SUPPLIER],
        [_rel("REL-01", "ENT-wh", "ENT-sp", cardinality="N:M", optional=True)],
    )
    model = _ok(design)
    (junction,) = (t for t in model.tables if t.relationship_id == "REL-01")
    assert junction.entity_id is None
    assert (junction.name, junction.physical_name) == ("창고거래처", "wrhus_bcnc")
    assert [c.physical_name for c in junction.columns] == ["wrhus_cd", "bzmn_no", "brnch_sn"]
    assert junction.primary_key == tuple(c.id for c in junction.columns)
    # 연결 테이블과 그 칸·FK는 원래 관계의 req_ids를 물려받고, PK라 NULL을 허용하지 않는다
    assert junction.req_ids == ("REQ-02",)
    assert all(c.req_ids == ("REQ-02",) and not c.nullable for c in junction.columns)
    fks = sorted(model.foreign_keys, key=lambda f: len(f.columns))
    assert [f.parent_table_id for f in fks] == [_table(model, e).id for e in ("ENT-wh", "ENT-sp")]
    assert all(f.table_id == junction.id and f.req_ids == ("REQ-02",) for f in fks)
    # 엔티티 테이블에는 FK 칸이 생기지 않는다
    assert all(c.relationship_id is None for t in model.tables if t.entity_id for c in t.columns)
    # TC-F09: 두 번 정리해도 같고 연결 테이블이 늘지 않는다
    assert _ok(design) == model


# ── 성질 ──────────────────────────────────────────────────────────────


def test_same_input_gives_same_result_and_input_is_unchanged() -> None:
    before = BASE.model_dump()
    assert _ok(BASE) == _ok(BASE)
    assert BASE.model_dump() == before


def test_reordering_lists_with_same_ids_gives_same_result() -> None:
    """관계 ID는 그대로 두고 목록 순서만 바꾼다 → 결과가 같아야 한다 (통과해야 하는 성질)."""
    rels = [_rel("REL-01", "ENT-wh", "ENT-rc"), _rel("REL-02", "ENT-sp", "ENT-rc")]
    forward = _design([WAREHOUSE, SUPPLIER, RECEIPT], rels)
    backward = _design([RECEIPT, SUPPLIER, WAREHOUSE], list(reversed(rels)))
    assert _ok(forward) == _ok(backward)


def test_d2_limitation_a04_renumbering_changes_derived_ids() -> None:
    """현재 한계 기록 (D2): A04가 순번을 다시 매기면 같은 관계의 파생 ID가 바뀐다.

    이 테스트가 통과하는 것은 ID 안정성의 증거가 아니다. D2가 정해지면 기대를 반대로 바꾼다.
    """
    first = _ok(
        _design(
            [WAREHOUSE, SUPPLIER, RECEIPT],
            [_rel("REL-01", "ENT-wh", "ENT-rc"), _rel("REL-02", "ENT-sp", "ENT-rc")],
        )
    )
    renumbered = _ok(
        _design(
            [WAREHOUSE, SUPPLIER, RECEIPT],
            [_rel("REL-02", "ENT-wh", "ENT-rc"), _rel("REL-01", "ENT-sp", "ENT-rc")],
        )
    )

    def warehouse_fk(model: NormalizedModel) -> ForeignKey:
        parent = _table(model, "ENT-wh").id
        return next(f for f in model.foreign_keys if f.parent_table_id == parent)

    assert warehouse_fk(first).id != warehouse_fk(renumbered).id
    assert warehouse_fk(first).columns != warehouse_fk(renumbered).columns


# ── 문제 (결과 없음) ──────────────────────────────────────────────────


def test_d6_entity_without_key_fails() -> None:
    receipt = _entity("ENT-rc", "입고", _attr("ATTR-rc-qty", "입고수량"))
    result = _failed(_design([WAREHOUSE, receipt], [_rel("REL-01", "ENT-wh", "ENT-rc")]))
    assert _codes(result) == {(ProblemCode.NO_PRIMARY_KEY, "D6")}
    assert result.problems[0].target == "ENT-rc"


def test_parent_without_key_is_reported_once_as_missing_pk() -> None:
    """부모의 PK 없음이 원인이므로, 그 부모를 가리키는 관계는 따로 보고하지 않는다."""
    warehouse = _entity("ENT-wh", "창고", _attr("ATTR-wh-nm", "창고명"))
    result = _failed(_design([warehouse, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-rc")]))
    assert [(p.code, p.target) for p in result.problems] == [(ProblemCode.NO_PRIMARY_KEY, "ENT-wh")]


def test_d13_fk_name_matching_existing_attribute_is_a_conflict_even_with_same_type() -> None:
    """A03이 자식에 `창고코드`를 이미 넣음.

    이름·타입이 같아도 같은 대상을 가리킨다는 근거가 없어 재사용하지 않는다.
    """
    receipt = _entity(
        "ENT-rc",
        "입고",
        _attr("ATTR-rc-no", "입고번호", is_key=True),
        _attr("ATTR-rc-wh", "창고코드", nullable=False),  # 부모 키와 같은 타입·길이
    )
    result = _failed(_design([WAREHOUSE, receipt], [_rel("REL-01", "ENT-wh", "ENT-rc")]))
    assert _codes(result) == {(ProblemCode.FK_COLUMN_CONFLICT, "D13")}
    assert result.problems[0].target == "REL-01"


def test_d4_two_relationships_to_same_parent_key_conflict() -> None:
    """같은 두 엔티티 사이 관계 둘(예: 출고 창고·입고 창고).

    FK 이름 구분 규칙이 정해지기 전까지 충돌로 본다.
    """
    rels = [
        _rel("REL-01", "ENT-wh", "ENT-rc"),
        _rel("REL-02", "ENT-wh", "ENT-rc", req_ids=["REQ-03"]),
    ]
    result = _failed(_design([WAREHOUSE, RECEIPT], rels))
    assert _codes(result) == {(ProblemCode.FK_COLUMN_CONFLICT, "D4")}
    assert result.problems[0].target == "REL-02"
    # 읽는 사람이 왜 멈췄는지 알 수 있게 이유를 함께 적는다 (#11 R2 요청)
    assert "역할 구분이 필요합니다" in result.problems[0].detail


def test_repeated_reference_policy_preserves_two_roles_and_is_order_independent() -> None:
    rels = [_rel("REL-01", "ENT-wh", "ENT-rc"), _rel("REL-02", "ENT-wh", "ENT-rc", optional=True)]
    policy = replace(RULES, repeated_foreign_key="relationship_id")
    design = _design([WAREHOUSE, RECEIPT], rels)
    result = normalize(design, pack=PACK, lexicon=LEXICON, rules=policy)
    assert isinstance(result, Normalized)
    assert not check_output(result.model, design)
    assert len(result.model.foreign_keys) == 2
    table = next(t for t in result.model.tables if t.name == RECEIPT.name)
    columns = [c for c in table.columns if c.relationship_id]
    assert len({c.physical_name for c in columns}) == 2
    assert all(c.physical_name.startswith("wrhus_cd_r") for c in columns)
    assert {c.relationship_id: c.nullable for c in columns} == {"REL-01": False, "REL-02": True}
    reversed_result = normalize(
        _design([RECEIPT, WAREHOUSE], list(reversed(rels))),
        pack=PACK,
        lexicon=LEXICON,
        rules=policy,
    )
    assert reversed_result == result


def test_repeated_reference_composite_keys_keep_pairs_and_length_checks() -> None:
    rels = [_rel("REL-01", "ENT-sp", "ENT-rc"), _rel("REL-02", "ENT-sp", "ENT-rc")]
    policy = replace(RULES, repeated_foreign_key="relationship_id")
    result = normalize(_design([SUPPLIER, RECEIPT], rels), pack=PACK, lexicon=LEXICON, rules=policy)
    assert isinstance(result, Normalized)
    assert all(len(fk.columns) == len(fk.parent_columns) == 2 for fk in result.model.foreign_keys)
    limited = normalize(
        _design(
            [WAREHOUSE, RECEIPT],
            [_rel("REL-01", "ENT-wh", "ENT-rc"), _rel("REL-02", "ENT-wh", "ENT-rc")],
        ),
        pack=PACK,
        lexicon=LEXICON,
        rules=replace(policy, max_bytes=15),
    )
    assert isinstance(limited, NormalizeFailed)
    assert {p.target for p in limited.problems if p.code == ProblemCode.NAME_TOO_LONG} == {
        "REL-01",
        "REL-02",
    }


def test_repeated_reference_policy_does_not_merge_keys_from_different_parents() -> None:
    other = _entity("ENT-other", "출고", _attr("ATTR-other", "창고코드", is_key=True))
    design = _design(
        [WAREHOUSE, other, RECEIPT],
        [_rel("REL-01", "ENT-wh", "ENT-rc"), _rel("REL-02", "ENT-other", "ENT-rc")],
    )
    before = design.model_dump()
    result = normalize(
        design,
        pack=PACK,
        lexicon=LEXICON,
        rules=replace(RULES, repeated_foreign_key="relationship_id"),
    )
    assert isinstance(result, NormalizeFailed)
    assert _codes(result) == {(ProblemCode.FK_COLUMN_CONFLICT, "D4")}
    detail = result.problems[0].detail
    assert "REL-01" in detail and "REL-02" in detail and "ENT-other" in detail
    assert design.model_dump() == before


def test_repeated_reference_policy_keeps_existing_child_key_collision_blocked() -> None:
    child = _entity("ENT-rc", "입고", _attr("ATTR-child-key", "창고코드", is_key=True))
    design = _design([WAREHOUSE, child], [_rel("REL-01", "ENT-wh", "ENT-rc")])
    result = normalize(
        design,
        pack=PACK,
        lexicon=LEXICON,
        rules=replace(RULES, repeated_foreign_key="relationship_id"),
    )
    assert isinstance(result, NormalizeFailed)
    assert _codes(result) == {(ProblemCode.FK_COLUMN_CONFLICT, "D13")}
    assert "ATTR-child-key" in result.problems[0].detail
    assert child.attributes[0].is_key


def test_d5_unregistered_word_is_reported_as_pending() -> None:
    lexicon = FixtureLexicon()
    del lexicon.words["입고수량"]
    result = _failed(BASE, lexicon)
    (problem,) = result.problems
    assert (problem.code, problem.decision, problem.pending) == (
        ProblemCode.UNRESOLVED_NAME,
        "D5",
        True,
    )


def test_name_longer_than_pack_limit_fails() -> None:
    lexicon = FixtureLexicon(words={"입고": "W" * (RULES.max_bytes + 1)})
    assert _codes(_failed(BASE, lexicon)) == {(ProblemCode.NAME_TOO_LONG, None)}


def test_reserved_word_alone_fails() -> None:
    lexicon = FixtureLexicon(words={"입고번호": "ORDER"})
    assert _codes(_failed(BASE, lexicon)) == {(ProblemCode.RESERVED_WORD, None)}


def test_duplicate_column_and_table_names_fail() -> None:
    lexicon = FixtureLexicon(words={"입고수량": "WRHSG_NO", "입고": "WRHUS"})
    result = _failed(BASE, lexicon)
    details = sorted(p.detail for p in result.problems)
    assert {p.code for p in result.problems} == {ProblemCode.DUPLICATE_NAME}
    assert details == ["컬럼 물리명 wrhsg_no 중복", "테이블 물리명 wrhus 중복"]


@pytest.mark.parametrize(
    ("parent", "changes", "decision", "pending"),
    [
        ("ENT-wh", {"cardinality": "N:M", "identifying": True}, "D8", False),
        ("ENT-rc", {"identifying": True}, "D8", False),  # 자기참조
        ("ENT-rc", {"cardinality": "N:M", "optional": True}, "D4", True),  # 자기참조
    ],
    ids=["identifying_many_to_many", "identifying_self_reference", "self_many_to_many"],
)
def test_unsupported_relationship_kinds_fail_instead_of_partial_result(
    parent: str, changes: dict[str, Any], decision: str, pending: bool
) -> None:
    """원인을 decision으로 나눈다 (#15 R1 댓글 2번).

    D8: A04가 막는 조합(식별 N:M·식별 자기참조, #79) → 설계 수정. D4: 설계는 맞지만 이름 규칙이
    없어 처리하지 못하는 자기참조 N:M → 결정 대기(pending), 사람이 지원 방안을 정한다.
    """
    design = _design([WAREHOUSE, RECEIPT], [_rel("REL-01", parent, "ENT-rc", **changes)])
    result = _failed(design, rules=RULES_SELF)
    assert _codes(result) == {(ProblemCode.UNSUPPORTED_RELATIONSHIP, decision)}
    assert [p.pending for p in result.problems] == [pending]


def test_d11_optional_identifying_relationship_fails() -> None:
    rel = _rel("REL-01", "ENT-wh", "ENT-rc", identifying=True, optional=True)
    assert _codes(_failed(_design([WAREHOUSE, RECEIPT], [rel]))) == {
        (ProblemCode.OPTIONAL_IDENTIFYING, "D11")
    }


def test_d14_identifying_cycle_is_one_problem_and_descendants_are_not_reported() -> None:
    rels = [
        _rel("REL-01", "ENT-wh", "ENT-rc", identifying=True),
        _rel("REL-02", "ENT-rc", "ENT-wh", identifying=True),
        _rel("REL-03", "ENT-rc", "ENT-ln", identifying=True),  # 순환의 자손
    ]
    result = _failed(_design([WAREHOUSE, RECEIPT, LINE], rels))
    assert [(p.code, p.target) for p in result.problems] == [
        (ProblemCode.IDENTIFYING_CYCLE, "ENT-rc,ENT-wh")
    ]


def test_d14_entity_linking_two_cycles_is_blocked_but_not_named_as_cycle() -> None:
    """창고 ↔ 입고 → 내역 → 거래처 ↔ 출고 (Codex 재현 사례 A ↔ B → X → C ↔ D).

    내역(X)은 두 순환 사이를 잇기만 한다. 순서를 정할 수 없어 막히지만 순환의 원인은 아니다.
    """
    issue = _entity("ENT-is", "출고", _attr("ATTR-is-no", "출고번호", is_key=True))
    rels = [
        _rel("REL-01", "ENT-wh", "ENT-rc", identifying=True),
        _rel("REL-02", "ENT-rc", "ENT-wh", identifying=True),
        _rel("REL-03", "ENT-rc", "ENT-ln", identifying=True),
        _rel("REL-04", "ENT-ln", "ENT-sp", identifying=True),
        _rel("REL-05", "ENT-sp", "ENT-is", identifying=True),
        _rel("REL-06", "ENT-is", "ENT-sp", identifying=True),
    ]
    result = _failed(_design([WAREHOUSE, RECEIPT, LINE, SUPPLIER, issue], rels))
    assert [(p.code, p.target) for p in result.problems] == [
        (ProblemCode.IDENTIFYING_CYCLE, "ENT-is,ENT-rc,ENT-sp,ENT-wh")
    ]


def test_d14_identifying_parent_without_key_blocks_descendants_with_one_cause() -> None:
    warehouse = _entity("ENT-wh", "창고", _attr("ATTR-wh-nm", "창고명"))
    rels = [
        _rel("REL-01", "ENT-wh", "ENT-rc", identifying=True),
        _rel("REL-02", "ENT-rc", "ENT-ln", identifying=True),
    ]
    result = _failed(_design([warehouse, RECEIPT, LINE], rels))
    assert [(p.code, p.target) for p in result.problems] == [(ProblemCode.NO_PRIMARY_KEY, "ENT-wh")]


def test_d13_identifying_child_already_holding_parent_key_conflicts() -> None:
    """A08 예시의 수불내역처럼 자식이 부모 키를 자기 속성(키)으로 이미 가진 경우 (#12 본문)."""
    receipt = _entity(
        "ENT-rc",
        "입고",
        _attr("ATTR-rc-wh", "창고코드", is_key=True),
        _attr("ATTR-rc-no", "입고번호", is_key=True),
    )
    rels = [
        _rel("REL-01", "ENT-wh", "ENT-rc", identifying=True),
        _rel("REL-02", "ENT-rc", "ENT-ln", identifying=True),
    ]
    result = _failed(_design([WAREHOUSE, receipt, LINE], rels))
    assert [(p.code, p.decision, p.target) for p in result.problems] == [
        (ProblemCode.FK_COLUMN_CONFLICT, "D13", "REL-01")
    ]


def test_d4_self_reference_without_naming_rule_fails() -> None:
    """naming.yaml column.self_reference_prefix가 빈칸(미정)이면 접두어가 없어 막는다."""
    design = _design([WAREHOUSE], [_rel("REL-01", "ENT-wh", "ENT-wh", optional=True)])
    result = _failed(design)
    assert _codes(result) == {(ProblemCode.NAMING_RULE_MISSING, "D4")}
    assert "column.self_reference_prefix" in result.problems[0].detail


def test_d4_junction_name_parent_child_is_the_same_as_unset() -> None:
    """table.junction_name의 parent_child는 미정일 때의 D4 제안 동작(부모 + 자식)과 같다."""
    rel = _rel("REL-01", "ENT-wh", "ENT-sp", cardinality="N:M", optional=True)
    design = _design([WAREHOUSE, SUPPLIER], [rel])
    unset = _ok(design)
    named = _ok(design, rules=replace(RULES, junction_name="parent_child"))
    assert named == unset
    (junction,) = (t for t in named.tables if t.relationship_id == "REL-01")
    assert junction.physical_name == "wrhus_bcnc"


def test_unknown_junction_name_rule_is_not_silently_ignored() -> None:
    """load_naming_rules가 거르지만, 규칙 객체를 직접 만든 경우도 조용히 넘기지 않는다."""
    rel = _rel("REL-01", "ENT-wh", "ENT-sp", cardinality="N:M", optional=True)
    design = _design([WAREHOUSE, SUPPLIER], [rel])
    with pytest.raises(ValueError, match="연결 테이블 이름 규칙"):
        normalize(
            design, pack=PACK, lexicon=LEXICON, rules=replace(RULES, junction_name="child_parent")
        )


def test_d5_self_reference_prefix_not_in_dictionary_is_pending() -> None:
    design = _design([WAREHOUSE], [_rel("REL-01", "ENT-wh", "ENT-wh", optional=True)])
    result = _failed(design, rules=replace(RULES, self_reference_prefix="최상위"))
    assert [(p.code, p.target, p.pending) for p in result.problems] == [
        (ProblemCode.UNRESOLVED_NAME, "REL-01", True)
    ]


def test_many_to_many_side_without_key_fails() -> None:
    supplier = _entity("ENT-sp", "거래처", _attr("ATTR-sp-bz", "사업자번호"))
    rel = _rel("REL-01", "ENT-wh", "ENT-sp", cardinality="N:M")
    result = _failed(_design([WAREHOUSE, supplier], [rel]))
    assert [(p.code, p.target) for p in result.problems] == [(ProblemCode.NO_PRIMARY_KEY, "ENT-sp")]


def test_d4_many_to_many_sides_with_same_key_name_conflict() -> None:
    issue = _entity("ENT-is", "출고", _attr("ATTR-is-wh", "창고코드", is_key=True))
    rel = _rel("REL-01", "ENT-wh", "ENT-is", cardinality="N:M")
    result = _failed(_design([WAREHOUSE, issue], [rel]))
    assert [(p.code, p.decision, p.target) for p in result.problems] == [
        (ProblemCode.FK_COLUMN_CONFLICT, "D4", "REL-01")
    ]


def test_all_problems_are_collected_not_just_the_first() -> None:
    receipt = _entity("ENT-rc", "입고", _attr("ATTR-rc-x", "미등록칸"))
    result = _failed(_design([WAREHOUSE, receipt], [_rel("REL-01", "ENT-wh", "ENT-rc")]))
    assert {p.code for p in result.problems} == {
        ProblemCode.NO_PRIMARY_KEY,
        ProblemCode.UNRESOLVED_NAME,
    }


# ── 추적 검사 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("design", "code", "targets"),
    [
        (
            _design([WAREHOUSE, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-없음")]),
            ProblemCode.INPUT_TRACE,
            "REL-01",
        ),
        (
            _design([WAREHOUSE, WAREHOUSE, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-rc")]),
            ProblemCode.INPUT_TRACE,
            "ENT-wh ATTR-wh-cd ATTR-wh-nm",  # 엔티티가 겹치면 속성 ID도 겹친다
        ),
        (
            _design(
                [WAREHOUSE, RECEIPT],
                [_rel("REL-01", "ENT-wh", "ENT-rc"), _rel("REL-01", "ENT-wh", "ENT-rc")],
            ),
            ProblemCode.INPUT_TRACE,
            "REL-01",
        ),
        (
            _design([WAREHOUSE, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-rc", req_ids=["REQ-99"])]),
            ProblemCode.INPUT_TRACE,
            "REL-01",
        ),
        (
            _design(
                [WAREHOUSE, RECEIPT.evolve(pack="maintenance")],
                [_rel("REL-01", "ENT-wh", "ENT-rc")],
            ),
            ProblemCode.PACK_MISMATCH,
            "ENT-rc",
        ),
    ],
    ids=[
        "unknown_entity",
        "duplicate_entity",
        "duplicate_relationship",
        "unknown_req",
        "other_pack",
    ],
)
def test_bad_input_stops_before_normalizing(
    design: DesignState, code: ProblemCode, targets: str
) -> None:
    result = _failed(design)
    assert {(p.code, p.target) for p in result.problems} == {(code, t) for t in targets.split()}


def test_output_check_finds_missing_refs_and_duplicate_ids() -> None:
    """정상 결과를 일부러 망가뜨려 출력 검사가 잡는지 본다 (정리 코드의 실수 방어)."""
    model = _ok(BASE)
    receipt = _table(model, "ENT-rc")
    fk = model.foreign_keys[0]
    broken_receipt = Table(
        **{
            **receipt.__dict__,
            "columns": (*receipt.columns[:-1], receipt.columns[0]),  # FK 칸을 지우고 ID 중복
            "req_ids": ("REQ-99",),
        }
    )
    broken_fk = ForeignKey(**{**fk.__dict__, "parent_table_id": "TBL-없음"})
    broken = NormalizedModel(
        **{
            **model.__dict__,
            "tables": tuple(broken_receipt if t.id == receipt.id else t for t in model.tables),
            "foreign_keys": (broken_fk,),
        }
    )
    details = {p.detail for p in check_output(broken, BASE)}
    assert {p.code for p in check_output(broken, BASE)} == {ProblemCode.OUTPUT_TRACE}
    assert "컬럼 ID 중복" in details
    assert "없는 요구사항 REQ-99" in details
    assert "없는 부모 테이블 TBL-없음" in details
    assert any(d.startswith("자식 테이블에 없는 컬럼") for d in details)
    assert check_output(model, BASE) == []


def _with_table(model: NormalizedModel, table: Table) -> NormalizedModel:
    tables = tuple(table if t.id == table.id else t for t in model.tables)
    return _copy(model, tables=tables)


@pytest.mark.parametrize("what", ["table", "column"])
def test_output_check_finds_table_or_column_without_source(what: str) -> None:
    """출처(엔티티·속성) 참조를 지운 테이블·컬럼은 다른 검사에 걸리지 않으므로 따로 잡아야 한다."""
    model = _ok(BASE)
    receipt = _table(model, "ENT-rc")
    if what == "table":
        broken = _with_table(model, _copy(receipt, entity_id=None))
        # 출처를 지우면 속성 칸의 소속과 엔티티별 테이블 수 검사도 함께 걸린다 (같은 원인)
        expected = [
            problem(ProblemCode.OUTPUT_TRACE, receipt.id, "출처(엔티티·관계) 참조가 없음"),
            *(
                problem(
                    ProblemCode.OUTPUT_TRACE, c.id, f"테이블의 엔티티에 없는 속성 {c.attribute_id}"
                )
                for c in receipt.columns
                if c.attribute_id
            ),
            problem(ProblemCode.OUTPUT_TRACE, "ENT-rc", "엔티티 테이블이 0개"),
        ]
    else:
        col = receipt.columns[1]  # 입고수량: PK·FK가 아닌 일반 속성 칸
        cols = tuple(_copy(c, attribute_id=None) if c.id == col.id else c for c in receipt.columns)
        broken = _with_table(model, _copy(receipt, columns=cols))
        expected = [problem(ProblemCode.OUTPUT_TRACE, col.id, "출처(속성·관계) 참조가 없음")]
    assert check_output(broken, BASE) == expected


def test_output_check_finds_fk_pointing_to_other_existing_child_column() -> None:
    """FK 칸을 자식의 다른 기존 칸으로 바꾸면 칸 수·존재 검사는 통과하므로 따로 잡아야 한다."""
    model = _ok(BASE)
    receipt = _table(model, "ENT-rc")
    fk = model.foreign_keys[0]
    other = receipt.columns[0].id  # 입고번호: 자식에 있지만 관계에서 만든 칸이 아님
    broken = _copy(model, foreign_keys=(_copy(fk, columns=(other,)),))
    assert check_output(broken, BASE) == [
        problem(ProblemCode.OUTPUT_TRACE, fk.id, f"FK 칸 {other}이 관계 REL-01에서 만든 칸이 아님")
    ]


def _with_column(
    model: NormalizedModel, entity_id: str, col_id: str, **changes: Any
) -> NormalizedModel:
    table = _table(model, entity_id)
    cols = tuple(_copy(c, **changes) if c.id == col_id else c for c in table.columns)
    return _with_table(model, _copy(table, columns=cols))


def test_output_check_finds_both_sources_on_table_and_column() -> None:
    model = _ok(BASE)
    receipt = _table(model, "ENT-rc")
    both_table = _with_table(model, _copy(receipt, relationship_id="REL-01"))
    # 1:N 관계에 연결 테이블이 생긴 것처럼 보이므로 완전성 검사도 함께 걸린다
    assert [(p.target, p.detail) for p in check_output(both_table, BASE)] == [
        (receipt.id, "출처(엔티티·관계)가 둘 다 있음"),
        ("REL-01", "연결 테이블이 1개"),
    ]
    qty = receipt.columns[1].id
    both_column = _with_column(model, "ENT-rc", qty, relationship_id="REL-01")
    assert [(p.target, p.detail) for p in check_output(both_column, BASE)] == [
        (qty, "출처(속성·관계)가 둘 다 있음")
    ]


def test_output_check_finds_attribute_column_in_other_entity_table() -> None:
    model = _ok(BASE)
    warehouse, receipt = _table(model, "ENT-wh"), _table(model, "ENT-rc")
    moved = warehouse.columns[1]  # 창고명 (PK 아님)
    broken = _with_table(
        _with_table(model, _copy(warehouse, columns=warehouse.columns[:1])),
        _copy(receipt, columns=(*receipt.columns, moved)),
    )
    assert [(p.target, p.detail) for p in check_output(broken, BASE)] == [
        (moved.id, "테이블의 엔티티에 없는 속성 ATTR-wh-nm")
    ]


def test_output_check_finds_nullable_pk_and_missing_fk() -> None:
    model = _ok(BASE)
    receipt = _table(model, "ENT-rc")
    pk_col = receipt.primary_key[0]
    nullable_pk = _with_column(model, "ENT-rc", pk_col, nullable=True)
    assert [(p.target, p.detail) for p in check_output(nullable_pk, BASE)] == [
        (receipt.id, f"PK 칸 {pk_col}이 NULL 허용")
    ]
    no_fk = _copy(model, foreign_keys=())
    assert [(p.target, p.detail) for p in check_output(no_fk, BASE)] == [("REL-01", "FK가 0개")]


def test_output_check_finds_swapped_or_retyped_composite_fk_columns() -> None:
    design = _design([SUPPLIER, RECEIPT], [_rel("REL-01", "ENT-sp", "ENT-rc")])
    model = _ok(design)
    fk = _fk(model, "REL-01")
    swapped = _copy(model, foreign_keys=(_copy(fk, columns=fk.columns[::-1]),))
    assert [(p.target, p.detail) for p in check_output(swapped, design)] == [
        (fk.id, f"FK 칸 {fk.columns[1]}의 짝이 부모 칸 {fk.parent_columns[0]}이 아님"),
        (fk.id, f"FK 칸 {fk.columns[0]}의 짝이 부모 칸 {fk.parent_columns[1]}이 아님"),
    ]
    retyped = _with_column(model, "ENT-rc", fk.columns[0], length=99)
    assert [(p.target, p.detail) for p in check_output(retyped, design)] == [
        (fk.id, f"FK 칸 {fk.columns[0]}의 타입이 부모 칸 {fk.parent_columns[0]}과 다름")
    ]


# ── 경계 ──────────────────────────────────────────────────────────────


def test_codegen_does_not_import_llm_or_nodes() -> None:
    """생성기는 LLM client를 import하지 않는다 (CLAUDE.md). 노드 모듈도 LLM을 가져오므로 막는다."""
    for path in (ROOT / "specton/codegen").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert not name.startswith(("specton.llm", "specton.nodes", "openai")), path


# ── #129 리뷰 반영 ────────────────────────────────────────────────────


def test_required_self_reference_fails_because_top_row_cannot_be_inserted() -> None:
    """필수 자기참조는 FK가 NOT NULL이라 상위가 없는 최상위 행을 넣을 수 없다."""
    design = _design([WAREHOUSE], [_rel("REL-01", "ENT-wh", "ENT-wh", optional=False)])
    result = _failed(design, rules=RULES_SELF)
    assert [(p.code, p.target) for p in result.problems] == [
        (ProblemCode.REQUIRED_SELF_REFERENCE, "REL-01")
    ]


def test_attribute_type_different_from_term_domain_type_fails() -> None:
    """속성 이름이 팩 용어와 같은데 타입이 그 용어 도메인의 타입과 다르면 보고한다."""
    lexicon = FixtureLexicon(
        terms={"창고코드": TermInfo("WRHUS_CD", "코드C10", data_type=SqlType.CHAR)}
    )
    wrong = _entity(
        "ENT-wh",
        "창고",
        _attr("ATTR-wh-cd", "창고코드", is_key=True, data_type="integer", length=None),
    )
    result = _failed(_design([wrong], []), lexicon=lexicon)
    assert [p.code for p in result.problems] == [ProblemCode.DOMAIN_TYPE_MISMATCH]


def test_single_key_attribute_marked_unique_gets_no_extra_unique() -> None:
    """PK 칸 하나가 is_unique이기도 하면 PK가 이미 유일하므로 UNIQUE를 더하지 않는다."""
    warehouse = _entity(
        "ENT-wh", "창고", _attr("ATTR-wh-cd", "창고코드", is_key=True, is_unique=True)
    )
    model = _ok(_design([warehouse], []))
    (table,) = model.tables
    assert table.unique_keys == ()


def test_unique_key_stays_when_inherited_parent_key_makes_the_final_pk_wider() -> None:
    """자기 키(입고번호)가 UNIQUE이고 식별 관계로 부모 키를 물려받으면 최종 PK는 창고코드+입고번호.

    이때 입고번호 단독 UNIQUE는 최종 PK와 다르므로 남아야 한다 (창고만 달라도 같은 번호를 막음).
    """
    receipt = _entity(
        "ENT-rc", "입고", _attr("ATTR-rc-no", "입고번호", is_key=True, is_unique=True)
    )
    rel = _rel("REL-01", "ENT-wh", "ENT-rc", identifying=True)
    model = _ok(_design([WAREHOUSE, receipt], [rel]))
    table = _table(model, "ENT-rc")
    assert _names(table, table.primary_key) == ["wrhus_cd", "wrhsg_no"]
    assert [_names(table, u) for u in table.unique_keys] == [["wrhsg_no"]]


def test_relationships_are_ordered_by_number_not_text() -> None:
    """`REL-9`가 `REL-10`보다 먼저 처리되어 복합 PK 칸이 번호 순으로 놓인다."""
    rels = [
        _rel("REL-10", "ENT-wh", "ENT-rc", identifying=True),
        _rel("REL-9", "ENT-sp", "ENT-rc", identifying=True),
    ]
    supplier = _entity("ENT-sp", "거래처", _attr("ATTR-sp-cd", "거래처코드", is_key=True))
    lexicon = FixtureLexicon(words={"거래처코드": "BCNC_CD"})
    model = _ok(_design([WAREHOUSE, supplier, RECEIPT], rels), lexicon=lexicon)
    receipt = _table(model, "ENT-rc")
    sources = [_col(receipt, c).relationship_id for c in receipt.primary_key]
    assert sources[:2] == ["REL-9", "REL-10"]
