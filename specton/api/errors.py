"""오류 응답을 `code`/`message`/`run_id`/`retryable` 형식으로 통일한다 (06 문서 "오류 형식").

저장 계층 예외를 HTTP 상태와 `ErrorCode`로 바꾼다. 내부 예외·경로·비밀값은 응답에 넣지 않는다.
"""

import logging
from collections.abc import Mapping
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from specton.contracts import Error, ErrorCode
from specton.persistence import errors as pe

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """API가 직접 내는 오류 (업로드 한도·형식, 팩 등)."""

    def __init__(
        self, status: int, code: ErrorCode, message: str, *, retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


# 저장 계층 예외 → (HTTP 상태, 코드, 메시지, 다시 시도). 메시지가 None이면 예외의 메시지를 쓴다
_PERSISTENCE: dict[type[pe.PersistenceError], tuple[int, ErrorCode, str | None, bool]] = {
    pe.RunNotFoundError: (404, ErrorCode.RUN_NOT_FOUND, "실행을 찾을 수 없습니다.", False),
    pe.RevisionConflictError: (
        409,
        ErrorCode.RUN_REVISION_CONFLICT,
        "다른 revision입니다. 최신 상태를 조회한 뒤 다시 시도하세요.",
        False,
    ),
    pe.InterruptStaleError: (
        409,
        ErrorCode.INTERRUPT_STALE,
        "이미 답했거나 지금 기다리는 확인 요청이 아닙니다. 최신 상태를 조회하세요.",
        False,
    ),
    pe.InvalidTransitionError: (
        409,
        ErrorCode.RUN_REVISION_CONFLICT,
        "지금 상태에서는 할 수 없는 요청입니다. 최신 상태를 조회하세요.",
        False,
    ),
    pe.ResponseMismatchError: (
        422,
        ErrorCode.INVALID_RESPONSE,
        "확인 요청 종류와 응답 종류가 다릅니다.",
        False,
    ),
    pe.InvalidResponseError: (422, ErrorCode.INVALID_RESPONSE, None, False),
    pe.BlockingFindingsError: (
        422,
        ErrorCode.INVALID_RESPONSE,
        "차단 오류가 남아 있어 승인할 수 없습니다.",
        False,
    ),
    pe.ArtifactNotReadyError: (
        409,
        ErrorCode.ARTIFACT_NOT_READY,
        "요청한 산출물이 아직 없습니다. PDF는 승인한 revision에서만 받을 수 있습니다.",
        True,
    ),
    pe.EventReplayExpiredError: (
        409,
        ErrorCode.EVENT_REPLAY_EXPIRED,
        "이어 받을 수 없는 이벤트 위치입니다. 상태를 조회한 뒤 다시 연결하세요.",
        False,
    ),
}


# 라우팅 단계 오류 (없는 경로·틀린 메서드) → 메시지. 코드는 INVALID_REQUEST
_HTTP_MESSAGES = {404: "없는 경로입니다.", 405: "허용하지 않는 메서드입니다."}


def error_response(
    status: int,
    code: ErrorCode,
    message: str,
    *,
    run_id: str | None,
    retryable: bool,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = Error(code=code.value, message=message, run_id=run_id, retryable=retryable)
    return JSONResponse(body.model_dump(mode="json"), status_code=status, headers=headers)


def _run_id(request: Request) -> str | None:
    """경로의 run ID. UUID가 아니면 입력을 되돌려 주지 않도록 None."""
    value = request.path_params.get("id")
    try:
        return None if value is None else str(UUID(str(value)))
    except ValueError:
        return None


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            exc.status, exc.code, exc.message, run_id=_run_id(request), retryable=exc.retryable
        )

    @app.exception_handler(pe.PersistenceError)
    async def _persistence_error(request: Request, exc: pe.PersistenceError) -> JSONResponse:
        mapped = _PERSISTENCE.get(type(exc))
        if mapped is None:
            logger.exception("처리하지 않은 저장 오류", exc_info=exc)
            return error_response(
                500, ErrorCode.INTERNAL, "서버 오류입니다.", run_id=_run_id(request), retryable=True
            )
        status, code, message, retryable = mapped
        return error_response(
            status, code, message or str(exc), run_id=_run_id(request), retryable=retryable
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = _HTTP_MESSAGES.get(exc.status_code, "요청을 처리할 수 없습니다.")
        return error_response(
            exc.status_code,
            ErrorCode.INVALID_REQUEST,
            message,
            run_id=_run_id(request),
            retryable=False,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 입력 값은 응답에 되돌려 주지 않는다 (원문·세션이 섞일 수 있다)
        where = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        resume = request.url.path.endswith("/resume")
        code = ErrorCode.INVALID_RESPONSE if resume else ErrorCode.INVALID_REQUEST
        return error_response(
            422, code, f"요청 형식이 틀렸습니다: {where}", run_id=_run_id(request), retryable=False
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("처리하지 않은 서버 오류", exc_info=exc)
        return error_response(
            500, ErrorCode.INTERNAL, "서버 오류입니다.", run_id=_run_id(request), retryable=True
        )
