import type { Finding, Severity } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import { colors, weights, type Tone } from '../../theme.ts'
import { SEVERITY_LABEL, severityGroups } from './rules.ts'

// 「검토가 필요한 항목」 (Figma 시안의 같은 이름 목록): 심각도마다 건수·대표 대상을 한 줄씩.
// 누르면 아래 지적 표를 그 심각도만 보이게 좁히고, 다시 누르면 전체로 돌아간다.
type Props = {
  findings: readonly Finding[]
  names: Map<string, string>
  selected: Severity | null
  onSelect: (severity: Severity | null) => void
}

const TONE: Record<Severity, Tone> = { critical: 'danger', major: 'warning', minor: 'neutral' }
const MEANING: Record<Severity, string> = {
  critical: '승인 전에 반드시 고칠 지적',
  major: '고치는 것을 권하는 지적',
  minor: '참고할 지적',
}

function ReviewSummary({ findings, names, selected, onSelect }: Props) {
  const groups = severityGroups(findings, names)
  if (groups.length === 0) return null
  return (
    <section aria-label="검토가 필요한 항목" style={{ border: `1.5px solid ${colors.border}`, borderRadius: 16, padding: 8 }}>
      {groups.map((g) => {
        const active = selected === g.severity
        return (
          <button
            key={g.severity}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(active ? null : g.severity)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              width: '100%',
              textAlign: 'left',
              cursor: 'pointer',
              font: 'inherit',
              color: colors.ink,
              background: active ? colors.primarySoft : 'transparent',
              border: `1.5px solid ${active ? colors.primary : 'transparent'}`,
              borderRadius: 12,
              padding: '10px 12px',
            }}
          >
            <StatusTag tone={TONE[g.severity]}>{SEVERITY_LABEL[g.severity]}</StatusTag>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: 'block', fontWeight: weights.strong }}>{MEANING[g.severity]}</span>
              <span style={{ display: 'block', color: colors.inkMuted, fontSize: 15 }}>{g.sample}</span>
            </span>
            <span style={{ fontSize: 24, fontWeight: weights.display }}>{g.count}</span>
            <span style={{ color: colors.inkMuted, display: 'inline-flex' }}>
              <Icon name="chevron" size={18} />
            </span>
          </button>
        )
      })}
    </section>
  )
}

export default ReviewSummary
