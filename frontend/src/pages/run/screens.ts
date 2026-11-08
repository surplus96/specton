// 실행 상태 → 화면 규칙. 화면 코드(RunPage)와 분리해 테스트한다.
// 상태 목록은 계약(RunState), 화면 대응은 docs/09-ui-flow.md 화면 목록·흐름도를 따른다.
import type { ApiErrorBody, InterruptKind, RunState, SseEvent } from '../../api/types.ts'
import type { ScreenId } from '../../layout/StageSteps.tsx'

/** 상태마다 보일 화면. Record라서 계약에 상태가 늘면 여기서 타입 오류가 난다. */
const SCREEN_OF: Record<RunState, ScreenId> = {
  queued: 'UI-04',
  parsing: 'UI-04',
  awaiting_input: 'UI-02', // 추출 확인 (HITL)
  analysing: 'UI-04',
  awaiting_requirements: 'UI-03', // 분석 확인 (HITL 1)
  designing: 'UI-04',
  generating: 'UI-04',
  reviewing: 'UI-04',
  awaiting_review: 'UI-06', // 최종 검토 (HITL 2)
  exporting: 'UI-04', // 승인 뒤 파일 생성 중 = 결과 보기(진행) (강의 09)
  completed: 'UI-07',
  // 실패·취소는 진행 화면에서 원인과 다음 행동을 보인다 (docs/09 UI-04 「호출 실패·한도 초과 안내」)
  failed: 'UI-04',
  cancel_requested: 'UI-04',
  cancelled: 'UI-04',
}

/** 확인 요청 종류마다 보일 화면 */
const SCREEN_OF_INTERRUPT: Record<InterruptKind, ScreenId> = {
  extraction: 'UI-02',
  requirements: 'UI-03',
  review: 'UI-06',
}

/**
 * 지금 보일 화면. 확인 화면은 status보다 interrupt.kind로 고른다 (구현 가이드 강의 09).
 * interrupt는 사람 확인을 기다릴 때만 값이 있다.
 */
export function screenFor(status: RunState, interrupt?: InterruptKind | null): ScreenId {
  if (interrupt && !isFinished(status)) return SCREEN_OF_INTERRUPT[interrupt]
  return SCREEN_OF[status]
}

/** 더 바뀌지 않는 상태. 이 상태가 되면 이벤트 연결을 닫는다. */
export const FINISHED_STATES: ReadonlySet<RunState> = new Set(['completed', 'failed', 'cancelled'])

export function isFinished(status: RunState): boolean {
  return FINISHED_STATES.has(status)
}

/** 취소 버튼을 보일 상태. 끝났거나 이미 취소를 요청했으면 숨긴다. */
export function canCancel(status: RunState): boolean {
  return !isFinished(status) && status !== 'cancel_requested'
}

/** UI-04 진행 단계. stage 값은 백엔드 runner가 저장하는 단계 이름이다. */
export const PROGRESS_STAGES = [
  { stage: 'parsing', title: '문서 읽기' },
  { stage: 'analysing', title: '요구사항 분석' },
  { stage: 'designing', title: '설계' },
  { stage: 'generating', title: '산출물 생성' },
  { stage: 'reviewing', title: '검토' },
] as const

/** 지금 몇 번째 진행 단계인지. 대기(queued)는 -1, 최종 검토 이후는 마지막 단계 다음. */
export function progressIndex(stage: string | null | undefined): number {
  if (!stage) return -1
  const index = PROGRESS_STAGES.findIndex((s) => s.stage === stage)
  if (index >= 0) return index
  return stage === 'review' || stage === 'exporting' ? PROGRESS_STAGES.length : -1
}

/**
 * UI-04에 보일 단계. 서버는 실행이 실패·취소되면 `run.stage`를 비우므로,
 * 그때는 마지막 진행 이벤트의 단계를 써서 실패한 단계에 표시가 가게 한다.
 */
export function displayStage(stage: string | null | undefined, events: readonly SseEvent[]): string | null {
  if (stage && progressIndex(stage) >= 0) return stage
  const last = [...events].reverse().find((e) => progressIndex(e.data.stage) >= 0)
  return last?.data.stage ?? stage ?? null
}

/** 분석 확인을 건너뛰었을 때 서버가 남기는 문구 (docs/06 「SSE」, ADR-0015) */
export const SKIPPED_REQUIREMENTS_MESSAGE = '확인할 항목이 없어 분석 확인을 생략했습니다'

/** UI-04 「분석 확인 생략(확인할 항목 없음)」 표시 여부 */
export function requirementsCheckSkipped(events: readonly SseEvent[]): boolean {
  return events.some(
    (e) => e.event === 'status' && e.data.stage === 'designing' && e.data.message === SKIPPED_REQUIREMENTS_MESSAGE,
  )
}

/** 실패 안내. 「자세히 보기」 문장(detail)은 상태 조회에 없고 SSE error 이벤트에만 있다. */
export function failureOf(
  error: ApiErrorBody | null | undefined,
  events: readonly SseEvent[],
): { code: string; message: string; retryable: boolean; detail: string | null } | null {
  const last = [...events].reverse().find((e) => e.event === 'error')
  const payload = last?.data.payload ?? {}
  const code = error?.code ?? (typeof payload.code === 'string' ? payload.code : null)
  if (!code) return null
  return {
    code,
    message: error?.message ?? last?.data.message ?? '실행이 실패했습니다.',
    retryable: error?.retryable ?? payload.retryable === true,
    detail: typeof payload.detail === 'string' ? payload.detail : null,
  }
}

/** 화면에 보일 최근 진행 문장. 같은 문장이 이어지면 하나만. */
export function recentMessages(events: readonly SseEvent[], limit = 8): string[] {
  const messages: string[] = []
  for (const e of events) {
    if (messages[messages.length - 1] !== e.data.message) messages.push(e.data.message)
  }
  return messages.slice(-limit)
}
