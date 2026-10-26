import pytest
from pydantic import ValidationError

from specton.contracts import (
    Attribute,
    AttributeDraft,
    DesignState,
    Entity,
    EntityOp,
    Finding,
    FindingDraft,
    Function,
    FunctionDraft,
    Relationship,
    Requirement,
    SourceRef,
    find_trace_issues,
)
from specton.contracts.base import RequirementType


def _src() -> SourceRef:
    return SourceRef(kind="xlsx", sheet="요구사항", row=5)


def _req(req_id: str = "REQ-01") -> Requirement:
    return Requirement(
        id=req_id,
        source_id="SFR-001",
        source_ref=_src(),
        text="주문을 취소할 수 있다",
        original_text="주문을 취소할 수 있다",
        type=RequirementType.FR,
        analysis_version=1,
    )


def _attr(attr_id: str = "ATTR-01", req_ids: list[str] | None = None) -> Attribute:
    return Attribute(
        id=attr_id,
        name="주문번호",
        data_type="varchar",
        length=20,
        is_key=True,
        nullable=False,
        req_ids=req_ids or ["REQ-01"],
    )


def _entity(entity_id: str = "ENT-01", req_ids: list[str] | None = None) -> Entity:
    return Entity(
        id=entity_id,
        pack="inventory",
        name="주문",
        description="고객 주문",
        attributes=[_attr()],
        req_ids=req_ids or ["REQ-01"],
    )


def _function(function_id: str = "FUNC-01", req_ids: list[str] | None = None) -> Function:
    return Function(
        id=function_id,
        name="주문 취소",
        description="주문을 취소한다",
        req_ids=req_ids or ["REQ-01"],
    )


def _state(**overrides: object) -> DesignState:
    base: dict[str, object] = {
        "run_id": "run-1",
        "requirements": [_req()],
        "functions": [_function()],
        "entities": [_entity()],
    }
    return DesignState.model_validate({**base, **overrides})


class TestImmutability:
    def test_fields_cannot_be_reassigned(self) -> None:
        state = _state()

        with pytest.raises(ValidationError):
            state.revision = 99  # type: ignore[misc]

    def test_collections_are_tuples(self) -> None:
        state = _state()

        assert isinstance(state.requirements, tuple)
        assert isinstance(state.functions[0].req_ids, tuple)
        assert isinstance(state.entities[0].attributes, tuple)

    def test_update_returns_a_new_object(self) -> None:
        state = _state()

        updated = state.model_copy(update={"revision": 1})

        assert (state.revision, updated.revision) == (0, 1)


