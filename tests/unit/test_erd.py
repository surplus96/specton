"""ERD 생성 (#13, TC-F10): 정리된 모델 → Mermaid erDiagram.

- 관계 수·참조가 원본 모델과 일치한다 (FK마다 선 하나, 선은 설계 관계를 가리킨다)
- 관계·키·선택 여부가 표기에 드러난다
- Mermaid 11.15.0이 받지 못하는 글자를 쓰지 않는다 (실측한 문법 규칙, #13 댓글)
"""

import re
from typing import Any

import pytest

from specton.codegen.erd import erd_edges, render_erd
from specton.codegen.model import Normalized
from specton.codegen.naming import DEFAULT_PACK_ROOT
from specton.codegen.normalize_step import normalize_from_state
from specton.contracts import DesignState, Entity, Relationship, Requirement
from specton.contracts.normalized import NormalizedModel
from specton.contracts.state import VersionInfo
from specton.packs.build import read_yaml

# ── 시험 모델 ─────────────────────────────────────────────
# 창고 ─1:N 필수 비식별─ 입고 / 입고 ─1:N 식별─ 입고내역 / 품목분류 자기참조(선택)
# 품목 ─N:M─ 거래처 (연결 테이블 품목거래처) / 품목 ─1:1 선택─ 품목사진


def _col(cid: str, name: str, physical: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": cid,
        "name": name,
        "physical_name": physical,
        "data_type": "varchar",
        "length": 20,
        "precision": None,
        "scale": None,
        "time_precision": None,
        "domain": None,
        "nullable": False,
        "req_ids": ["REQ-01"],
        "attribute_id": f"ATTR-{cid}",
    }
    return {**base, **extra}


def _fk_col(
    cid: str, name: str, physical: str, rel: str, refs: str, **extra: Any
) -> dict[str, Any]:
    return _col(
        cid, name, physical, attribute_id=None, relationship_id=rel, references=refs, **extra
    )


def _table(
    tid: str, name: str, physical: str, columns: list[dict[str, Any]], pk: list[str], **extra: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": tid,
        "name": name,
        "physical_name": physical,
        "columns": columns,
        "primary_key": pk,
        "unique_keys": [],
        "req_ids": ["REQ-01"],
    }
    return {**base, **extra}


def _fk(
    fid: str, rel: str, table: str, cols: list[str], parent: str, parent_cols: list[str]
) -> dict[str, Any]:
    return {
        "id": fid,
        "relationship_id": rel,
        "table_id": table,
        "columns": cols,
        "parent_table_id": parent,
        "parent_columns": parent_cols,
        "req_ids": ["REQ-01"],
    }


def _rel(rid: str, parent: str, child: str, **extra: Any) -> Relationship:
    data: dict[str, Any] = {
        "id": rid,
        "parent": parent,
        "child": child,
        "cardinality": "1:N",
        "optional": False,
        "identifying": False,
        "rationale": '"근거" 설명.',
        "req_ids": ["REQ-01"],
    }
    return Relationship.model_validate({**data, **extra})


RELATIONSHIPS = (
    _rel("REL-01", "ENT-wh", "ENT-rc"),
    _rel("REL-02", "ENT-rc", "ENT-rl", identifying=True),
    _rel("REL-03", "ENT-cl", "ENT-cl", optional=True),
    _rel("REL-04", "ENT-it", "ENT-vd", cardinality="N:M"),
    _rel("REL-05", "ENT-it", "ENT-ph", cardinality="1:1", optional=True),
)

