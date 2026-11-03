"""실행 제어 API (06 문서): 등록·조회·재개·취소·SSE·오류 형식. 로컬 DB가 필요하다.

실행기(#17)는 없으므로, 실행기가 할 진행 기록은 저장 함수로 직접 만든다.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from specton.api.main import create_app
from specton.api.session import SESSION_COOKIE
from specton.config import Settings
from specton.contracts import Interrupt, SseEventType
from specton.contracts import RunState as S
from specton.persistence import lease
from specton.persistence.db import Pool
from specton.persistence.runs import NewEvent, record_progress

pytestmark = pytest.mark.db

XLSX = ("req.xlsx", b"PK\x03\x04 fake workbook", "application/octet-stream")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, storage_dir=tmp_path / "storage", sse_poll_seconds=0.01)


@pytest.fixture
def client(settings: Settings, pool: Pool) -> Iterator[TestClient]:
    with TestClient(create_app(settings, pool)) as c:
        yield c


def _other(settings: Settings, pool: Pool) -> TestClient:
    """다른 세션(다른 owner_ref)의 클라이언트."""
    return TestClient(create_app(settings, pool))


def _create(client: TestClient, file: tuple[str, bytes, str] = XLSX, pack: str = "inventory"):  # type: ignore[no-untyped-def]
    return client.post("/runs", files={"file": file}, data={"pack": pack})


def _owner(client: TestClient) -> str:
    return client.cookies[SESSION_COOKIE]


# 사람 확인 대기 상태까지 실행기가 지나가는 상태들 (03 문서 상태도)
_PATH = {
    S.AWAITING_INPUT: [S.PARSING],
    S.AWAITING_REQUIREMENTS: [S.PARSING, S.ANALYSING],
    S.AWAITING_REVIEW: [
        S.PARSING,
        S.ANALYSING,
        S.AWAITING_REQUIREMENTS,
        S.DESIGNING,
        S.GENERATING,
        S.REVIEWING,
    ],
}


def _wait(pool: Pool, run_id: str, kind: str, state: S) -> str:
    """실행기가 run을 사람 확인 대기로 만들고 lease를 반납한 상태. interrupt_id를 돌려준다."""
    ask = Interrupt(interrupt_id=f"int-{kind}", kind=kind, message="확인 필요")  # type: ignore[arg-type]
    with pool.connection() as conn:
        assert lease.acquire(conn, UUID(run_id), "w1", 60)
        for i, step in enumerate(_PATH[state]):
            # 지나간 확인 요청은 바로 답한 것으로 본다 (이 테스트의 대상이 아님)
            passed = Interrupt(interrupt_id=f"int-{i}", kind="requirements", message="이전 확인")
            waiting = passed if step in lease.WAITING_STATES else None
            record_progress(
                conn, run_id, "w1", f"cp-{i}", status=step, revision=0, interrupt=waiting
            )
        event = NewEvent(SseEventType.INTERRUPT, "확인 필요", payload={"id": ask.interrupt_id})
        record_progress(
            conn, run_id, "w1", "cp-wait", status=state, revision=0, interrupt=ask, events=[event]
        )
        lease.release(conn, UUID(run_id), "w1")
    return ask.interrupt_id


def _error(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


# 등록 (POST /runs)


def test_create_returns_queued_run_and_issues_a_session(
    client: TestClient, settings: Settings
) -> None:
    response = _create(client)

    assert response.status_code == 202
    body = response.json()
    assert (body["status"], body["revision"]) == ("queued", 0)
    assert SESSION_COOKIE in response.cookies
    stored = list((settings.storage_dir / body["run_id"]).iterdir())
    assert [p.suffix for p in stored] == [".xlsx"]
    assert "req.xlsx" not in str(stored[0])  # 사용자 파일명을 경로로 쓰지 않는다


@pytest.mark.parametrize(
    ("name", "expected"),
    [("req.hwp", "HWPX"), ("req.pdf", ".xlsx"), ("req.docx", ".xlsx")],
)
def test_unsupported_formats_are_415(client: TestClient, name: str, expected: str) -> None:
    response = _create(client, (name, b"data", "application/octet-stream"))

    assert _error(response) == (415, "UNSUPPORTED_MEDIA_TYPE")
    assert expected in response.json()["message"]


def test_unknown_pack_is_422(client: TestClient) -> None:
    assert _error(_create(client, pack="finance")) == (422, "PACK_UNSUPPORTED")


def test_too_large_upload_is_413_and_leaves_no_file(settings: Settings, pool: Pool) -> None:
    small = settings.model_copy(update={"max_upload_mb": 1})
    with TestClient(create_app(small, pool)) as client:
        response = _create(client, ("big.csv", b"a," * (600 * 1024), "text/csv"))

    assert _error(response) == (413, "UPLOAD_TOO_LARGE")
    assert not any(settings.storage_dir.rglob("*.csv"))


def test_missing_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/runs", data={"pack": "inventory"})

    assert _error(response) == (422, "INVALID_REQUEST")
    assert response.json()["retryable"] is False


# 조회·소유자 (ADR-0011)


def test_runs_are_visible_only_to_their_owner(
    client: TestClient, settings: Settings, pool: Pool
) -> None:
    run_id = _create(client).json()["run_id"]
    other = _other(settings, pool)

    assert client.get(f"/runs/{run_id}").json()["status"] == "queued"
    assert [r["run_id"] for r in client.get("/runs").json()] == [run_id]
    assert _error(other.get(f"/runs/{run_id}")) == (404, "RUN_NOT_FOUND")
    assert other.get("/runs").json() == []
    assert _error(other.post(f"/runs/{run_id}/cancel", json={"expected_revision": 0})) == (
        404,
        "RUN_NOT_FOUND",
    )


def test_unknown_run_is_404_with_run_id(client: TestClient) -> None:
    run_id = str(uuid4())
    response = client.get(f"/runs/{run_id}")

    assert _error(response) == (404, "RUN_NOT_FOUND")
    assert response.json()["run_id"] == run_id


def test_list_checks_query(client: TestClient) -> None:
    assert _error(client.get("/runs", params={"limit": 0})) == (422, "INVALID_REQUEST")
    assert _error(client.get("/runs", params={"status": "nope"})) == (422, "INVALID_REQUEST")


def test_status_shows_stage_interrupt_and_error(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "requirements", S.AWAITING_REQUIREMENTS)

    body = client.get(f"/runs/{run_id}").json()

    assert body["status"] == "awaiting_requirements"
    assert body["interrupt"]["interrupt_id"] == interrupt_id
    assert body["error"] is None


# 취소 (ADR-0012)


def test_cancel_queued_run_finishes_immediately(client: TestClient) -> None:
    run_id = _create(client).json()["run_id"]

    response = client.post(f"/runs/{run_id}/cancel", json={"expected_revision": 0})

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    assert _error(client.post(f"/runs/{run_id}/cancel", json={"expected_revision": 0})) == (
        409,
        "RUN_REVISION_CONFLICT",
    )


def test_cancel_with_old_revision_is_409(client: TestClient) -> None:
    run_id = _create(client).json()["run_id"]

    response = client.post(f"/runs/{run_id}/cancel", json={"expected_revision": 5})

    assert _error(response) == (409, "RUN_REVISION_CONFLICT")
    assert _error(client.post(f"/runs/{run_id}/cancel", json={})) == (422, "INVALID_REQUEST")


# 재개 (POST /runs/{id}/resume)


def _resume(client: TestClient, run_id: str, interrupt_id: str, response: dict[str, Any]):  # type: ignore[no-untyped-def]
    return client.post(
        f"/runs/{run_id}/resume",
        json={"interrupt_id": interrupt_id, "expected_revision": 0, "response": response},
    )


ANSWERS = {"kind": "requirements", "answers": []}


def test_resume_moves_on_and_rejects_a_second_answer(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "requirements", S.AWAITING_REQUIREMENTS)

    first = _resume(client, run_id, interrupt_id, ANSWERS)
    second = _resume(client, run_id, interrupt_id, ANSWERS)

    assert first.status_code == 202
    assert (first.json()["status"], first.json()["interrupt"]) == ("designing", None)
    assert _error(second) == (409, "INTERRUPT_STALE")
    with pool.connection() as conn:
        assert lease.claimable_runs(conn, 10) == [UUID(run_id)]  # 실행기가 이어 간다


def test_resume_checks_interrupt_id_kind_and_body(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "requirements", S.AWAITING_REQUIREMENTS)
    review = {"kind": "review", "decision": "approve", "feedback": ""}

    assert _error(_resume(client, run_id, "int-other", ANSWERS)) == (409, "INTERRUPT_STALE")
    assert _error(_resume(client, run_id, interrupt_id, review)) == (422, "INVALID_RESPONSE")
    assert _error(_resume(client, run_id, interrupt_id, {"kind": "nope"})) == (
        422,
        "INVALID_RESPONSE",
    )


def test_extraction_not_confirmed_stops_the_run(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "extraction", S.AWAITING_INPUT)

    response = _resume(
        client, run_id, interrupt_id, {"kind": "extraction", "confirmed": False, "edits": []}
    )

    assert response.json()["status"] == "cancelled"


def test_review_hold_keeps_waiting_and_approve_is_blocked_by_critical(
    client: TestClient, pool: Pool
) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "review", S.AWAITING_REVIEW)
    with pool.connection() as conn:
        snapshot = uuid4()
        conn.execute(
            "INSERT INTO model_snapshot (snapshot_id, run_id, revision, normalized_model, "
            "model_hash) VALUES (%s, %s, 0, '{}', 'h')",
            (snapshot, run_id),
        )
        conn.execute(
            "INSERT INTO finding (snapshot_id, finding_id, source, reviewer_or_rule, fingerprint, "
            "iteration, payload) VALUES (%s, 'F-1', 'rule', 'RULE-01', 'fp', 0, %s)",
            (snapshot, Jsonb({"severity": "critical"})),
        )

    hold = _resume(
        client, run_id, interrupt_id, {"kind": "review", "decision": "hold", "feedback": ""}
    )
    approve = _resume(
        client, run_id, interrupt_id, {"kind": "review", "decision": "approve", "feedback": ""}
    )
    revise = _resume(
        client, run_id, interrupt_id, {"kind": "review", "decision": "revise", "feedback": "고침"}
    )

    assert hold.json()["status"] == "awaiting_review"
    assert _error(approve) == (422, "INVALID_RESPONSE")
    assert revise.json()["status"] == "designing"


# SSE (GET /runs/{id}/events)


def _sse(client: TestClient, run_id: str, last: str | None = None) -> list[dict[str, str]]:
    headers = {} if last is None else {"Last-Event-ID": last}
    with client.stream("GET", f"/runs/{run_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        events.append(fields)
    return events


def test_sse_replays_and_closes_when_the_run_has_ended(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    _wait(pool, run_id, "requirements", S.AWAITING_REQUIREMENTS)
    client.post(f"/runs/{run_id}/cancel", json={"expected_revision": 0})

    events = _sse(client, run_id)
    after_first = _sse(client, run_id, last="1")

    assert [e["event"] for e in events] == ["interrupt", "cancelled"]
    assert [e["id"] for e in events] == ["1", "2"]
    assert [e["id"] for e in after_first] == ["2"]


def test_sse_rejects_unknown_position_and_other_owner(
    client: TestClient, settings: Settings, pool: Pool
) -> None:
    run_id = _create(client).json()["run_id"]

    with client.stream("GET", f"/runs/{run_id}/events", headers={"Last-Event-ID": "99"}) as r:
        assert (r.status_code, r.read() and r.json()["code"]) == (409, "EVENT_REPLAY_EXPIRED")
    with _other(settings, pool).stream("GET", f"/runs/{run_id}/events") as r:
        assert r.status_code == 404
