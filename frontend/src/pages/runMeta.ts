// 실행 목록·카드 표시 규칙 (시작 화면·지난 작업·사이드바). 화면 코드와 분리해 테스트한다.
import type { RunState } from '../api/types.ts'
import type { Tone } from '../theme.ts'
import { isFinished } from './run/screens.ts'
import { STATUS_LABEL } from './workspace/rules.ts'

export type RunBadge = { tone: Tone; text: string; dot?: boolean; check?: boolean }

const AWAITING: ReadonlySet<RunState> = new Set(['awaiting_input', 'awaiting_requirements', 'awaiting_review'])

/** 카드 상태 칩: 사람 확인을 기다리면 「확인 필요」(라임 점), 끝났으면 「승인 완료」 등 */
export function runBadge(status: RunState): RunBadge {
  if (AWAITING.has(status)) return { tone: 'info', text: '확인 필요', dot: true }
  switch (status) {
    case 'completed':
      return { tone: 'neutral', text: '승인 완료', check: true }
    case 'failed':
      return { tone: 'danger', text: '실패' }
    case 'cancelled':
      return { tone: 'neutral', text: '취소됨' }
    case 'cancel_requested':
      return { tone: 'warning', text: '취소 중' }
    case 'queued':
      return { tone: 'neutral', text: '대기 중' }
    default:
      return { tone: 'info', text: '진행 중' }
  }
}

export function isAwaiting(status: RunState): boolean {
  return AWAITING.has(status)
}

/** 아직 끝나지 않은 실행 (지금 진행 중 카드에 보일 것) */
export function isActive(status: RunState): boolean {
  return !isFinished(status)
}

/** 시안의 네 단계 (01 문서 읽기 · 02 요구사항 정리 · 03 초안 생성 · 04 검토와 승인) */
export const FOUR_STEPS = ['문서 읽기', '요구사항 정리', '초안 생성', '검토와 승인'] as const

const STEP_OF: Record<RunState, number> = {
  queued: 0,
  parsing: 0,
  awaiting_input: 0,
  analysing: 1,
  awaiting_requirements: 1,
  designing: 2,
  generating: 2,
  reviewing: 2,
  awaiting_review: 3,
  exporting: 3,
  completed: 4,
  failed: -1,
  cancel_requested: -1,
  cancelled: -1,
}

const STEP_OF_STAGE: Record<string, number> = {
  parsing: 0,
  analysing: 1,
  designing: 2,
  generating: 2,
  reviewing: 2,
  review: 3,
  exporting: 3,
}

export type StepState = 'done' | 'now' | 'wait' | 'fail' | 'todo'

/**
 * 네 단계 각각의 상태. 사람 확인을 기다리는 단계는 'wait'(라임), 실패·취소는 멈춘 단계를 'fail'.
 * 실패·취소 때 서버가 stage를 비우면 어디서 멈췄는지 모르므로 전부 'todo'로 둔다(지어내지 않는다).
 */
export function fourStepStates(status: RunState, stage?: string | null): StepState[] {
  let at = STEP_OF[status]
  const stopped = at < 0
  if (stopped) at = stage ? (STEP_OF_STAGE[stage] ?? -1) : -1
  return FOUR_STEPS.map((_, i) => {
    if (status === 'completed' || i < at) return 'done'
    if (i > at || at < 0) return 'todo'
    if (stopped) return 'fail'
    return AWAITING.has(status) ? 'wait' : 'now'
  })
}

/** 카드 아래 한 줄 안내. 확인 요청 문장이 있으면 그것을 쓴다 */
export function runMessage(status: RunState, interruptMessage?: string | null): string {
  if (interruptMessage) return interruptMessage
  switch (status) {
    case 'awaiting_input':
      return '문서에서 읽은 원문 중 확인할 것이 있어요.'
    case 'awaiting_requirements':
      return '정리한 요구사항 중 확인할 것이 있어요.'
    case 'awaiting_review':
      return '설계 초안을 만들었어요. 검사 결과를 확인하고 승인해 주세요.'
    case 'completed':
      return '승인을 마쳤어요. 형식별로 내려받을 수 있어요.'
    case 'failed':
      return '실행이 멈췄어요. 원인을 확인해 주세요.'
    case 'cancelled':
      return '실행을 취소했어요.'
    case 'queued':
      return '다른 실행이 끝나면 시작해요.'
    case 'cancel_requested':
      return '취소를 요청했어요. 진행 중인 작업이 끝나면 멈춰요.'
    default:
      return `지금 ${STATUS_LABEL[status]}이에요. 확인이 필요한 곳이 생기면 멈추고 알려 드려요.`
  }
}

/** 카드의 행동 버튼 글자 */
export function runAction(status: RunState): string {
  switch (status) {
    case 'awaiting_input':
    case 'awaiting_requirements':
      return '확인하기'
    case 'awaiting_review':
      return '초안 검토하기'
    case 'completed':
      return '결과 보기'
    case 'failed':
    case 'cancelled':
      return '자세히 보기'
    default:
      return '진행 보기'
  }
}

/** 날짜 2026.05.12 */
export function dotDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`
}

/** 날짜와 시각 2026.05.12 14:03 */
export function dotDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${dotDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 설계안 차수. revision은 0부터 세므로 사람에게는 1차부터 보인다 (revision 0 → 「1차 설계안」) */
export function revisionText(revision: number): string {
  return `${revisionNumber(revision)}차 설계안`
}

/** 카드 배지처럼 좁은 곳에 쓰는 짧은 차수 (revision 1 → 「2차」) */
export function revisionBadge(revision: number): string {
  return `${revisionNumber(revision)}차`
}

function revisionNumber(revision: number): number {
  return Number.isInteger(revision) && revision >= 0 ? revision + 1 : 1
}

/** 이 브라우저에서 올리지 않아 파일 이름을 모르는 실행의 이름. 실행 ID 대신 시작 시각으로 구분한다 */
export function untitledRunName(createdAt?: string | null): string {
  const at = createdAt ? dotDateTime(createdAt) : ''
  return at ? `이름 없는 작업 · ${at}` : '이름 없는 작업'
}

/** 검색: 파일 이름·상태 이름·실행 ID·날짜에 검색어가 들어 있으면 남긴다 (대소문자 무시, 공백으로 나눈 낱말 모두) */
export function matchesQuery(
  run: { run_id: string; status: RunState; created_at: string },
  fileName: string | null,
  query: string,
): boolean {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return true
  const hay = [fileName ?? '', STATUS_LABEL[run.status], runBadge(run.status).text, run.run_id, dotDateTime(run.created_at)]
    .join(' ')
    .toLowerCase()
  return words.every((w) => hay.includes(w))
}
