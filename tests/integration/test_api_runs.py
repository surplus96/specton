"""실행 제어 API (06 문서): 등록·조회·재개·취소·SSE·오류 형식. 로컬 DB가 필요하다.

실행기(#17)는 없으므로, 실행기가 할 진행 기록은 저장 함수로 직접 만든다.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from specton.api.main import create_app
from specton.api.session import SESSION_COOKIE
from specton.config import Settings
from specton.contracts import ArtifactRef, DesignState, Interrupt, ResumeRequest, SseEventType
from specton.contracts import RunState as S
from specton.persistence import lease, runs
from specton.persistence.db import Pool
from specton.persistence.runs import NewEvent, answer_interrupt, events_after, record_progress
from specton.persistence.snapshots import add_artifact, save_model

pytestmark = pytest.mark.db

StateFactory = Callable[[str, str], DesignState]
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
    assert not any(settings.storage_dir.rglob("*"))  # 빈 run 폴더도 남기지 않는다


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


def test_bad_run_id_is_not_echoed_back(client: TestClient) -> None:
    response = client.get("/runs/abc")

    assert _error(response) == (422, "INVALID_REQUEST")
    assert response.json()["run_id"] is None


def test_routing_errors_use_the_same_format(client: TestClient) -> None:
    missing = client.get("/nope")
    wrong_method = client.delete("/runs")

    assert _error(missing) == (404, "INVALID_REQUEST")
    assert _error(wrong_method) == (405, "INVALID_REQUEST")
    assert "POST" in wrong_method.headers["allow"]


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

    response = _resume(client, run_id, interrupt_id, {"kind": "extraction", "confirmed": False})

    assert response.json()["status"] == "cancelled"


def _judged(pool: Pool, run_id: str, **statuses: str) -> None:
    """실행기가 파싱 뒤 남긴 추출 블록과 판정 (block_id=판정)."""
    with pool.connection() as conn:
        document = conn.execute("SELECT document_id FROM document WHERE run_id = %s", (run_id,))
        document_id = document.fetchone()["document_id"]  # type: ignore[index]
        for block_id, status in statuses.items():
            conn.execute(
                "INSERT INTO source_block (document_id, block_id, source_ref, source_text, "
                "extraction_status, payload) VALUES (%s, %s, '{}', '원문', %s, '{}')",
                (document_id, block_id, status),
            )


def _extraction(*excluded: dict[str, str], confirmed: bool = True) -> dict[str, Any]:
    return {"kind": "extraction", "confirmed": confirmed, "excluded_blocks": list(excluded)}


@pytest.mark.parametrize(
    ("answer", "block"),
    [
        (_extraction({"block_id": "B1"}, confirmed=False), None),  # 중단하면서 제외
        (_extraction({"block_id": "B2", "reason": "범위 밖"}), "B3"),  # fail을 남김
        (_extraction({"block_id": "B9"}, {"block_id": "B3"}), "B9"),  # 없는 블록
        (_extraction({"block_id": "B1"}, {"block_id": "B3"}), "B1"),  # pass 블록
        (_extraction({"block_id": "B2", "reason": " "}, {"block_id": "B3"}), "B2"),  # 빈 사유
        (_extraction({"block_id": "B3"}, {"block_id": "B3"}), "B3"),  # 두 번 제외
    ],
)
def test_extraction_answer_must_match_the_block_judgements(
    client: TestClient, pool: Pool, answer: dict[str, Any], block: str | None
) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "extraction", S.AWAITING_INPUT)
    _judged(pool, run_id, B1="pass", B2="review", B3="fail")

    response = _resume(client, run_id, interrupt_id, answer)

    assert _error(response) == (422, "INVALID_RESPONSE")
    if block is not None:
        assert response.json()["message"].startswith(f"{block}:")
    assert client.get(f"/runs/{run_id}").json()["status"] == "awaiting_input"  # 그대로 기다린다


def test_extraction_answer_with_valid_exclusions_moves_on(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "extraction", S.AWAITING_INPUT)
    _judged(pool, run_id, B1="pass", B2="review", B3="review", B4="fail")
    answer = _extraction({"block_id": "B2", "reason": "2차 범위"}, {"block_id": "B4"})

    response = _resume(client, run_id, interrupt_id, answer)  # B3은 확인, B4는 사유 없이 제외

    assert response.status_code == 202
    assert response.json()["status"] == "analysing"


def _confirmed_events(pool: Pool, client: TestClient, run_id: str) -> list[dict[str, Any]]:
    """재생한 이벤트 중 추출 확인 목록을 담은 것의 payload."""
    with pool.connection() as conn:
        events = events_after(conn, UUID(run_id), _owner(client), 0)
    return [e.data.payload for e in events if "confirmed_block_ids" in e.data.payload]


def _blank(pool: Pool, block_id: str) -> None:
    """원문 문장이 없는 블록(범례·각주 줄)으로 바꾼다."""
    with pool.connection() as conn:
        conn.execute("UPDATE source_block SET source_text = NULL WHERE block_id = %s", (block_id,))


def test_extraction_answer_records_the_confirmed_review_blocks(
    client: TestClient, pool: Pool
) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "extraction", S.AWAITING_INPUT)
    _judged(pool, run_id, B1="pass", B2="review", B3="review", B4="review", B5="review", B6="fail")
    _blank(pool, "B3")  # 원문 없는 review를 확인
    _blank(pool, "B5")  # 원문 없는 review를 제외
    answer = _extraction(
        {"block_id": "B4", "reason": "2차 범위"},
        {"block_id": "B5", "reason": "범례"},
        {"block_id": "B6"},
    )

    response = _resume(client, run_id, interrupt_id, answer)
    again = _resume(client, run_id, interrupt_id, answer)

    assert response.status_code == 202
    assert _error(again) == (409, "INTERRUPT_STALE")
    expected = {
        "kind": "extraction",
        "interrupt_id": interrupt_id,
        "confirmed_block_ids": ["B2", "B3"],
    }
    assert _confirmed_events(pool, client, run_id) == [expected]  # 재생할 수 있고 한 번만 남는다


def test_excluding_every_review_block_records_an_empty_list(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "extraction", S.AWAITING_INPUT)
    _judged(pool, run_id, B1="pass", B2="review")

    response = _resume(
        client, run_id, interrupt_id, _extraction({"block_id": "B2", "reason": "범위 밖"})
    )

    assert response.status_code == 202
    assert [p["confirmed_block_ids"] for p in _confirmed_events(pool, client, run_id)] == [[]]


def test_stopped_or_rejected_extraction_answer_records_no_confirmation(
    client: TestClient, pool: Pool
) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "extraction", S.AWAITING_INPUT)
    _judged(pool, run_id, B1="review", B2="fail")

    rejected = _resume(client, run_id, interrupt_id, _extraction())  # fail을 남김
    stopped = _resume(client, run_id, interrupt_id, _extraction(confirmed=False))

    assert _error(rejected) == (422, "INVALID_RESPONSE")
    assert stopped.json()["status"] == "cancelled"
    assert _confirmed_events(pool, client, run_id) == []


def test_extraction_answer_rolls_back_together_when_saving_fails(
    client: TestClient, pool: Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "extraction", S.AWAITING_INPUT)
    _judged(pool, run_id, B1="review")
    request = ResumeRequest.model_validate(
        {"interrupt_id": interrupt_id, "expected_revision": 0, "response": _extraction()}
    )

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("이벤트 저장 실패")

    monkeypatch.setattr(runs, "_append_events", broken)
    with pool.connection() as conn, pytest.raises(RuntimeError):
        answer_interrupt(conn, UUID(run_id), _owner(client), request)
    monkeypatch.undo()

    with pool.connection() as conn:
        approvals = conn.execute("SELECT count(*) AS n FROM approval WHERE run_id = %s", (run_id,))
        assert approvals.fetchone()["n"] == 0  # type: ignore[index]
    assert client.get(f"/runs/{run_id}").json()["status"] == "awaiting_input"
    assert _confirmed_events(pool, client, run_id) == []


def _analysed(pool: Pool, run_id: str, *req_ids: str) -> None:
    """실행기가 분석 확인에서 멈추며 저장한 revision 0 모델 (요구사항 ID만)."""
    model = {"requirements": [{"id": r} for r in req_ids]}
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO model_snapshot (snapshot_id, run_id, revision, normalized_model, "
            "model_hash) VALUES (%s, %s, 0, %s, 'h')",
            (uuid4(), run_id, Jsonb(model)),
        )


def _answers(*answers: tuple[str, str, list[str]]) -> dict[str, Any]:
    return {
        "kind": "requirements",
        "answers": [{"req_id": r, "action": a, "texts": t} for r, a, t in answers],
    }


@pytest.mark.parametrize(
    ("answer", "req_id"),
    [
        (_answers(("REQ-09", "keep", [])), "REQ-09"),  # 없는 요구사항
        (_answers(("REQ-01", "keep", []), ("REQ-01", "edit", ["새 문장"])), "REQ-01"),  # 두 번
        (_answers(("REQ-01", "keep", ["바꿀 문장"])), "REQ-01"),  # keep은 문장 0개
        (_answers(("REQ-02", "edit", ["가", "나"])), "REQ-02"),  # edit은 1개
        (_answers(("REQ-02", "split", ["하나만"])), "REQ-02"),  # split은 2개 이상
        (_answers(("REQ-01", "split", ["입고를 등록한다", " "])), "REQ-01"),  # 빈 문장
    ],
)
def test_requirements_answer_must_match_the_saved_requirements(
    client: TestClient, pool: Pool, answer: dict[str, Any], req_id: str
) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "requirements", S.AWAITING_REQUIREMENTS)
    _analysed(pool, run_id, "REQ-01", "REQ-02")

    response = _resume(client, run_id, interrupt_id, answer)
    again = _resume(client, run_id, interrupt_id, _answers(("REQ-01", "keep", [])))

    assert _error(response) == (422, "INVALID_RESPONSE")
    assert response.json()["message"].startswith(f"{req_id}:")
    assert again.status_code == 202  # 거절된 답은 기록되지 않아 다시 답할 수 있다


def test_requirements_answer_that_fits_moves_on(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "requirements", S.AWAITING_REQUIREMENTS)
    _analysed(pool, run_id, "REQ-01", "REQ-02")
    answer = _answers(("REQ-01", "edit", ["입고를 등록한다"]), ("REQ-02", "split", ["가", "나"]))

    response = _resume(client, run_id, interrupt_id, answer)

    assert response.status_code == 202
    assert response.json()["status"] == "designing"


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


# 화면용 조회 (GET /runs/{id}/view)


def _saved(client: TestClient, pool: Pool, sample_state: StateFactory) -> str:
    """실행기가 모델·지적을 저장한 run (revision 0)."""
    run_id = _create(client).json()["run_id"]
    with pool.connection() as conn:
        row = conn.execute("SELECT document_id FROM document WHERE run_id = %s", (run_id,))
        document_id = str(row.fetchone()["document_id"])  # type: ignore[index]
        assert lease.acquire(conn, UUID(run_id), "w1", 60)
        save_model(conn, UUID(run_id), "w1", sample_state(run_id, document_id))
    return run_id


def test_view_is_empty_before_any_result(client: TestClient) -> None:
    run_id = _create(client).json()["run_id"]

    for section in ("extraction", "requirements", "design", "review"):
        body = client.get(f"/runs/{run_id}/view", params={"section": section}).json()
        assert (body["revision"], body["items"], body["artifacts"]) == (0, [], [])


def test_view_reads_saved_sections(
    client: TestClient, pool: Pool, sample_state: StateFactory
) -> None:
    run_id = _saved(client, pool, sample_state)

    def items(section: str) -> list[dict[str, Any]]:
        return client.get(f"/runs/{run_id}/view", params={"section": section}).json()["items"]  # type: ignore[no-any-return]

    assert [b["block_id"] for b in items("extraction")] == ["B-1"]
    assert [r["id"] for r in items("requirements")] == ["REQ-01"]
    assert [(d["type"], d["id"]) for d in items("design")] == [
        ("function", "FUNC-01"),
        ("entity", "ENT-01"),
    ]
    assert [f["id"] for f in items("review")] == ["A05-1-1"]


def test_view_checks_section_revision_and_owner(
    client: TestClient, settings: Settings, pool: Pool
) -> None:
    run_id = _create(client).json()["run_id"]
    view = f"/runs/{run_id}/view"

    assert _error(client.get(view, params={"section": "nope"})) == (422, "INVALID_REQUEST")
    assert _error(client.get(view, params={"section": "design", "revision": 1})) == (
        409,
        "RUN_REVISION_CONFLICT",
    )
    assert _error(_other(settings, pool).get(view, params={"section": "design"})) == (
        404,
        "RUN_NOT_FOUND",
    )


# 산출물 내려받기 (GET /runs/{id}/artifacts/{kind})


def _artifact(
    settings: Settings, pool: Pool, run_id: str, ref: ArtifactRef, content: bytes
) -> None:
    storage_ref = f"{run_id}/artifacts/{ref.kind}.{ref.file_format}"
    (settings.storage_dir / storage_ref).parent.mkdir(parents=True, exist_ok=True)
    (settings.storage_dir / storage_ref).write_bytes(content)
    with pool.connection() as conn:
        add_artifact(conn, UUID(run_id), "w1", ref, storage_ref)


def test_download_sends_the_file_with_a_safe_name(
    client: TestClient, settings: Settings, pool: Pool, sample_state: StateFactory
) -> None:
    run_id = _saved(client, pool, sample_state)
    _artifact(settings, pool, run_id, ArtifactRef(kind="ddl", file_format="sql", revision=0,
              hash="abc"), b"CREATE TABLE t ();")  # fmt: skip

    response = client.get(
        f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": 0}
    )
    listed = client.get(f"/runs/{run_id}/view", params={"section": "design"}).json()

    assert response.status_code == 200
    assert response.content == b"CREATE TABLE t ();"
    assert 'filename="specton-ddl-r0-draft.sql"' in response.headers["content-disposition"]
    assert response.headers["etag"] == '"abc"'
    assert [(a["kind"], a["approved"]) for a in listed["artifacts"]] == [("ddl", False)]


def test_download_rejects_bad_combinations_and_missing_files(
    client: TestClient, settings: Settings, pool: Pool, sample_state: StateFactory
) -> None:
    run_id = _saved(client, pool, sample_state)
    _artifact(settings, pool, run_id, ArtifactRef(kind="erd", file_format="pdf", revision=0,
              hash="h"), b"%PDF")  # fmt: skip
    url = f"/runs/{run_id}/artifacts"

    def get(kind: str, file_format: str) -> Any:
        return client.get(f"{url}/{kind}", params={"file_format": file_format, "revision": 0})

    assert _error(get("ddl", "pdf")) == (422, "ARTIFACT_FORMAT_UNSUPPORTED")
    assert _error(get("ddl", "sql")) == (409, "ARTIFACT_NOT_READY")
    assert _error(get("erd", "pdf")) == (409, "ARTIFACT_NOT_READY")  # 초안 PDF는 내주지 않는다
    assert get("ddl", "sql").json()["retryable"] is True
    assert _error(
        _other(settings, pool).get(f"{url}/ddl", params={"file_format": "sql", "revision": 0})
    ) == (404, "RUN_NOT_FOUND")
