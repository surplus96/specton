import type { DesignItem, Finding } from '../../api/viewItems.ts'
import { colors, tones, weights } from '../../theme.ts'
import { resultCounts } from './summary.ts'

// 결과 한눈에 보기: 요구사항에서 설계까지 몇 개가 만들어졌는지 큰 숫자로 (발표·프로젝터용).
type Props = {
  design: readonly DesignItem[]
  findings: readonly Finding[]
}

function ResultSummary({ design, findings }: Props) {
  const c = resultCounts(design, findings)
  const cards = [
    { label: '요구사항', value: c.requirements },
    { label: '기능', value: c.functions },
    { label: '엔티티 (테이블)', value: c.entities },
    { label: '관계', value: c.relationships },
    { label: '검토 지적', value: c.findings },
    { label: '차단 지적', value: c.blocking, danger: c.blocking > 0 },
  ]
  return (
    <section
      aria-label="결과 한눈에 보기"
      style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12 }}
    >
      {cards.map((card) => (
        <div
          key={card.label}
          style={{
            background: card.danger ? tones.danger.bg : colors.navy,
            color: colors.onDark,
            borderRadius: 16,
            padding: '16px 18px',
          }}
        >
          <div style={{ fontSize: 40, fontWeight: weights.display, lineHeight: 1.1 }}>{card.value}</div>
          <div style={{ marginTop: 4, fontWeight: weights.strong, color: card.danger ? colors.onDark : colors.onDarkMuted }}>
            {card.label}
          </div>
        </div>
      ))}
    </section>
  )
}

export default ResultSummary