MODEL = NormalizedModel.model_validate(
    {
        "pack": "inventory",
        "pack_version": "0.1.7",
        "rules_version": "normalize-v0",
        "lexicon_digest": "x",
        "tables": [
            _table(
                "TBL-cl",
                "품목분류",
                "item_clsf",
                [
                    _col("C-cl-cd", "분류코드", "clsf_cd"),
                    _fk_col(
                        "C-cl-up", "상위분류코드", "up_clsf_cd", "REL-03", "C-cl-cd", nullable=True
                    ),
                ],
                ["C-cl-cd"],
                entity_id="ENT-cl",
            ),
            _table(
                "TBL-it",
                "품목",
                "item",
                [
                    _col("C-it-cd", "품목코드", "item_cd"),
                    _col(
                        "C-it-pr",
                        "단가",
                        "untprc",
                        data_type="numeric",
                        length=None,
                        precision=12,
                        scale=2,
                    ),
                    _col("C-it-io", "입·출고구분", "io_se", data_type="char", length=1),
                    _col("C-it-1", "1차 단가", "frst_untprc", data_type="integer", length=None),
                    _col("C-it-bc", "바코드", "brcd", nullable=True),
                ],
                ["C-it-cd"],
                unique_keys=[["C-it-bc"]],
                entity_id="ENT-it",
            ),
            _table(
                "TBL-ph",
                "품목사진",
                "item_phto",
                [
                    _col("C-ph-no", "사진번호", "phto_no"),
                    _fk_col("C-ph-it", "품목코드", "item_cd", "REL-05", "C-it-cd", nullable=True),
                ],
                ["C-ph-no"],
                unique_keys=[["C-ph-it"]],
                entity_id="ENT-ph",
            ),
            _table(
                "TBL-rc",
                "입고",
                "wrhsg",
                [
                    _col("C-rc-no", "입고번호", "wrhsg_no"),
                    _col(
                        "C-rc-dt",
                        "입고일시",
                        "wrhsg_dt",
                        data_type="timestamp",
                        length=None,
                        time_precision=3,
                    ),
                    _fk_col("C-rc-wh", "창고코드", "wrhus_cd", "REL-01", "C-wh-cd"),
                ],
                ["C-rc-no"],
                entity_id="ENT-rc",
            ),
            _table(
                "TBL-rl",
                "입고내역",
                "wrhsg_dtl",
                [
                    _fk_col("C-rl-rc", "입고번호", "wrhsg_no", "REL-02", "C-rc-no"),
                    _col("C-rl-sn", "순번", "sn", data_type="integer", length=None),
                ],
                ["C-rl-rc", "C-rl-sn"],
                entity_id="ENT-rl",
            ),
            _table(
                "TBL-vd",
                "거래처",
                "bzpt",
                [_col("C-vd-cd", "거래처코드", "bzpt_cd")],
                ["C-vd-cd"],
                entity_id="ENT-vd",
            ),
            _table(
                "TBL-wh",
                "창고",
                "wrhus",
                [_col("C-wh-cd", "창고코드", "wrhus_cd")],
                ["C-wh-cd"],
                entity_id="ENT-wh",
            ),
            _table(
                "TBL-x4",
                "품목거래처",
                "item_bzpt",
                [
                    _fk_col("C-x4-it", "품목코드", "item_cd", "REL-04", "C-it-cd"),
                    _fk_col("C-x4-vd", "거래처코드", "bzpt_cd", "REL-04", "C-vd-cd"),
                ],
                ["C-x4-it", "C-x4-vd"],
                relationship_id="REL-04",
            ),
        ],
        "foreign_keys": [
            _fk("FK-01", "REL-01", "TBL-rc", ["C-rc-wh"], "TBL-wh", ["C-wh-cd"]),
            _fk("FK-02", "REL-02", "TBL-rl", ["C-rl-rc"], "TBL-rc", ["C-rc-no"]),
            _fk("FK-03", "REL-03", "TBL-cl", ["C-cl-up"], "TBL-cl", ["C-cl-cd"]),
            _fk("FK-04", "REL-04", "TBL-x4", ["C-x4-it"], "TBL-it", ["C-it-cd"]),
            _fk("FK-05", "REL-04", "TBL-x4", ["C-x4-vd"], "TBL-vd", ["C-vd-cd"]),
            _fk("FK-06", "REL-05", "TBL-ph", ["C-ph-it"], "TBL-it", ["C-it-cd"]),
        ],
    }
)

EDGE_LINE = re.compile(r'^    (\w+) (\|\||\|o)(--|\.\.)(o\{|o\|) (\w+) : "([\w-]+)"$')


def _edge_lines(text: str) -> list[tuple[str, ...]]:
    return [m.groups() for line in text.splitlines() if (m := EDGE_LINE.match(line))]


# ── TC-F10: 관계 수·참조 ───────────────────────────────────


def test_one_line_per_foreign_key_and_every_relationship_is_drawn() -> None:
    edges = erd_edges(MODEL, RELATIONSHIPS)
    assert [e.foreign_key_id for e in edges] == [fk.id for fk in MODEL.foreign_keys]
    assert {e.relationship_id for e in edges} == {r.id for r in RELATIONSHIPS}
    lines = _edge_lines(render_erd(MODEL, RELATIONSHIPS))
    assert len(lines) == len(MODEL.foreign_keys)
    # N:M 하나는 연결 테이블을 거치는 선 둘이다
    assert [line[5] for line in lines].count("REL-04") == 2


