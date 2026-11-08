"""실행 제어 API (06 문서): 등록·조회·재개·취소·SSE·오류 형식. 로컬 DB가 필요하다.

실행기(#17)는 없으므로, 실행기가 할 진행 기록은 저장 함수로 직접 만든다.
"""

import io
import zipfile
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
from specton.contracts import (
    VALIDATION_STEPS,
    ArtifactRef,
    DesignState,
    Interrupt,
    ResumeRequest,
    SseEventType,
)
from specton.contracts import RunState as S
from specton.persistence import lease, runs, validations
from specton.persistence.db import Pool
from specton.persistence.runs import NewEvent, answer_interrupt, events_after, record_progress
from specton.persistence.snapshots import add_artifact, save_model

pytestmark = pytest.mark.db

StateFactory = Callable[[str, str], DesignState]


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


# 실행기가 없어 파서는 돌지 않는다. 업로드 내용 검사(zip인지)만 통과하면 된다 (#21)
XLSX = ("req.xlsx", _zip({"[Content_Types].xml": b"<Types/>"}), "application/octet-stream")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        require_sql_validation=False,
        storage_dir=tmp_path / "storage",
        sse_poll_seconds=0.01,
    )


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


@pytest.mark.parametrize(
    ("file", "message"),
    [
        (("req.xlsx", b"not a workbook", "application/octet-stream"), "형식이 아닙니다"),
        (("req.hwpx", b"<hwpml/>", "application/octet-stream"), "형식이 아닙니다"),
        (("req.csv", b"id,text\n1,\x00\x01", "text/csv"), "텍스트가 아닙니다"),
    ],
)
def test_content_that_does_not_match_the_extension_is_415(
    client: TestClient, settings: Settings, file: tuple[str, bytes, str], message: str
) -> None:
    """확장자만 바꾼 파일을 파서에 넘기지 않는다 (#21, TC-N03)."""
    response = _create(client, file)

    assert _error(response) == (415, "UNSUPPORTED_MEDIA_TYPE")
    assert message in response.json()["message"]
    assert not any(p.is_file() for p in settings.storage_dir.rglob("*"))


def test_zip_that_unpacks_beyond_the_limit_is_413(settings: Settings, pool: Pool) -> None:
    """압축 폭탄: 올린 크기는 작아도 압축을 푼 크기가 한도를 넘으면 막는다 (#21, TC-N05)."""
    small = settings.model_copy(update={"max_unzipped_mb": 1})
    bomb = _zip({"xl/worksheets/sheet1.xml": b"0" * (2 * 1024 * 1024)})
    assert len(bomb) < 64 * 1024
    with TestClient(create_app(small, pool)) as client:
        response = _create(client, ("req.xlsx", bomb, "application/octet-stream"))

    assert _error(response) == (413, "UPLOAD_TOO_LARGE")
    assert "압축을 푼 크기" in response.json()["message"]
    assert not any(p.is_file() for p in settings.storage_dir.rglob("*"))


@pytest.mark.parametrize("secure", [False, True])
def test_session_cookie_is_secure_only_when_configured(
    settings: Settings, pool: Pool, secure: bool
) -> None:
    """HTTPS 배포에서는 세션 쿠키에 Secure를 붙인다 (#21, PR #108 리뷰)."""
    app = create_app(settings.model_copy(update={"session_cookie_secure": secure}), pool)
    with TestClient(app) as client:
        cookie = client.get("/runs").headers["set-cookie"]

    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert ("Secure" in cookie) is secure


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
    # 확인 응답도 다른 세션이면 실행이 없는 것과 같다 (#21, TC-N03)
    assert _error(_resume(other, run_id, "int-x", ANSWERS)) == (404, "RUN_NOT_FOUND")


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
    _analysed(pool, run_id)

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


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(None, id="missing-snapshot"),
        pytest.param({}, id="missing-requirements"),
        pytest.param({"requirements": None}, id="null-requirements"),
    ],
)
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_answers(), id="empty-answer"),
        pytest.param(_answers(("REQ-01", "keep", [])), id="keep-answer"),
    ],
)
def test_missing_requirements_model_is_internal_and_keeps_waiting(
    client: TestClient, pool: Pool, model: dict[str, Any] | None, answer: dict[str, Any]
) -> None:
    """모델 누락은 빈 답도 500이며, 기록을 남기지 않고 복구 후 재응답할 수 있다 (#144·#146)."""
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "requirements", S.AWAITING_REQUIREMENTS)
    with pool.connection() as conn:
        if model is not None:
            conn.execute(
                "INSERT INTO model_snapshot (snapshot_id, run_id, revision, normalized_model, "
                "model_hash) VALUES (%s, %s, 0, %s, 'h')",
                (uuid4(), run_id, Jsonb(model)),
            )
        before = runs.get_run(conn, UUID(run_id), _owner(client))
        before_events = events_after(conn, UUID(run_id), _owner(client), 0)

    response = _resume(client, run_id, interrupt_id, answer)

    assert _error(response) == (500, "INTERNAL")
    assert response.json() == {
        "code": "INTERNAL",
        "message": "서버 오류입니다.",
        "run_id": run_id,
        "retryable": True,
    }
    with pool.connection() as conn:
        assert runs.get_run(conn, UUID(run_id), _owner(client)) == before
        assert events_after(conn, UUID(run_id), _owner(client), 0) == before_events
        assert (
            conn.execute("SELECT 1 FROM approval WHERE run_id = %s", (run_id,)).fetchone() is None
        )
        if model is not None:
            conn.execute(
                "UPDATE model_snapshot SET normalized_model = %s "
                "WHERE run_id = %s AND revision = 0",
                (Jsonb({"requirements": [{"id": "REQ-01"}]}), run_id),
            )
    if model is None:
        _analysed(pool, run_id, "REQ-01")
    assert _resume(client, run_id, interrupt_id, answer).status_code == 202


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


