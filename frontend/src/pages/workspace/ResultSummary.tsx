import type { DesignItem, Finding } from '../../api/viewItems.ts'
import Icon, { type IconName } from '../../layout/Icon.tsx'
import { resultCounts } from './summary.ts'

// 결과 한눈에 보기: 요구사항에서 설계까지 몇 개가 만들어졌는지 큰 숫자로.
// 차단 지적이 있으면 그 칸만 진한 면 + 흰 글자.
type Props = {
  design: readonly DesignItem[]
  /** null이면 검토 지적을 불러오지 못한 것. 지적 칸 대신 안내를 보인다 */
  findings: readonly Finding[] | null
}

type Card = { label: string; value: number; icon: IconName; danger?: boolean; finding?: boolean }

function ResultSummary({ design, findings }: Props) {
  const c = resultCounts(design, findings ?? [])
  const all: Card[] = [
    { label: '요구사항', value: c.requirements, icon: 'file' },
    { label: '기능', value: c.functions, icon: 'list' },
    { label: '테이블', value: c.entities, icon: 'database' },
    { label: '관계', value: c.relationships, icon: 'link' },
    { label: '검토 의견', value: c.findings, icon: 'check', finding: true },
    { label: '꼭 고칠 것', value: c.blocking, icon: 'alert', danger: c.blocking > 0, finding: true },
  ]
  // 지적을 못 불러왔는데 「0건」으로 보이면 안 되므로 지적 칸은 뺀다
  const cards = findings === null ? all.filter((card) => !card.finding) : all
  return (
    <section aria-label="결과 한눈에 보기" className="stats">
      {cards.map((card) => (
        <div key={card.label} className={`stat${card.danger ? ' stat--danger' : ''}`}>
          <span className="stat__label">
            <Icon name={card.icon} size={16} />
            {card.label}
          </span>
          <span className="stat__value">{card.value}</span>
        </div>
      ))}
      {findings === null && (
        <div role="status" className="muted" style={{ alignSelf: 'center', fontSize: 14 }}>
          검토 지적을 불러오지 못했어요. 파일은 그대로 내려받을 수 있어요.
        </div>
      )}
    </section>
  )
}

export default ResultSummary