def test_lines_join_the_tables_named_in_the_foreign_key() -> None:
    idents = {t.id: t.physical_name for t in MODEL.tables}
    by_fk = {fk.id: fk for fk in MODEL.foreign_keys}
    lines = _edge_lines(render_erd(MODEL, RELATIONSHIPS))
    for edge, line in zip(erd_edges(MODEL, RELATIONSHIPS), lines, strict=True):
        fk = by_fk[edge.foreign_key_id]
        assert (line[0], line[4]) == (idents[fk.parent_table_id], idents[fk.table_id])


def test_every_table_is_declared_once() -> None:
    text = render_erd(MODEL, RELATIONSHIPS)
    for table in MODEL.tables:
        assert text.count(f'    {table.physical_name}["{table.name}"] {{') == 1


def test_foreign_key_to_unknown_relationship_stops() -> None:
    with pytest.raises(ValueError, match="FK-01: 설계에 없는 관계"):
        erd_edges(MODEL, RELATIONSHIPS[1:])


# ── 관계·키·선택 여부 표기 ─────────────────────────────────


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("REL-01", ("||", "..", "o{")),  # 1:N 필수 비식별
        ("REL-02", ("||", "--", "o{")),  # 1:N 식별
        ("REL-03", ("|o", "..", "o{")),  # 자기참조 선택
        ("REL-05", ("|o", "..", "o|")),  # 1:1 선택
        ("REL-04", ("||", "--", "o{")),  # N:M 연결 테이블: 부모 키가 연결 테이블 PK
    ],
)
def test_markers_show_cardinality_optionality_and_identifying(
    rel: str, expected: tuple[str, str, str]
) -> None:
    for line in _edge_lines(render_erd(MODEL, RELATIONSHIPS)):
        if line[5] == rel:
            assert (line[1], line[2], line[3]) == expected


def test_self_reference_points_to_the_same_table() -> None:
    (line,) = [
        line for line in _edge_lines(render_erd(MODEL, RELATIONSHIPS)) if line[5] == "REL-03"
    ]
    assert line[0] == line[4] == "item_clsf"


def test_attribute_lines_use_korean_name_keys_and_physical_name() -> None:
    text = render_erd(MODEL, RELATIONSHIPS)
    assert '        varchar(20) 창고코드 PK "wrhus_cd"' in text
    assert '        varchar(20) 입고번호 PK,FK "wrhsg_no"' in text  # 식별 관계: 자식 PK에 부모 키
    assert '        varchar(20) 바코드 UK "brcd"' in text
    assert '        varchar(20) 품목코드 FK,UK "item_cd"' in text  # 1:1: 자식 FK가 유일
    assert '        timestamp(3) 입고일시 "wrhsg_dt"' in text


def test_overview_has_no_attributes() -> None:
    text = render_erd(MODEL, RELATIONSHIPS, attributes=False)
    assert "{\n" not in text and "PK" not in text
    assert '    wrhus["창고"]' in text.splitlines()
    assert len(_edge_lines(text)) == len(MODEL.foreign_keys)


# ── Mermaid 11.15.0 문법 (실측) ────────────────────────────


def test_numeric_scale_goes_to_the_comment_because_mermaid_rejects_commas_in_types() -> None:
    assert '        numeric 단가 "untprc · numeric(12,2)"' in render_erd(MODEL, RELATIONSHIPS)


def test_names_mermaid_cannot_parse_are_replaced_and_the_original_is_kept() -> None:
    text = render_erd(MODEL, RELATIONSHIPS)
    assert '        char(1) 입_출고구분 "io_se · 입·출고구분"' in text  # 가운뎃점
    assert '        integer _1차_단가 "frst_untprc · 1차 단가"' in text  # 숫자로 시작·공백


def _two_tables(first: str, second: str) -> NormalizedModel:
    """물리명만 바꿔 쓰는 테이블 둘: 둘째가 첫째를 부모로 가리킨다 (REL-01)."""
    return NormalizedModel.model_validate(
        {
            "pack": "inventory",
            "pack_version": "0.1.7",
            "rules_version": "normalize-v0",
            "lexicon_digest": "x",
            "tables": [
                _table("TBL-1", "첫째", first, [_col("C-1", "첫째코드", "frst_cd")], ["C-1"]),
                _table(
                    "TBL-2",
                    "둘째",
                    second,
                    [
                        _col("C-2", "둘째코드", "scnd_cd"),
                        _fk_col("C-2-1", "첫째코드", "frst_cd", "REL-01", "C-1"),
                    ],
                    ["C-2"],
                ),
            ],
            "foreign_keys": [_fk("FK-01", "REL-01", "TBL-2", ["C-2-1"], "TBL-1", ["C-1"])],
        }
    )


