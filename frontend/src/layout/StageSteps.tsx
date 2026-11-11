// 화면 단계 표시줄 (UI-01~07, docs/09-ui-flow.md). 지난 단계는 진한 선, 지금 단계는 라임.
// 실패·취소로 실제로 거치지 않은 확인 화면은 지난 단계로 칠하지 않는다(unreached).
export const SCREENS = [
  { id: 'UI-01', title: '실행 시작' },
  { id: 'UI-02', title: '추출 확인' },
  { id: 'UI-03', title: '분석 확인' },
  { id: 'UI-04', title: '설계 진행' },
  { id: 'UI-05', title: '결과 작업공간' },
  { id: 'UI-06', title: '최종 검토' },
  { id: 'UI-07', title: '다운로드' },
] as const

export type ScreenId = (typeof SCREENS)[number]['id']

export type StepState = 'done' | 'now' | 'skipped' | 'available' | 'todo'
const STATE_TEXT: Record<StepState, string> = { done: '지남', now: '지금', skipped: '생략', available: '결과 있음', todo: '' }
function StageSteps({ steps }: { steps: Record<ScreenId, StepState> }) {
  return (
    <ol className="stage-strip" aria-label="화면 단계" style={{ listStyle: 'none', padding: 0 }}>
      {SCREENS.map((s, i) => {
        const state = steps[s.id]
        return (
          <li key={s.id} className={`stage-strip__item stage-strip__item--${state}`} aria-current={state === 'now' ? 'step' : undefined}>
            <div className="stage-strip__bar" />
            <span><b>{String(i + 1).padStart(2, '0')}</b>{s.title}
              <small className="stage-strip__state">{STATE_TEXT[state] && ` · ${STATE_TEXT[state]}`}</small>
            </span>
          </li>
        )
      })}
    </ol>
  )
}
export default StageSteps
