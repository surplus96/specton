"""REQ-16: 재작업 판단 (target_stage 분기, A09 호출 조건, 상한·반복 지적)."""

import pytest

from specton.contracts import Finding
from specton.review.rework import (
    HitlReason,
    ReworkAction,
    ReworkDecision,
    decide_rework,
    earliest_stage,
    resolve_with_router,
)

MAX_REWORK = 3


def _finding(
    number: int, *, severity: str = "major", stage: str | None = "data_model", fingerprint: str = ""
) -> Finding:
    return Finding(
        id=f"A05-0-{number}",
        source="llm",
        reviewer_id="A05",
        kind="cardinality_conflict",
        severity=severity,
        targets=[{"kind": "relationship", "id": f"REL-{number:02d}"}],
        evidence=[{"req_id": "REQ-01", "quote": "최대 하나"}],
        suggestion="1:N으로 바꾼다",
        target_stage=stage,
        fingerprint=fingerprint or f"fp-{number}",
        iteration=0,
    )


def _decide(
    findings: list[Finding], *, count: int = 0, previous: frozenset[str] = frozenset()
) -> ReworkDecision:
    return decide_rework(
        findings, rework_count=count, max_rework=MAX_REWORK, previous_fingerprints=previous
    )


def test_no_findings_means_no_rework() -> None:
    assert _decide([]).action is ReworkAction.NONE


def test_minor_findings_do_not_trigger_rework() -> None:
    decision = _decide([_finding(1, severity="minor", stage=None)])

    assert decision.action is ReworkAction.NONE


def test_clear_stage_reworks_without_the_router() -> None:
    decision = _decide([_finding(1, stage="functions")])

    assert (decision.action, decision.target_stage) == (ReworkAction.REWORK, "functions")
    assert decision.unrouted == ()


def test_mixed_stages_go_back_to_the_earliest() -> None:
    decision = _decide([_finding(1, stage="data_model"), _finding(2, stage="requirements")])

    assert decision.target_stage == "requirements"


def test_finding_without_stage_asks_the_router() -> None:
    routed, unrouted = _finding(1, stage="data_model"), _finding(2, stage=None)

    decision = _decide([routed, unrouted])

    assert decision.action is ReworkAction.ASK_ROUTER
    assert decision.unrouted == (unrouted,)
    assert decision.target_stage == "data_model"


def test_rework_limit_stops_the_loop() -> None:
    decision = _decide([_finding(1)], count=MAX_REWORK)

    assert (decision.action, decision.hitl_reason) == (ReworkAction.HITL, HitlReason.LIMIT)


def test_repeated_finding_stops_the_loop() -> None:
    decision = _decide([_finding(1, fingerprint="same")], count=1, previous=frozenset({"same"}))

    assert (decision.action, decision.hitl_reason) == (ReworkAction.HITL, HitlReason.REPEATED)


def test_minor_repeat_does_not_stop_the_loop() -> None:
    findings = [_finding(1, severity="minor", fingerprint="same"), _finding(2, stage="functions")]

    decision = _decide(findings, count=1, previous=frozenset({"same"}))

    assert (decision.action, decision.target_stage) == (ReworkAction.REWORK, "functions")


@pytest.mark.parametrize(
    ("known", "router", "expected"),
    [("data_model", "requirements", "requirements"), (None, "functions", "functions")],
)
def test_router_answer_is_merged_with_known_stages(
    known: str | None, router: str, expected: str
) -> None:
    findings = [_finding(2, stage=None)] + ([_finding(1, stage=known)] if known else [])
    decision = _decide(findings)

    resolved = resolve_with_router(decision, router)

    assert (resolved.action, resolved.target_stage) == (ReworkAction.REWORK, expected)


def test_router_without_answer_goes_to_hitl() -> None:
    decision = _decide([_finding(1, stage=None)])

    resolved = resolve_with_router(decision, None)

    assert (resolved.action, resolved.hitl_reason) == (ReworkAction.HITL, HitlReason.UNDECIDED)


def test_router_answer_requires_a_router_decision() -> None:
    with pytest.raises(ValueError):
        resolve_with_router(_decide([_finding(1)]), "functions")


def test_earliest_stage_orders_by_rerun_scope() -> None:
    assert earliest_stage(["data_model", "functions"]) == "functions"