def _declared(text: str) -> dict[str, str]:
    """선언된 엔티티: 별칭 → 식별자."""
    return {alias: ident for ident, alias in re.findall(r'^    (\w+)\["([^"]*)"\]', text, re.M)}


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("t002", "1table"),  # 둘째의 대체 ID t002가 앞 테이블 물리명과 겹침 (#177 리뷰 재현)
        ("1table", "t001"),  # 첫째의 대체 ID t001이 뒤 테이블 물리명과 겹침
        ("item", "item"),  # 같은 물리명: 둘째는 대체 ID
        ("t002", "t002"),  # 같은 물리명이면서 대체 ID까지 겹침
    ],
)
def test_every_table_gets_its_own_identifier_and_edges_keep_their_tables(
    first: str, second: str
) -> None:
    rels = (_rel("REL-01", "ENT-1", "ENT-2"),)
    text = render_erd(_two_tables(first, second), rels)
    declared = _declared(text)
    assert len(set(declared.values())) == 2, text
    assert _edge_lines(text) == [(declared["첫째"], "||", "..", "o{", declared["둘째"], "REL-01")]


def test_a_usable_physical_name_is_kept_even_when_an_earlier_table_needs_a_replacement() -> None:
    """대체 ID 때문에 쓸 수 있는 물리명을 잃지 않는다."""
    rels = (_rel("REL-01", "ENT-1", "ENT-2"),)
    assert _declared(render_erd(_two_tables("1table", "t001"), rels))["둘째"] == "t001"


def test_aliases_and_comments_never_contain_double_quotes() -> None:
    model = MODEL.model_copy(
        update={
            "tables": (MODEL.tables[0].model_copy(update={"name": '품목"분류'}), *MODEL.tables[1:])
        }
    )
    assert '["품목\'분류"]' in render_erd(model, RELATIONSHIPS)


def test_same_input_same_text() -> None:
    assert render_erd(MODEL, RELATIONSHIPS) == render_erd(MODEL, RELATIONSHIPS)
    assert render_erd(MODEL, RELATIONSHIPS).startswith(
        "erDiagram\n    %% Specton ERD · inventory 0.1.7\n"
    )


# ── 실제 모델 정리 결과로 ──────────────────────────────────

PACK = "maintenance"


def test_renders_the_real_normalize_output() -> None:
    """실제 maintenance 팩 용어로 정리한 결과(#12 정리 코드)를 그대로 그린다."""
    key = {"data_type": "varchar", "is_key": True, "nullable": False, "req_ids": ["REQ-01"]}

    def entity(eid: str, name: str, *attrs: dict[str, Any]) -> Entity:
        return Entity.model_validate(
            {
                "id": eid,
                "pack": PACK,
                "name": name,
                "description": name,
                "attributes": attrs,
                "req_ids": ["REQ-01"],
            }
        )

    design = DesignState(
        run_id="run-1",
        versions=VersionInfo(
            pack_id=PACK,
            pack_version=str(read_yaml(DEFAULT_PACK_ROOT / PACK / "manifest.yaml")["version"]),
        ),
        requirements=[
            Requirement(
                id="REQ-01",
                source_ref={"file_format": "csv", "row": 2},
                text="한 접수는 한 설비에 대한 것이다.",
                draft_text="한 접수는 한 설비에 대한 것이다.",
                type="FR",
                analysis_version=1,
            )
        ],
        entities=[
            entity("ENT-eq", "설비", {"id": "ATTR-eq-cd", "name": "설비코드", "length": 10, **key}),
            entity(
                "ENT-rc",
                "고장접수",
                {"id": "ATTR-rc-no", "name": "고장접수번호", "length": 20, **key},
            ),
        ],
        relationships=[_rel("REL-01", "ENT-eq", "ENT-rc")],
    )
    result = normalize_from_state({"design": design})
    assert isinstance(result, Normalized), result
    text = render_erd(result.model, design.relationships)
    assert len(_edge_lines(text)) == len(result.model.foreign_keys) == 1
    assert ' 설비코드 PK "' in text and ' 설비코드 FK "' in text
