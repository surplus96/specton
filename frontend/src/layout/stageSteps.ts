import type { ScreenId, StepState } from './StageSteps.tsx'

/** 표시줄 칸. 여러 화면을 한 칸에 묶을 수 있다 */
export const STEPS: readonly { ids: readonly ScreenId[]; title: string }[] = [
  { ids: ['UI-01'], title: '파일 올리기' },
  { ids: ['UI-02'], title: '원문 확인' },
  { ids: ['UI-03'], title: '요구사항 확인' },
  { ids: ['UI-04'], title: '설계 중' },
  { ids: ['UI-05', 'UI-06'], title: '결과 보기 및 최종 승인' },
  { ids: ['UI-07'], title: '내려받기' },
]

/** 묶은 화면들의 상태를 한 칸 상태로: 지금 > 마지막 화면 완료 > 결과 있음 > 모두 건너뜀 > 대기 */
export function mergedState(states: readonly StepState[]): StepState {
  if (states.includes('now')) return 'now'
  if (states[states.length - 1] === 'done') return 'done'
  if (states.includes('available')) return 'available'
  if (states.length > 0 && states.every((s) => s === 'skipped')) return 'skipped'
  if (states.every((s) => s === 'done' || s === 'skipped')) return 'done'
  return 'todo'
}
