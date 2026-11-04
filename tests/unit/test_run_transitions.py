"""run 상태 전이 검사 (03 문서 상태도)와 실행기 설정값 (ADR-0012)."""

import pytest

from specton.config import Settings
from specton.contracts import RunState as S
from specton.persistence.runs import can_transition


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (S.QUEUED, S.PARSING),
        (S.PARSING, S.ANALYSING),
        (S.REVIEWING, S.DESIGNING),
        (S.REVIEWING, S.ANALYSING),  # 요구사항 단계 재작업 (#111)
        (S.DESIGNING, S.ANALYSING),  # HITL 2 수정 요청 뒤 요구사항 단계로
        (S.DESIGNING, S.AWAITING_REVIEW),  # HITL 2 수정 요청을 A09가 판단하지 못함 (#114)
        (S.AWAITING_REVIEW, S.EXPORTING),
        (S.DESIGNING, S.DESIGNING),
        (S.GENERATING, S.FAILED),
        (S.ANALYSING, S.CANCEL_REQUESTED),
        (S.CANCEL_REQUESTED, S.CANCELLED),
    ],
)
def test_allows_flow_in_the_state_diagram(current: S, new: S) -> None:
    assert can_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (S.QUEUED, S.DESIGNING),
        (S.ANALYSING, S.DESIGNING),  # ADR-0015(#95) 승인 전
        (S.CANCEL_REQUESTED, S.DESIGNING),
        (S.CANCEL_REQUESTED, S.CANCEL_REQUESTED),
        (S.COMPLETED, S.FAILED),
        (S.CANCELLED, S.CANCELLED),
    ],
)
def test_rejects_other_transitions(current: S, new: S) -> None:
    assert not can_transition(current, new)


def test_runner_defaults_follow_adr_0012() -> None:
    settings = Settings(_env_file=None)

    assert (settings.run_concurrency, settings.lease_seconds, settings.lease_renew_seconds) == (
        2,
        60,
        20,
    )


def test_lease_must_be_renewed_before_it_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTON_LEASE_RENEW_SECONDS", "60")

    with pytest.raises(ValueError, match="갱신 주기"):
        Settings(_env_file=None)


def test_pool_must_fit_runs_lease_renewal_and_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTON_RUN_CONCURRENCY", "4")
    monkeypatch.setenv("SPECTON_DB_POOL_SIZE", "5")

    with pytest.raises(ValueError, match="연결 풀"):
        Settings(_env_file=None)
