"""체크포인트 직렬화기는 등록한 타입만 다시 읽는다 (#131, ADR-0012)."""

from collections.abc import Iterator
from enum import StrEnum

import pytest
from langgraph.checkpoint.serde.event_hooks import SerdeEvent, register_serde_event_listener

from specton.contracts import (
    VALIDATION_STEPS,
    Column,
    DesignState,
    NormalizedModel,
    SqlValidation,
    Table,
    ValidationIssue,
    ValidationStep,
)
from specton.contracts.base import TargetStage
from specton.contracts.findings import Finding
from specton.persistence.db import CHECKPOINT_TYPES, GRAPH_STATE_TYPES, checkpoint_serde
from specton.review.rework import HitlReason


@pytest.fixture
def events() -> Iterator[list[SerdeEvent]]:
    seen: list[SerdeEvent] = []
    unregister = register_serde_event_listener(seen.append)
    yield seen
    unregister()


class _Unlisted(StrEnum):
    """목록에 없는 타입."""

    VALUE = "value"


def test_graph_state_values_come_back_without_warnings(events: list[SerdeEvent]) -> None:
    serde = checkpoint_serde()
    value = {
        "design": DesignState(run_id="run-1"),
        "stage": TargetStage.DATA_MODEL,
        "reason": HitlReason.LIMIT,
    }

    restored = serde.loads_typed(serde.dumps_typed(value))

    assert restored == value
    assert type(restored["design"]) is DesignState
    assert events == []


def test_design_with_a_normalized_model_comes_back_without_warnings(
    events: list[SerdeEvent],
) -> None:
    """모델 정리 결과를 담은 상태도 허용 목록으로 다시 읽힌다 (#142)."""
    serde = checkpoint_serde()
    design = DesignState(run_id="run-1", normalized=_normalized())

    restored = serde.loads_typed(serde.dumps_typed(design))

    assert restored == design
    assert type(restored.normalized) is NormalizedModel
    assert events == []


def test_sql_validation_comes_back_without_warnings(events: list[SerdeEvent]) -> None:
    """실행기가 체크포인트에 담는 검증 결과도 허용 목록으로 다시 읽힌다 (#175)."""
    serde = checkpoint_serde()
    issue = ValidationIssue(code="syntax_error", statement_index=0, sqlstate="42601")
    steps = (
        ValidationStep(name=VALIDATION_STEPS[0], status="failed", issues=(issue,)),
        *(ValidationStep(name=name, status="not_run") for name in VALIDATION_STEPS[1:]),
    )
    validation = SqlValidation(
        status="failed", artifact_hash="0" * 64, validator_version="v1", policy_version="p1",
        postgres_version="18", steps=steps,
    )

    restored = serde.loads_typed(serde.dumps_typed({"validation": validation}))

    assert restored == {"validation": validation}
    assert type(restored["validation"].steps[0].issues[0]) is ValidationIssue
    assert events == []


def test_unlisted_type_is_blocked(events: list[SerdeEvent]) -> None:
    serde = checkpoint_serde()

    restored = serde.loads_typed(serde.dumps_typed(_Unlisted.VALUE))

    assert not isinstance(restored, _Unlisted)
    assert [e["kind"] for e in events] == ["msgpack_blocked"]


def test_every_contract_and_graph_state_type_is_listed() -> None:
    assert ("specton.contracts.state", "DesignState") in CHECKPOINT_TYPES
    assert (Finding.__module__, Finding.__name__) in CHECKPOINT_TYPES
    assert GRAPH_STATE_TYPES <= CHECKPOINT_TYPES
    assert all(module.startswith("specton.") for module, _ in CHECKPOINT_TYPES)
    assert ("specton.contracts.normalized", "NormalizedModel") in CHECKPOINT_TYPES
    assert ("specton.contracts.validation", "SqlValidation") in CHECKPOINT_TYPES


def _normalized(physical_name: str = "ord") -> NormalizedModel:
    """테이블 1개·컬럼 1개(PK)인 정리 결과."""
    column = Column(
        id="COL-1", name="주문번호", physical_name="ord_no", data_type="varchar", length=20,
        precision=None, scale=None, time_precision=None, domain=None, nullable=False,
        req_ids=("REQ-01",), attribute_id="ATTR-01",
    )  # fmt: skip
    table = Table(
        id="TBL-1", name="주문", physical_name=physical_name, columns=(column,),
        primary_key=("COL-1",), unique_keys=(), req_ids=("REQ-01",), entity_id="ENT-01",
    )  # fmt: skip
    return NormalizedModel(
        pack="inventory", pack_version="0.1.0", rules_version="normalize-v0",
        lexicon_digest="d", tables=(table,), foreign_keys=(),
    )  # fmt: skip
