"""체크포인트 직렬화기는 등록한 타입만 다시 읽는다 (#131, ADR-0012)."""

from collections.abc import Iterator
from enum import StrEnum

import pytest
from langgraph.checkpoint.serde.event_hooks import SerdeEvent, register_serde_event_listener

from specton.contracts import DesignState
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
