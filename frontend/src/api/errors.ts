// API 오류를 한곳에서 다룬다.
// - 서버가 보낸 오류 본문(code·message·retryable)을 ApiError에 담는다.
// - 화면에는 errorMessage()로 한글 안내를 보여 주고, nextAction()으로 다음 행동(새로고침·다시 시도 등)을 정한다.
import type { ApiErrorBody, ErrorCode } from './types.ts'

export class ApiError extends Error {
  /** HTTP 상태 코드. 서버에 닿지 못했으면 0 */
  readonly status: number
  /** 서버가 보낸 오류 본문. 형식이 맞지 않거나 연결 실패면 null */
  readonly body: ApiErrorBody | null
  /** 연결 실패 등 원래 예외 (디버깅용) */
  readonly origin: unknown

  constructor(status: number, body: ApiErrorBody | null, origin?: unknown) {
    super(body?.message ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.origin = origin
  }

  /** 오류 코드. 연결 실패는 'NETWORK', 본문을 읽지 못하면 'UNKNOWN' */
  get code(): ErrorCode | 'NETWORK' | 'UNKNOWN' {
    if (this.status === 0) return 'NETWORK'
    return (this.body?.code as ErrorCode | undefined) ?? 'UNKNOWN'
  }

  static async fromResponse(res: Response): Promise<ApiError> {
    let body: ApiErrorBody | null = null
    try {
      const data: unknown = await res.json()
      if (isErrorBody(data)) body = data
    } catch {
      // JSON이 아닌 응답(프록시 오류 페이지 등)
    }
    return new ApiError(res.status, body)
  }
}

function isErrorBody(data: unknown): data is ApiErrorBody {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as ApiErrorBody).code === 'string' &&
    typeof (data as ApiErrorBody).message === 'string'
  )
}

// 서버 문구가 없을 때 쓰는 안내. 서버 문구(body.message)가 있으면 그것을 그대로 보여 준다.
const FALLBACK_MESSAGES: Record<ErrorCode, string> = {
  RUN_NOT_FOUND: '이 작업을 찾을 수 없어요.',
  RUN_REVISION_CONFLICT: '다른 곳에서 내용이 바뀌었습니다. 새로고침한 뒤 다시 시도해 주세요.',
  INTERRUPT_STALE: '이미 답한 확인이에요. 새로고침해 주세요.',
  EVENT_REPLAY_EXPIRED: '진행 기록을 다시 불러올게요. 새로고침해 주세요.',
  ARTIFACT_NOT_READY: '파일이 아직 만들어지지 않았습니다.',
  ARTIFACT_FORMAT_UNSUPPORTED: '이 형식으로는 내려받을 수 없습니다.',
  UPLOAD_TOO_LARGE: '파일이 너무 큽니다.',
  UNSUPPORTED_MEDIA_TYPE: '지원하는 형식은 .xlsx, .csv, .hwpx, .hwp입니다.',
  PACK_UNSUPPORTED: '아직 지원하지 않는 업무 분야예요.',
  INVALID_RESPONSE: '입력한 내용을 다시 확인해 주세요.',
  INVALID_REQUEST: '입력한 내용을 다시 확인해 주세요.',
  LLM_REFUSED: 'AI가 이 문서에 답하지 않았어요. 문서 내용을 확인해 주세요.',
  LLM_OUTPUT_INVALID: 'AI 답이 형식에 맞지 않았어요. 다시 해 주세요.',
  LLM_UNAVAILABLE: 'AI에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.',
  BUDGET_EXCEEDED: '문서가 AI 사용 한도를 넘었어요. 요구사항을 나눠 올려 주세요.',
  EXTRACTION_FAILED: '문서를 읽지 못했습니다. 다른 파일로 다시 시도해 주세요.',
  INTERNAL: '문제가 생겼어요. 잠시 뒤 다시 해 주세요.',
}

/** 화면에 보여 줄 한글 안내 */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.body?.message) return err.body.message
    const code = err.code
    if (code === 'NETWORK') return '서버에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.'
    if (code === 'UNKNOWN') return '요청을 처리하지 못했어요. 잠시 뒤 다시 해 주세요.'
    return FALLBACK_MESSAGES[code]
  }
  return '알 수 없는 오류가 발생했습니다.'
}

/** 오류 뒤에 사용자에게 권할 행동 */
export type NextAction = 'refresh' | 'retry' | 'reupload' | 'none'

export function nextAction(code: ErrorCode | 'NETWORK' | 'UNKNOWN', retryable = false): NextAction {
  switch (code) {
    case 'RUN_REVISION_CONFLICT':
    case 'INTERRUPT_STALE':
    case 'EVENT_REPLAY_EXPIRED':
      return 'refresh' // 최신 상태를 다시 조회
    case 'UPLOAD_TOO_LARGE':
    case 'UNSUPPORTED_MEDIA_TYPE':
    case 'EXTRACTION_FAILED':
      return 'reupload' // 다른 파일로
    case 'NETWORK':
    case 'ARTIFACT_NOT_READY':
      return 'retry'
    default:
      return retryable ? 'retry' : 'none'
  }
}
