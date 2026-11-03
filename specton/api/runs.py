"""실행 제어 API: 등록·조회·SSE·재개·취소 (06 문서).

모든 run 접근은 세션의 `owner_ref`로 검사하고, 다른 소유자의 run은 404다 (ADR-0011).
상태를 바꾸는 요청은 202와 현재 상태를 돌려준다. 202는 설계 성공을 뜻하지 않는다.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID, uuid4

import yaml
from anyio import to_thread
from fastapi import APIRouter, File, Form, Header, Path, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from specton.api.deps import ConnDep, PoolDep, SettingsDep
from specton.api.errors import ApiError
from specton.api.session import OwnerRef
from specton.api.uploads import save_upload
from specton.config import Settings
from specton.contracts import (
    ErrorCode,
    ResumeRequest,
    RunState,
    RunStatus,
    RunSummary,
    SseEvent,
)
from specton.packs.build import discover_packs
from specton.persistence import runs
from specton.persistence.db import Pool
from specton.persistence.lease import FINAL_STATES

router = APIRouter(prefix="/runs")

RunId = Annotated[UUID, Path(alias="id")]
_KEEPALIVE_SECONDS = 15.0


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


def _pack_version(settings: Settings, pack: str) -> str:
    """선택한 팩의 버전. 없는 팩이면 422 PACK_UNSUPPORTED. 팩 목록은 domain_packs에서 읽는다."""
    packs = {p.name: p for p in discover_packs(settings.pack_root)}
    if pack not in packs:
        raise ApiError(
            422, ErrorCode.PACK_UNSUPPORTED, f"지원하는 팩은 {', '.join(sorted(packs))}입니다."
        )
    manifest = yaml.safe_load((packs[pack] / "manifest.yaml").read_text(encoding="utf-8"))
    return str(manifest["version"])


def _model_config(settings: Settings) -> dict[str, str]:
    """실행에 쓴 모델 설정. 재현을 위해 run에 기록한다."""
    return {
        "design_model": settings.design_model,
        "review_model": settings.review_model,
        "design_reasoning_effort": settings.design_reasoning_effort,
        "review_reasoning_effort": settings.review_reasoning_effort,
        "review_mode": settings.review_mode,
    }


@router.post("", status_code=202, operation_id="createRun")
def create_run(
    request: Request,
    owner: OwnerRef,
    settings: SettingsDep,
    pool: PoolDep,
    file: Annotated[UploadFile, File()],
    pack: Annotated[str, Form()],
) -> RunStatus:
    """요구사항 문서를 받아 `queued` 실행을 등록한다. 실행기가 찾아가 시작한다."""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes + 64 * 1024:
        raise ApiError(
            413, ErrorCode.UPLOAD_TOO_LARGE, f"파일이 {settings.max_upload_mb}MB를 넘습니다."
        )
    pack_version = _pack_version(settings, pack)
    run_id, document_id = uuid4(), uuid4()
    stored = save_upload(file, settings.storage_dir, run_id, document_id, max_bytes)
    try:
        with pool.connection() as conn, conn.transaction():
            status = runs.create_run(
                conn,
                owner,
                pack,
                pack_version=pack_version,
                model_config=_model_config(settings),
                run_id=run_id,
            )
            runs.add_document(
                conn,
                run_id,
                document_id=document_id,
                file_name=stored.file_name,
                file_format=stored.file_format,
                file_hash=stored.file_hash,
                storage_ref=stored.storage_ref,
            )
    except BaseException:
        (settings.storage_dir / stored.storage_ref).unlink(missing_ok=True)
        raise
    return status


@router.get("", operation_id="listRuns")
def list_runs(
    owner: OwnerRef,
    conn: ConnDep,
    status: RunState | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RunSummary]:
    """소유자의 실행 목록. 최근 것부터."""
    return runs.list_runs(conn, owner, status=status, limit=limit)


@router.get("/{id}", operation_id="getRun")
def get_run(run_id: RunId, owner: OwnerRef, conn: ConnDep) -> RunStatus:
    """현재 상태·revision·단계·확인 요청·실패 원인."""
    return runs.get_run(conn, run_id, owner)


@router.post("/{id}/resume", status_code=202, operation_id="resumeRun")
def resume_run(run_id: RunId, owner: OwnerRef, conn: ConnDep, body: ResumeRequest) -> RunStatus:
    """사람 확인 응답. 같은 요청에 두 번 답하거나 오래된 요청에 답하면 409."""
    runs.answer_interrupt(conn, run_id, owner, body)
    return runs.get_run(conn, run_id, owner)


@router.post("/{id}/cancel", status_code=202, operation_id="cancelRun")
def cancel_run(run_id: RunId, owner: OwnerRef, conn: ConnDep, body: CancelRequest) -> RunStatus:
    """취소 요청. 실행 중이면 `cancel_requested`, 실행자가 없으면 바로 `cancelled` (ADR-0012)."""
    runs.request_cancel(conn, run_id, owner, body.expected_revision)
    return runs.get_run(conn, run_id, owner)


@router.get("/{id}/events", operation_id="streamRunEvents")
async def stream_events(
    run_id: RunId,
    owner: OwnerRef,
    request: Request,
    pool: PoolDep,
    settings: SettingsDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """진행 이벤트 SSE. `Last-Event-ID` 이후를 재생한 뒤 새 이벤트를 이어 보낸다.

    확인할 때만 DB 연결을 빌린다. 연결이 끊겨도 실행은 취소하지 않는다.
    """
    after = _parse_event_id(last_event_id)
    # 스트림을 열기 전에 소유자·재생 위치를 확인해 404·409를 JSON으로 돌려준다
    first = await to_thread.run_sync(_fetch, pool, run_id, owner, after)
    return StreamingResponse(
        _event_stream(request, pool, settings, run_id, owner, after, first),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _parse_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    if not value.isdigit():
        raise ApiError(
            409,
            ErrorCode.EVENT_REPLAY_EXPIRED,
            "이어 받을 수 없는 이벤트 위치입니다. 상태를 조회한 뒤 다시 연결하세요.",
        )
    return int(value)


def _fetch(pool: Pool, run_id: UUID, owner: str, after: int) -> tuple[list[SseEvent], RunState]:
    with pool.connection() as conn:
        events = runs.events_after(conn, run_id, owner, after)
        return events, runs.get_run(conn, run_id, owner).status


async def _event_stream(
    request: Request,
    pool: Pool,
    settings: Settings,
    run_id: UUID,
    owner: str,
    last_id: int,
    first: tuple[list[SseEvent], RunState],
) -> AsyncIterator[str]:
    events, status = first
    idle = 0.0
    while True:
        for event in events:
            yield event.encode()
            last_id = event.id
        if events:
            idle = 0.0
        elif status in FINAL_STATES:
            return  # 끝난 실행: 남은 이벤트를 다 보냈으면 닫는다
        if await request.is_disconnected():
            return
        await asyncio.sleep(settings.sse_poll_seconds)
        idle += settings.sse_poll_seconds
        if idle >= _KEEPALIVE_SECONDS:
            yield ": keep-alive\n\n"
            idle = 0.0
        events, status = await to_thread.run_sync(_fetch, pool, run_id, owner, last_id)
