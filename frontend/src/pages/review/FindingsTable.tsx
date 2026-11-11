import type { Finding, Severity } from '../../api/viewItems.ts'
import StatusTag from '../../layout/StatusTag.tsx'
import type { Tone } from '../../theme.ts'
import DataTable from '../../ui/DataTable.tsx'
import { SEVERITY_LABEL, STAGE_LABEL, sortFindings, sourceText, targetText } from './rules.ts'

// 검토 지적 표. 최종 검토(UI-06)와 결과 작업공간(UI-05) 「검토」 탭이 같이 쓴다.
// 심각도는 색만이 아니라 글(차단·주요·참고)로도 보인다. 데이터에 없는 지적을 만들어 보이지 않는다.
type Props = {
  findings: Finding[]
  names: Map<string, string>
}

const SEVERITY_TONE: Record<Severity, Tone> = { critical: 'danger', major: 'warning', minor: 'neutral' }

function FindingsTable({ findings, names }: Props) {
  return (
    <DataTable<Finding>
      label="검토 지적"
      rows={sortFindings(findings)}
      rowKey={(f) => f.id}
      minWidth={980}
      pageSize={findings.length > 30 ? 30 : undefined}
      empty="지적이 없어요."
      columns={[
        { key: 'sev', title: '심각도', width: 84, render: (f) => <StatusTag tone={SEVERITY_TONE[f.severity]}>{SEVERITY_LABEL[f.severity]}</StatusTag> },
        {
          key: 'targets',
          title: '대상',
          width: 180,
          render: (f) => (
            <div className="stack-sm" style={{ gap: 2 }}>
              {f.targets.map((t) => (
                <span key={`${t.kind}:${t.id}`}>{targetText(t, names)}</span>
              ))}
            </div>
          ),
        },
        {
          key: 'evidence',
          title: '근거',
          width: 260,
          render: (f) => (
            <div className="stack-sm" style={{ gap: 4 }}>
              {f.evidence.map((e, i) => (
                <span key={i}>
                  {e.req_id && <span className="mono subtle">{e.req_id} </span>}「{e.quote}」
                </span>
              ))}
            </div>
          ),
        },
        { key: 'suggestion', title: '제안', render: (f) => f.suggestion },
        {
          key: 'source',
          title: '출처 · 돌아갈 단계',
          width: 180,
          render: (f) => (
            <div className="stack-sm" style={{ gap: 2 }}>
              <span>{sourceText(f)}</span>
              <span className="subtle" style={{ fontSize: 13 }}>
                {f.kind === 'technical_identifier' ? '참고 · 기술 식별자 사용' : f.target_stage ? STAGE_LABEL[f.target_stage] : '판단 필요'}
              </span>
            </div>
          ),
        },
      ]}
    />
  )
}

export default FindingsTable
