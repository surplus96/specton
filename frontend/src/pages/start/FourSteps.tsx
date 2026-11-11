import { FOUR_STEPS, type StepState } from '../runMeta.ts'

// 시안의 네 단계 진행 막대 (01 문서 읽기 … 04 검토와 승인). 지금 단계는 굵게, 사람 확인을 기다리면 라임.
const STATE_TEXT: Record<StepState, string> = {
  done: '완료',
  now: '진행 중',
  wait: '확인 필요',
  fail: '멈춤',
  todo: '대기',
}

function FourSteps({ states }: { states: StepState[] }) {
  return (
    <ol className="steps4" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {FOUR_STEPS.map((title, i) => {
        const s = states[i]
        const cls = s === 'now' || s === 'wait' ? 'steps4__item--now' : `steps4__item--${s}`
        return (
          <li key={title} className={`steps4__item ${cls}${s === 'wait' ? ' steps4__item--wait' : ''}`}>
            <div className="steps4__bar">
              <i />
            </div>
            <span>
              <span className="mono" style={{ marginRight: 8 }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              {title}
              <span className="sr-only"> · {STATE_TEXT[s]}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export default FourSteps