class TestSourceRef:
    def test_each_kind_requires_its_locator(self) -> None:
        assert SourceRef(kind="csv", row=3).display() == "3행"
        assert SourceRef(kind="pdf", page=2, block=0).display() == "2쪽 블록0"
        hwpx = SourceRef(kind="hwpx", section=0, paragraph=4, table=1, cell="2행1열")
        assert hwpx.display() == "구역0 문단4 표1 2행1열"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"kind": "xlsx", "row": 1},
            {"kind": "pdf", "page": 1},
            {"kind": "hwpx", "section": 0},
            {"kind": "hwpx", "section": 0, "paragraph": 1, "table": 1},
            {"kind": "csv", "row": 0},
        ],
    )
    def test_incomplete_locator_is_rejected(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            SourceRef.model_validate(kwargs)

    def test_round_trips_through_json(self) -> None:
        ref = _src()
        assert SourceRef.model_validate_json(ref.model_dump_json()) == ref


class TestPriority:
    def test_null_priority_must_be_unspecified(self) -> None:
        func = FunctionDraft(name="a", description="b", req_ids=["REQ-01"])
        assert func.priority is None
        assert func.priority_source == "unspecified"

    def test_inferred_value_keeps_its_source(self) -> None:
        func = FunctionDraft(
            name="a",
            description="b",
            req_ids=["REQ-01"],
            priority="Must",
            priority_source="inferred",
        )
        assert func.priority_source == "inferred"

    @pytest.mark.parametrize(
        "extra",
        [
            {"priority": "Must"},  # 값이 있는데 출처가 unspecified
            {"priority": None, "priority_source": "inferred"},
            {"priority": "Unknown", "priority_source": "inferred"},  # 임의 문자열
        ],
    )
    def test_inconsistent_priority_is_rejected(self, extra: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            FunctionDraft.model_validate(
                {"name": "a", "description": "b", "req_ids": ["REQ-01"], **extra}
            )


class TestLlmOutputBoundary:
    def test_draft_rejects_code_filled_fields(self) -> None:
        with pytest.raises(ValidationError):
            FunctionDraft.model_validate(
                {"id": "FUNC-99", "name": "a", "description": "b", "req_ids": ["REQ-01"]}
            )

    def test_finding_draft_rejects_fingerprint(self) -> None:
        with pytest.raises(ValidationError):
            FindingDraft.model_validate(
                {
                    "kind": "missing",
                    "severity": "major",
                    "targets": [{"kind": "entity", "id": "ENT-01"}],
                    "evidence": [{"quote": "x"}],
                    "suggestion": "y",
                    "fingerprint": "abc",
                }
            )

    def test_llm_output_must_not_invent_unknown_sql_type(self) -> None:
        with pytest.raises(ValidationError):
            AttributeDraft(name="x", data_type="jsonb", req_ids=["REQ-01"])

    def test_llm_output_cannot_carry_free_sql_check(self) -> None:
        with pytest.raises(ValidationError):
            AttributeDraft(
                name="qty",
                data_type="integer",
                req_ids=["REQ-01"],
                check="qty > 0; DROP TABLE item",
            )

    def test_req_ids_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            FunctionDraft(name="a", description="b", req_ids=[])

    def test_req_id_format_is_enforced(self) -> None:
        with pytest.raises(ValidationError):
            FunctionDraft(name="a", description="b", req_ids=["SFR-001"])


class TestAttribute:
    def test_varchar_requires_length(self) -> None:
        with pytest.raises(ValidationError):
            AttributeDraft(name="x", data_type="varchar", req_ids=["REQ-01"])

    def test_numeric_scale_cannot_exceed_precision(self) -> None:
        with pytest.raises(ValidationError):
            AttributeDraft(name="x", data_type="numeric", precision=5, scale=6, req_ids=["REQ-01"])

    def test_key_cannot_be_nullable(self) -> None:
        with pytest.raises(ValidationError):
            AttributeDraft(
                name="x", data_type="integer", is_key=True, nullable=True, req_ids=["REQ-01"]
            )


class TestFinding:
    def _draft(self) -> dict[str, object]:
        return {
            "kind": "missing",
            "severity": "major",
            "targets": [{"kind": "entity", "id": "ENT-01"}],
            "evidence": [{"req_id": "REQ-01", "quote": "주문을 취소할 수 있다"}],
            "suggestion": "취소 사유를 저장한다",
            "target_stage": "data_model",
        }

    def test_rule_finding_carries_rule_code(self) -> None:
        finding = Finding.model_validate(
            {
                **self._draft(),
                "id": "F-1",
                "source": "rule",
                "rule_code": "RULE-01",
                "fingerprint": "abc",
                "iteration": 0,
            }
        )
        assert finding.reviewer_id is None

    def test_llm_finding_needs_reviewer_not_rule_code(self) -> None:
        base = {**self._draft(), "id": "F-1", "fingerprint": "abc", "iteration": 1}
        Finding.model_validate({**base, "source": "llm", "reviewer_id": "A06"})
        with pytest.raises(ValidationError):
            Finding.model_validate({**base, "source": "llm"})
        with pytest.raises(ValidationError):
            Finding.model_validate(
                {**base, "source": "llm", "reviewer_id": "A06", "rule_code": "x"}
            )

    def test_relationship_stage_has_no_standalone_value(self) -> None:
        with pytest.raises(ValidationError):
            FindingDraft.model_validate({**self._draft(), "target_stage": "relationships"})


class TestTraceIntegrity:
    """TC-N01: 누락·없는 REQ 참조를 주입하면 모두 검출한다."""

    def test_clean_state_has_no_issues(self) -> None:
        assert find_trace_issues(_state()) == []

    def test_unknown_req_ids_are_found_for_every_element_kind(self) -> None:
        relationship = Relationship(
            id="REL-01",
            parent="ENT-01",
            child="ENT-01",
            cardinality="1:N",
            optional=False,
            rationale="자기참조",
            req_ids=["REQ-99"],
        )
        state = _state(
            functions=[_function(req_ids=["REQ-98"])],
            entities=[
                Entity(
                    id="ENT-01",
                    pack="inventory",
                    name="주문",
                    description="d",
                    attributes=[_attr(req_ids=["REQ-97"])],
                    req_ids=["REQ-96"],
                )
            ],
            relationships=[relationship],
        )

        issues = find_trace_issues(state)

        assert {(i.object_kind, i.kind) for i in issues} == {
            ("function", "unknown_req_id"),
            ("entity", "unknown_req_id"),
            ("attribute", "unknown_req_id"),
            ("relationship", "unknown_req_id"),
        }

    def test_empty_req_ids_that_bypass_validation_are_found(self) -> None:
        function = Function.model_construct(
            id="FUNC-01", name="a", description="b", req_ids=[], entity_ops=[]
        )
        state = _state().model_copy(update={"functions": (function,)})

        issues = find_trace_issues(state)

        assert [(i.kind, i.object_id) for i in issues] == [("missing_req_ids", "FUNC-01")]

    def test_dangling_entity_references_are_found(self) -> None:
        dangling_op = EntityOp(entity_id="ENT-404", operations=["C"])
        function = _function().model_copy(update={"entity_ops": (dangling_op,)})
        relationship = Relationship(
            id="REL-01",
            parent="ENT-01",
            child="ENT-405",
            cardinality="1:N",
            optional=True,
            rationale="r",
            req_ids=["REQ-01"],
        )
        state = _state(functions=[function], relationships=[relationship])

        issues = find_trace_issues(state)

        assert [i.kind for i in issues] == ["unknown_entity_ref", "unknown_entity_ref"]

    def test_duplicate_ids_are_found(self) -> None:
        state = _state(functions=[_function(), _function()])
        assert [i.kind for i in find_trace_issues(state)] == ["duplicate_id"]