# 최종 승인의 SQL 검증 확인·승인 근거 (#195, #167)

SQL_HASH = "a" * 64
OLD_VERSIONS = {**validations.REQUIRED_VERSIONS, "validator_version": "sql-validator-v0"}
APPROVE = {"kind": "review", "decision": "approve", "feedback": ""}


def _steps(status: str) -> list[dict[str, Any]]:
    """전체 상태가 `status`가 되는 다섯 단계 (실패·장애는 execute, 미검증은 뒤 세 단계 미실행)."""
    names = [n.value for n in VALIDATION_STEPS]
    if status == "passed":
        return [{"name": n, "status": "passed", "issues": []} for n in names]
    if status == "unverified":
        return [
            {"name": n, "status": "passed" if i < 2 else "not_run", "issues": []}
            for i, n in enumerate(names)
        ]
    issue = [{"code": "x", "message": None, "statement_index": None, "sqlstate": None}]
    return [
        {"name": n, "status": status if n == "execute" else "passed",
         "issues": issue if n == "execute" else []}
        for n in names
    ]  # fmt: skip


def _review_with_sql(
    pool: Pool, run_id: str, attempts: list[tuple[str, dict[str, str]]], *, sql: bool = True
) -> dict[str, UUID]:
    """revision 0 스냅샷에 ERD와 (선택) SQL 산출물, 검증 시도들을 넣는다.

    시도는 넣은 순서대로 검증 시각이 1분씩 늦다.
    """
    ids: dict[str, UUID] = {}
    with pool.connection() as conn:
        snapshot = uuid4()
        conn.execute(
            "INSERT INTO model_snapshot (snapshot_id, run_id, revision, normalized_model, "
            "model_hash) VALUES (%s, %s, 0, '{}', 'm')",
            (snapshot, run_id),
        )
        kinds = [("erd", "mmd", "e" * 64)] + ([("ddl", "sql", SQL_HASH)] if sql else [])
        for kind, file_format, digest in kinds:
            ids[kind] = uuid4()
            conn.execute(
                "INSERT INTO artifact (artifact_id, snapshot_id, kind, file_format, hash, "
                "storage_ref) VALUES (%s, %s, %s, %s, %s, 'x')",
                (ids[kind], snapshot, kind, file_format, digest),
            )
        for i, (status, versions) in enumerate(attempts):
            ids[f"attempt-{i}"] = uuid4()
            conn.execute(
                "INSERT INTO artifact_validation (validation_id, artifact_id, artifact_hash, "
                "model_hash, status, steps, validator_version, policy_version, postgres_version, "
                "validated_at) VALUES (%s, %s, %s, 'm', %s, %s, %s, %s, %s, "
                "'2026-11-08T09:00:00Z'::timestamptz + %s * interval '1 minute')",
                (
                    ids[f"attempt-{i}"], ids["ddl"], SQL_HASH, status, Jsonb(_steps(status)),
                    versions["validator_version"], versions["policy_version"],
                    versions["postgres_version"], i,
                ),
            )  # fmt: skip
    return ids


@pytest.fixture
def checked_client(settings: Settings, pool: Pool) -> Iterator[TestClient]:
    """최종 승인 때 SQL 검증 통과를 요구하는 앱."""
    with TestClient(
        create_app(settings.model_copy(update={"require_sql_validation": True}), pool)
    ) as c:
        yield c


def _basis(pool: Pool, run_id: str) -> dict[UUID, UUID | None]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT b.artifact_id, b.validation_id FROM approval_basis b JOIN approval a "
            "USING (approval_id) WHERE a.run_id = %s",
            (run_id,),
        ).fetchall()
    return {r["artifact_id"]: r["validation_id"] for r in rows}


def test_approve_with_a_passed_sql_records_the_basis(
    checked_client: TestClient, pool: Pool
) -> None:
    run_id = _create(checked_client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "review", S.AWAITING_REVIEW)
    ids = _review_with_sql(pool, run_id, [("passed", validations.REQUIRED_VERSIONS)])

    response = _resume(checked_client, run_id, interrupt_id, APPROVE)

    assert response.status_code == 202
    assert _basis(pool, run_id) == {ids["erd"]: None, ids["ddl"]: ids["attempt-0"]}


