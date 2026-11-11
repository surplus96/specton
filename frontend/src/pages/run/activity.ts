// 진행 기록 규칙(이벤트 글·연결 상태·경과 시간). AI Workspace와 설계 중 진행 시간(Elapsed)이 쓴다.
// 이벤트(SSE) 종류·내용은 docs/06-api.md 「SSE」를 따른다. 이벤트는 기록으로만 보이고,
// 화면 판단(어느 화면을 보일지)은 여전히 상태 조회 결과로 한다 (followRun.ts).
import type { SseEvent, SseEventName } from '../../api/types.ts'
import type { Tone } from '../../theme.ts'
import { STATUS_LABEL } from '../workspace/rules.ts'
import type { Connection } from './followRun.ts'
import { PROGRESS_STAGES } from './screens.ts'

/** 이벤트 종류마다 보일 글과 색. 색만으로 구분하지 않도록 글을 함께 쓴다. */
export const EVENT_LABEL: Record<SseEventName, { label: string; tone: Tone }> = {
  status: { label: '진행', tone: 'info' },
  interrupt: { label: '확인 필요', tone: 'warning' },
  artifact: { label: '문서 생성', tone: 'success' },
  error: { label: '문제', tone: 'danger' },
  completed: { label: '완료', tone: 'success' },
  cancelled: { label: '취소', tone: 'neutral' },
}

/** 이벤트 연결 상태 */
export const CONNECTION_LABEL: Record<Connection, { label: string; tone: Tone }> = {
  connecting: { label: '연결 중', tone: 'neutral' },
  live: { label: '실시간으로 보는 중', tone: 'info' },
  retrying: { label: '다시 연결 중', tone: 'warning' },
  closed: { label: '기록 끝남', tone: 'neutral' },
}

/**
 * stage 값 → 화면 이름. 서버는 실행 상태 이름(designing·failed 등)을 stage로 보낸다 (runner).
 * 진행 단계 이름을 먼저 쓰고, 없으면 실행 상태 이름, 그래도 모르는 값은 그대로 보인다.
 */
const STAGE_TITLE: Record<string, string> = {
  ...STATUS_LABEL,
  ...Object.fromEntries(PROGRESS_STAGES.map((s) => [s.stage, s.title])),
  awaiting_input: '원문 확인',
  awaiting_requirements: '요구사항 확인',
  awaiting_review: '최종 승인',
  review: '최종 승인',
}

export function stageTitle(stage: string | null | undefined): string | null {
  if (!stage) return null
  return STAGE_TITLE[stage] ?? stage
}

export type ActivityItem = {
  /** 처음 이벤트의 id. 화면 key로 쓴다 */
  id: number
  event: SseEventName
  label: string
  tone: Tone
  stage: string | null
  message: string
  /** 같은 내용이 이어서 온 횟수 (1이면 한 번) */
  count: number
  /** 이 화면이 마지막으로 받은 시각(ms). 모르면 null */
  at: number | null
}

/**
 * 패널에 보일 기록. 최신이 맨 위다 (강의장 화면에서 새 소식이 바로 보이게).
 * 종류·단계·문장이 모두 같은 이벤트가 이어지면 한 줄로 합치고 횟수를 센다.
 */
/** 서버가 단계(노드)마다 남기는 시작·끝 기록인지 (payload.node가 있는 status) */
export function isNodeEvent(e: SseEvent): boolean {
  return e.event === 'status' && typeof e.data.payload?.node === 'string'
}

export function activityItems(events: readonly SseEvent[], receivedAt: Record<number, number> = {}): ActivityItem[] {
  const items: ActivityItem[] = []
  for (const e of events) {
    // 단계 하나하나의 시작·끝 기록(「a01 시작」·「parse 종료」)은 AI Workspace용이라 여기서는 뺀다
    if (isNodeEvent(e)) continue
    const stage = stageTitle(e.data.stage)
    const last = items[items.length - 1]
    if (last && last.event === e.event && last.stage === stage && last.message === e.data.message) {
      last.count += 1
      last.at = receivedAt[e.id] ?? last.at
      continue
    }
    const { label, tone } = EVENT_LABEL[e.event]
    items.push({ id: e.id, event: e.event, label, tone, stage, message: e.data.message, count: 1, at: receivedAt[e.id] ?? null })
  }
  return items.reverse()
}

/** 경과 시간 글자: 45초, 2분 05초, 1시간 03분 */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  if (h > 0) return `${h}시간 ${pad(m)}분`
  if (m > 0) return `${m}분 ${pad(s)}초`
  return `${s}초`
}

/** 받은 시각 글자 (14:03:12) */
export function clockTime(ms: number): string {
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
