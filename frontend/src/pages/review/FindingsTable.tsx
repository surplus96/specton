import { Flex, Table, Typography } from 'antd'
import StatusTag from '../../layout/StatusTag.tsx'
import type { Tone } from '../../theme.ts'
import type { TableColumnsType } from 'antd'
import type { Finding, Severity } from '../../api/viewItems.ts'
import { SEVERITY_LABEL, STAGE_LABEL, sortFindings, sourceText, targetText } from './rules.ts'

// 검토 지적 표. 최종 검토(UI-06)와 결과 작업공간(UI-05) 「검토」 탭이 같이 쓴다.
// 심각도는 색만이 아니라 글(차단·주요·참고)로도 보인다 (docs/09 표현 기준).
type Props = {
  findings: Finding[]
  names: Map<string, string>
}

const SEVERITY_TONE: Record<Severity, Tone> = { critical: 'danger', major: 'warning', minor: 'neutral' }

function FindingsTable({ findings, names }: Props) {
  if (findings.length === 0) return <Typography.Text type="secondary">지적이 없습니다.</Typography.Text>

  const columns: TableColumnsType<Finding> = [
    {
      title: '심각도',
      dataIndex: 'severity',
      width: 84,
      render: (s: Severity) => <StatusTag tone={SEVERITY_TONE[s]}>{SEVERITY_LABEL[s]}</StatusTag>,
    },
    {
      title: '대상',
      key: 'targets',
      width: 170,
      render: (_, f) => (
        <Flex vertical>
          {f.targets.map((t) => (
            <span key={`${t.kind}:${t.id}`}>{targetText(t, names)}</span>
          ))}
        </Flex>
      ),
    },
    {
      title: '근거',
      key: 'evidence',
      width: 240,
      render: (_, f) => (
        <Flex vertical gap={4}>
          {f.evidence.map((e, i) => (
            <span key={i}>
              {e.req_id && <Typography.Text type="secondary">{e.req_id} </Typography.Text>}「{e.quote}」
            </span>
          ))}
        </Flex>
      ),
    },
    { title: '제안', dataIndex: 'suggestion' },
    {
      title: '출처 · 돌아갈 단계',
      key: 'source',
      width: 170,
      render: (_, f) => (
        <Flex vertical>
          <span>{sourceText(f)}</span>
          <Typography.Text type="secondary">{f.kind === 'technical_identifier' ? '참고 · 기술 식별자 사용' : f.target_stage ? STAGE_LABEL[f.target_stage] : '판단 필요'}</Typography.Text>
        </Flex>
      ),
    },
  ]

  return (
    <Table rowKey="id" size="small" pagination={false} columns={columns} dataSource={sortFindings(findings)} scroll={{ x: 960 }} />
  )
}

export default FindingsTable