@pytest.mark.parametrize(
    ("attempts", "sql", "message"),
    [
        ([], False, "승인할 SQL 산출물이 없습니다."),
        ([], True, "검증을 통과하지 않은 SQL"),  # 기록 없음 = unverified
        ([("unverified", validations.REQUIRED_VERSIONS)], True, "검증을 통과하지 않은 SQL"),
        ([("failed", validations.REQUIRED_VERSIONS)], True, "검증을 통과하지 않은 SQL"),
        ([("error", validations.REQUIRED_VERSIONS)], True, "검증을 통과하지 않은 SQL"),
        # 새 시도가 실패면 이전 통과로 돌아가지 않는다
        (
            [("passed", validations.REQUIRED_VERSIONS), ("failed", validations.REQUIRED_VERSIONS)],
            True,
            "검증을 통과하지 않은 SQL",
        ),
        # 지금 요구하는 버전의 시도가 없으면 이전 버전 통과를 쓰지 않는다
        ([("passed", OLD_VERSIONS)], True, "검증을 통과하지 않은 SQL"),
    ],
)
def test_approve_is_rejected_without_a_current_passed_sql(
    checked_client: TestClient,
    pool: Pool,
    attempts: list[tuple[str, dict[str, str]]],
    sql: bool,
    message: str,
) -> None:
    run_id = _create(checked_client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "review", S.AWAITING_REVIEW)
    _review_with_sql(pool, run_id, attempts, sql=sql)

    response = _resume(checked_client, run_id, interrupt_id, APPROVE)

    assert _error(response) == (422, "INVALID_RESPONSE")
    assert message in response.json()["message"]
    status = checked_client.get(f"/runs/{run_id}").json()
    assert (status["status"], status["interrupt"]["interrupt_id"]) == (
        "awaiting_review",
        interrupt_id,
    )
    assert _basis(pool, run_id) == {}
    with pool.connection() as conn:
        assert (
            conn.execute("SELECT 1 FROM approval WHERE run_id = %s", (run_id,)).fetchone() is None
        )


def test_without_the_setting_approve_skips_the_check_but_keeps_the_basis(
    client: TestClient, pool: Pool
) -> None:
    """연결 전(기본값)에는 지금처럼 승인하고, SQL 근거에 검증 시도를 붙이지 않는다."""
    run_id = _create(client).json()["run_id"]
    interrupt_id = _wait(pool, run_id, "review", S.AWAITING_REVIEW)
    ids = _review_with_sql(pool, run_id, [("failed", validations.REQUIRED_VERSIONS)])

    response = _resume(client, run_id, interrupt_id, APPROVE)

    assert response.status_code == 202
    assert _basis(pool, run_id) == {ids["erd"]: None, ids["ddl"]: None}


def test_view_shows_the_current_sql_validation(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    _wait(pool, run_id, "review", S.AWAITING_REVIEW)
    _review_with_sql(
        pool, run_id, [("passed", OLD_VERSIONS), ("failed", validations.REQUIRED_VERSIONS)]
    )

    artifacts = client.get(f"/runs/{run_id}/view", params={"section": "design"}).json()["artifacts"]

    by_kind = {a["kind"]: a for a in artifacts}
    assert "validation" not in by_kind["erd"]
    assert by_kind["ddl"]["validation"] == {
        "status": "failed",
        "validated_at": "2026-11-08T09:01:00+00:00",
    }


def test_view_shows_unverified_when_no_record_matches(client: TestClient, pool: Pool) -> None:
    run_id = _create(client).json()["run_id"]
    _wait(pool, run_id, "review", S.AWAITING_REVIEW)
    _review_with_sql(pool, run_id, [("passed", OLD_VERSIONS)])

    artifacts = client.get(f"/runs/{run_id}/view", params={"section": "design"}).json()["artifacts"]

    sql = next(a for a in artifacts if a["kind"] == "ddl")
    assert sql["validation"] == {"status": "unverified", "validated_at": None}


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


@pytest.mark.parametrize("absolute", [False, True])
def test_download_rejects_a_record_pointing_outside_storage(
    client: TestClient, settings: Settings, pool: Pool, sample_state: StateFactory, absolute: bool
) -> None:
    run_id = _saved(client, pool, sample_state)
    _artifact(
        settings, pool, run_id,
        ArtifactRef(kind="ddl", file_format="sql", revision=0, hash="fixture"), b"fixture",
    )  # fmt: skip
    outside = settings.storage_dir.parent / "storage-other" / "private.sql"
    outside.parent.mkdir()
    outside.write_bytes(b"must not be downloaded")
    storage_ref = str(outside) if absolute else "../storage-other/private.sql"
    with pool.connection() as conn:
        conn.execute("UPDATE artifact SET storage_ref = %s", (storage_ref,))

    with pytest.raises(RuntimeError, match="산출물 기록은 있으나 파일이 없습니다"):
        client.get(f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": 0})
