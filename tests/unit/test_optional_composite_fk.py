"""필수 품목 참조와 선택 로트 참조가 같은 업무 칼럼을 명시적으로 공유한다."""

from pathlib import Path

import pytest

from specton.codegen.model import Normalized, NormalizeFailed, ProblemCode
from specton.codegen.normalize import check_output
from specton.codegen.normalize_step import normalize_design
from specton.config import Settings
from specton.contracts import DesignState, RelationshipDraft
from specton.llm.errors import LLMContractError
from specton.llm.stub import reply, stub_client
from specton.nodes.a04_relationships import A04Output, run

FIXTURE = Path(__file__).parents[1] / "data/optional_composite_fk.json"


def state() -> DesignState:
    return DesignState.model_validate_json(FIXTURE.read_text())


def nullable(design: DesignState, attr_id: str, value: bool) -> DesignState:
    return design.evolve(
        entities=tuple(
            e.evolve(
                attributes=tuple(
                    a.evolve(nullable=value) if a.id == attr_id else a for a in e.attributes
                )
            )
            for e in design.entities
        )
    )


def drafts(design: DesignState) -> A04Output:
    entities = {e.id: e for e in design.entities}
    names = {a.id: a.name for e in design.entities for a in e.attributes}
    return A04Output(
        relationships=tuple(
            RelationshipDraft.model_validate(
                r.model_dump(exclude={"id", "parent", "child", "fk_bindings"})
                | {
                    "parent_name": entities[r.parent].name,
                    "child_name": entities[r.child].name,
                    "fk_bindings": [
                        {
                            "parent_attribute_name": names[b.parent_attribute_id],
                            "child_attribute_name": names[b.child_attribute_id],
                        }
                        for b in r.fk_bindings or ()
                    ],
                }
            )
            for r in design.relationships
        )
    )


def test_optional_composite_fk_preserves_required_shared_column() -> None:
    design = state()
    result = normalize_design(design)
    assert isinstance(result, Normalized), result
    child = next(t for t in result.model.tables if t.entity_id == "ENT-STOCK")
    columns = {c.attribute_id: c for c in child.columns}
    fks = {f.relationship_id: f for f in result.model.foreign_keys}
    assert len(child.columns) == 3
    assert not columns["ATTR-STOCK-ITEM"].nullable
    assert columns["ATTR-STOCK-LOT"].nullable
    assert fks["REL-01"].columns == (columns["ATTR-STOCK-ITEM"].id,)
    assert set(fks["REL-01"].columns) < set(fks["REL-02"].columns)
    assert not check_output(result.model, design)


@pytest.mark.parametrize(
    "attr_id,value,optional,target",
    [
        ("ATTR-STOCK-LOT", False, True, "REL-02"),
        ("ATTR-STOCK-ITEM", True, True, "REL-01"),
        ("ATTR-STOCK-LOT", True, False, "REL-02"),
    ],
)
def test_invalid_group_nullability_remains_blocked(
    attr_id: str, value: bool, optional: bool, target: str
) -> None:
    design = nullable(state(), attr_id, value)
    design = design.evolve(
        relationships=(design.relationships[0], design.relationships[1].evolve(optional=optional))
    )
    result = normalize_design(design)
    assert isinstance(result, NormalizeFailed)
    assert any(
        p.code is ProblemCode.INVALID_FK_BINDING and p.target == target for p in result.problems
    )


def test_unbound_composite_member_can_be_derived_nullable() -> None:
    design = state()
    design = design.evolve(
        entities=tuple(
            e.evolve(attributes=tuple(a for a in e.attributes if a.id != "ATTR-STOCK-LOT"))
            if e.id == "ENT-STOCK"
            else e
            for e in design.entities
        ),
        relationships=(
            design.relationships[0],
            design.relationships[1].evolve(fk_bindings=(design.relationships[1].fk_bindings[0],)),
        ),
    )
    result = normalize_design(design)
    assert isinstance(result, Normalized), result
    child = next(t for t in result.model.tables if t.entity_id == "ENT-STOCK")
    assert any(c.relationship_id == "REL-02" and c.nullable for c in child.columns)


