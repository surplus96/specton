import type { DesignItem, Finding } from '../../api/viewItems.ts'
import Icon, { type IconName } from '../../layout/Icon.tsx'
import { colors, tones, weights } from '../../theme.ts'
import { resultCounts } from './summary.ts'

// 결과 한눈에 보기: 요구사항에서 설계까지 몇 개가 만들어졌는지 큰 숫자로 (발표·프로젝터용).
// 모양은 Figma 시안의 요약 카드(아이콘 + 이름 + 큰 숫자), 색은 theme.ts 그대로:
// 흰 카드 + 테두리, 아이콘은 파랑. 차단 지적이 있으면 그 카드만 진한 빨강 면 + 흰 글자.
type Props = {
  design: readonly DesignItem[]
  /** null이면 검토 지적을 불러오지 못한 것. 지적 카드 대신 안내를 보인다 */
  findings: readonly Finding[] | null
}

type Card = { label: string; value: number; icon: IconName; danger?: boolean }

function ResultSummary({ design, findings }: Props) {
  const c = resultCounts(design, findings ?? [])
  const all: Card[] = [
    { label: '요구사항', value: c.requirements, icon: 'file' },
    { label: '기능', value: c.functions, icon: 'list' },
    { label: '엔티티 (테이블)', value: c.entities, icon: 'database' },
    { label: '관계', value: c.relationships, icon: 'link' },
    { label: '검토 지적', value: c.findings, icon: 'check' },
    { label: '차단 지적', value: c.blocking, icon: 'alert', danger: c.blocking > 0 },
  ]
  // 지적을 못 불러왔는데 「0건」으로 보이면 안 되므로 지적 카드는 뺀다
  const cards = findings === null ? all.filter((card) => card.icon !== 'check' && card.icon !== 'alert') : all
  return (
    <section
      aria-label="결과 한눈에 보기"
      style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}
    >
      {cards.map((card) => (
        <div
          key={card.label}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            background: card.danger ? tones.danger.bg : colors.canvas,
            color: card.danger ? tones.danger.fg : colors.ink,
            border: `1.5px solid ${card.danger ? tones.danger.bg : colors.border}`,
            borderRadius: 16,
            padding: '14px 16px',
          }}
        >
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 44,
              height: 44,
              flex: 'none',
              borderRadius: 12,
              color: card.danger ? tones.danger.fg : colors.primary,
              border: `1.5px solid ${card.danger ? tones.danger.fg : colors.primary}`,
            }}
          >
            <Icon name={card.icon} size={22} />
          </span>
          <div>
            <div style={{ fontWeight: weights.strong, color: card.danger ? tones.danger.fg : colors.inkMuted }}>{card.label}</div>
            <div style={{ fontSize: 36, fontWeight: weights.display, lineHeight: 1.1 }}>{card.value}</div>
          </div>
        </div>
      ))}
      {findings === null && (
        <div role="status" style={{ alignSelf: 'center', color: colors.inkMuted }}>
          검토 지적을 불러오지 못했습니다. 파일은 그대로 내려받을 수 있습니다.
        </div>
      )}
    </section>
  )
}

export default ResultSummary
