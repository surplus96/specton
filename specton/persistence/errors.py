"""저장 계층 오류. API가 `ErrorCode`로 바꿔 응답한다 (06 문서)."""


class PersistenceError(Exception):
    """저장 계층 오류의 기반."""


class RunNotFoundError(PersistenceError):
    """없는 실행이거나 다른 소유자의 실행. 둘을 구분해 알리지 않는다 (ADR-0011)."""


class RevisionConflictError(PersistenceError):
    """요청의 `expected_revision`이 현재 revision과 다르다."""

    def __init__(self, run_id: str, current: int) -> None:
        super().__init__(f"run {run_id}의 현재 revision은 {current}입니다")
        self.current = current


class InvalidTransitionError(PersistenceError):
    """허용하지 않는 상태 전이. 이미 끝난 실행을 취소하는 경우도 여기에 든다."""


class LeaseLostError(PersistenceError):
    """lease를 잃은 실행자의 기록. 다른 실행자가 이어받았을 수 있으므로 저장하지 않는다."""


class InterruptStaleError(PersistenceError):
    """이미 답했거나 지금 기다리는 것이 아닌 확인 요청에 답했다."""


class ResponseMismatchError(PersistenceError):
    """확인 요청 종류와 다른 응답 (예: 추출 확인에 검토 응답)."""


class InvalidResponseError(PersistenceError):
    """확인 요청의 내용과 맞지 않는 답 (예: `pass` 블록 제외). 메시지에 블록 ID를 넣는다."""


class BlockingFindingsError(PersistenceError):
    """차단 오류(critical)가 남아 있어 승인할 수 없다 (ADR-0010)."""


class ArtifactNotReadyError(PersistenceError):
    """요청한 revision·형식의 산출물이 아직 없다 (PDF는 승인본만)."""


class EventReplayExpiredError(PersistenceError):
    """재생할 수 없는 이벤트 위치. 상태를 다시 조회한 뒤 이어 받는다."""