@pytest.mark.parametrize("attr_id,value", [("ATTR-STOCK-LOT", False), ("ATTR-STOCK-ITEM", True)])
def test_output_guard_catches_changed_fk_nullability(attr_id: str, value: bool) -> None:
    design = state()
    result = normalize_design(design)
    assert isinstance(result, Normalized), result
    broken = result.model.evolve(
        tables=tuple(
            t.evolve(
                columns=tuple(
                    c.evolve(nullable=value) if c.attribute_id == attr_id else c for c in t.columns
                )
            )
            for t in result.model.tables
        )
    )
    assert any("NULL" in p.detail for p in check_output(broken, design))


def test_a04_accepts_shared_required_part_of_optional_composite() -> None:
    design = state()
    client, _ = stub_client(reply(drafts(design)))
    result = run(client, design, Settings(_env_file=None), pack="inventory")
    assert len(result.output) == 2
    assert result.output[1].fk_bindings == design.relationships[1].fk_bindings


def test_a04_rejects_optional_composite_without_a_nullable_member() -> None:
    design = nullable(state(), "ATTR-STOCK-LOT", False)
    client, _ = stub_client(reply(drafts(design)), max_structured_retries=0)
    with pytest.raises(LLMContractError):
        run(client, design, Settings(_env_file=None), pack="inventory")


@pytest.mark.parametrize("optional,nullable_lot", [(True, True), (False, False)])
def test_group_policy_keeps_both_optional_and_required_composites(
    optional: bool, nullable_lot: bool
) -> None:
    design = nullable(state(), "ATTR-STOCK-LOT", nullable_lot)
    design = design.evolve(
        relationships=(design.relationships[0], design.relationships[1].evolve(optional=optional))
    )
    result = normalize_design(design)
    assert isinstance(result, Normalized), result


def test_a04_preserves_partial_binding_with_a_derived_nullable_member() -> None:
    design = state()
    bindings = design.relationships[1].fk_bindings
    assert bindings is not None
    design = design.evolve(
        entities=tuple(
            e.evolve(attributes=tuple(a for a in e.attributes if a.id != "ATTR-STOCK-LOT"))
            if e.id == "ENT-STOCK"
            else e
            for e in design.entities
        ),
        relationships=(
            design.relationships[0],
            design.relationships[1].evolve(fk_bindings=bindings[:1]),
        ),
    )
    client, _ = stub_client(reply(drafts(design)))
    result = run(client, design, Settings(_env_file=None), pack="inventory")
    assert result.output[1].fk_bindings == design.relationships[1].fk_bindings


def test_inherited_parent_key_is_deferred_then_checked_as_complete_fk() -> None:
    design = state()
    warehouse, lot, stock = design.entities
    warehouse = warehouse.evolve(
        name="창고", attributes=(warehouse.attributes[0].evolve(name="창고코드"),)
    )
    lot = lot.evolve(attributes=(lot.attributes[1],))
    stock = stock.evolve(
        attributes=(stock.attributes[0], stock.attributes[2].evolve(nullable=False))
    )
    parent = design.relationships[0].evolve(child=lot.id, identifying=True, fk_bindings=None)
    optional = design.relationships[1]
    assert optional.fk_bindings is not None
    optional = optional.evolve(fk_bindings=optional.fk_bindings[1:])
    design = design.evolve(entities=(warehouse, lot, stock), relationships=(parent, optional))
    client, _ = stub_client(reply(drafts(design)))
    a04 = run(client, design, Settings(_env_file=None), pack="inventory")
    result = normalize_design(design.evolve(relationships=a04.output))
    assert isinstance(result, Normalized), result
    child = next(t for t in result.model.tables if t.entity_id == stock.id)
    assert any(c.relationship_id == "REL-02" and c.nullable for c in child.columns)
    assert any(c.attribute_id == "ATTR-STOCK-LOT" and not c.nullable for c in child.columns)
