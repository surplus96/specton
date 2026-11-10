"""#290: 복합 업무 유일성·명시적 FK 재사용. 평가 자료와 무관한 합성 설계다."""

import hashlib
import json

import pytest
from pydantic import ValidationError
from test_normalize import LEXICON, PACK, RULES, WAREHOUSE, _attr, _design, _entity, _rel

from specton.codegen.model import Normalized, NormalizeFailed, ProblemCode
from specton.codegen.normalize import check_output, normalize
from specton.contracts import DesignState, EntityDraft
from specton.model_hash import MODEL_FIELDS, model_hash, model_payload
from specton.nodes.a03_entities import _with_ids


def business_design(*, identifying: bool = False) -> DesignState:
    child = _entity(
        "ENT-rc",
        "입고",
        _attr("ATTR-no", "입고번호", is_key=True),
        _attr("ATTR-wh", "창고코드", nullable=False, is_key=identifying),
        _attr("ATTR-seq", "내역순번", nullable=False),
    ).evolve(unique_keys=(("ATTR-wh", "ATTR-seq"),))
    relation = _rel("REL-01", "ENT-wh", "ENT-rc", identifying=identifying).evolve(
        fk_bindings=({"parent_attribute_id": "ATTR-wh-cd", "child_attribute_id": "ATTR-wh"},)
    )
    return _design([WAREHOUSE, child], [relation])


def test_surrogate_key_keeps_composite_business_unique_and_explicit_fk() -> None:
    design = business_design()
    result = normalize(design, pack=PACK, lexicon=LEXICON, rules=RULES)
    assert isinstance(result, Normalized), result
    assert not check_output(result.model, design)
    table = next(t for t in result.model.tables if t.entity_id == "ENT-rc")
    columns = {c.attribute_id: c for c in table.columns}
    assert len(columns) == 3
    assert table.primary_key == (columns["ATTR-no"].id,)
    assert (columns["ATTR-wh"].id, columns["ATTR-seq"].id) in table.unique_keys
    assert all((columns[a].id,) not in table.unique_keys for a in ("ATTR-wh", "ATTR-seq"))
    assert result.model.foreign_keys[0].columns == (columns["ATTR-wh"].id,)
    assert columns["ATTR-wh"].relationship_id is None  # 원래 속성 출처를 보존


def test_identifying_reuse_does_not_duplicate_own_primary_key_column() -> None:
    result = normalize(business_design(identifying=True), pack=PACK, lexicon=LEXICON, rules=RULES)
    assert isinstance(result, Normalized), result
    child = next(t for t in result.model.tables if t.entity_id == "ENT-rc")
    assert len(child.primary_key) == len(set(child.primary_key)) == 2


def test_output_guard_detects_dropped_business_unique() -> None:
    design = business_design()
    result = normalize(design, pack=PACK, lexicon=LEXICON, rules=RULES)
    assert isinstance(result, Normalized)
    broken = result.model.evolve(
        tables=tuple(
            t.evolve(unique_keys=()) if t.entity_id == "ENT-rc" else t for t in result.model.tables
        )
    )
    assert any("UNIQUE" in p.detail for p in check_output(broken, design))


def test_explicit_reuse_rejects_different_sql_length() -> None:
    design = business_design()
    parent, child = design.entities
    child = child.evolve(
        attributes=tuple(a.evolve(length=11) if a.id == "ATTR-wh" else a for a in child.attributes)
    )
    result = normalize(
        design.evolve(entities=(parent, child)), pack=PACK, lexicon=LEXICON, rules=RULES
    )
    assert isinstance(result, NormalizeFailed)
    assert ProblemCode.INVALID_FK_BINDING in {p.code for p in result.problems}
    from specton.contracts import Severity
    from specton.review.normalization_findings import map_normalization_failure

    repaired_input = design.evolve(
        entities=(parent, child), versions={"pack_id": PACK.name, "pack_version": PACK.version}
    )
    review = map_normalization_failure(
        repaired_input, result.problems, severities={"RULE-04": Severity.CRITICAL}
    )
    assert not review["requires_manual_review"]
    assert all(
        f.rule_code == "RULE-04" and f.target_stage == "data_model" for f in review["findings"]
    )


@pytest.mark.parametrize(
    "change",
    [
        {"fk_bindings": None},
        {"fk_bindings": ({"parent_attribute_id": "ATTR-wh-nm", "child_attribute_id": "ATTR-wh"},)},
        {"optional": True},
    ],
)
def test_no_implicit_reuse_or_invalid_key_null_binding(change: dict[str, object]) -> None:
    state = business_design()
    state = state.evolve(relationships=(state.relationships[0].evolve(**change),))
    result = normalize(state, pack=PACK, lexicon=LEXICON, rules=RULES)
    assert isinstance(result, NormalizeFailed)
    expected = (
        ProblemCode.FK_COLUMN_CONFLICT
        if change.get("fk_bindings", ()) is None
        else (ProblemCode.INVALID_FK_BINDING)
    )
    assert expected in {p.code for p in result.problems}


def test_draft_unique_attribute_names_are_converted_to_ids_by_code() -> None:
    entity = business_design().entities[1]
    data = entity.model_dump(exclude={"id", "pack", "unique_keys"})
    data["attributes"] = [a.model_dump(exclude={"id"}) for a in entity.attributes]
    data["unique_keys"] = (("창고코드", "내역순번"),)
    draft = EntityDraft.model_validate(data)
    (saved,) = _with_ids((draft,), "inventory")
    ids = {a.name: a.id for a in saved.attributes}
    assert saved.unique_keys == ((ids["창고코드"], ids["내역순번"]),)
    with pytest.raises(ValidationError, match="UNIQUE"):
        draft.evolve(unique_keys=(("없는 속성",),))


def test_absent_new_fields_keep_legacy_payload_hash_and_new_declarations_change_it() -> None:
    original = business_design()
    legacy = original.evolve(
        entities=tuple(e.evolve(unique_keys=None) for e in original.entities),
        relationships=tuple(r.evolve(fk_bindings=None) for r in original.relationships),
    )
    old = {
        name: [
            i.model_dump(mode="json", exclude={"unique_keys", "fk_bindings"})
            for i in getattr(legacy, name)
        ]
        for name in MODEL_FIELDS
    }
    expected = hashlib.sha256(
        json.dumps(old, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert model_payload(legacy) == old
    assert model_hash(legacy) == expected
    assert model_hash(original) != expected
