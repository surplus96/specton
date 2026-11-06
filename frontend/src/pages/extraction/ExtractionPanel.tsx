import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Checkbox, Collapse, Flex, Input, Popconfirm, Radio, Spin, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import type { ExtractionBlock } from '../../api/viewItems.ts'
import PageCard from '../../layout/PageCard.tsx'
import { useResume } from '../run/useResume.ts'
import {
  STATUS_LABEL,
  STOP_RESPONSE,
  buildResponse,
  initialDecisions,
  locationText,
  problems,
  relatedWarnings,
  skippedSheets,
  sortBlocks,
  type Decision,
  type Decisions,
} from './rules.ts'

// UI-02 추출 확인 (docs/09, ADR-0015, 구현 가이드 강의 10).
// 원문은 고치지 않고 확인 또는 제외만 한다. 확인할 블록(review·fail)을 먼저 보인다.
type Props = {
  run: RunStatus
  events: SseEvent[]
  onChanged: () => Promise<void>
}

const STATUS_COLOR: Record<ExtractionBlock['extraction_status'], string> = {
  fail: 'red',
  review: 'orange',
  pass: 'default',
}

function ExtractionPanel({ run, events, onChanged }: Props) {
  const interruptId = run.interrupt?.interrupt_id
  const [blocks, setBlocks] = useState<ExtractionBlock[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [decisions, setDecisions] = useState<Decisions>({})
  const { send, sending, error: actionError, notice, reloadKey, reload, canAnswer } = useResume(run, onChanged)

  // 확인 요청이 바뀌면(다른 곳에서 답한 뒤 새 요청 등) 블록을 다시 읽고 결정을 처음으로 돌린다
  useEffect(() => {
    let alive = true
    setBlocks(null)
    setLoadError(null)
    getView(run.run_id, 'extraction', run.revision)
      .then((view) => {
        if (!alive) return
        const items = view.items as ExtractionBlock[]
        setBlocks(items)
        setDecisions(initialDecisions(items))
      })
      .catch((err: unknown) => alive && setLoadError(err))
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, interruptId, reloadKey])

  const sorted = useMemo(() => (blocks ? sortBlocks(blocks) : []), [blocks])
  const toCheck = sorted.filter((b) => b.extraction_status !== 'pass')
  const passed = sorted.filter((b) => b.extraction_status === 'pass')
  const blocking = blocks ? problems(blocks, decisions) : []
  const warnings = blocks ? relatedWarnings(blocks, decisions) : []
  const sheets = skippedSheets(events.map((e) => e.data.payload))

  const decide = (blockId: string, change: Partial<Decision>) =>
    setDecisions((prev) => ({ ...prev, [blockId]: { ...prev[blockId], ...change } }))

  const columns: TableColumnsType<ExtractionBlock> = [
    {
      title: '판정',
      dataIndex: 'extraction_status',
      width: 96,
      render: (status: ExtractionBlock['extraction_status']) => <Tag color={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Tag>,
    },
    { title: '블록', dataIndex: 'block_id', width: 72 },
    { title: '위치', key: 'ref', width: 140, render: (_, b) => locationText(b.source_ref) },
    { title: '원문 ID', dataIndex: 'source_id', width: 100, render: (id: string | null) => id ?? '—' },
    {
      title: '원문 문장',
      dataIndex: 'source_text',
      render: (text: string | null) => (text === null ? <Typography.Text type="secondary">원문 없음</Typography.Text> : <Lines text={text} />),
    },
    { title: '판정 이유', dataIndex: 'notice', render: (n: string | null) => (n ? <Lines text={n} /> : '—') },
  ]

  const decisionColumn: TableColumnsType<ExtractionBlock>[number] = {
    title: '결정',
    key: 'decision',
    width: 240,
    render: (_, b) => {
      const d = decisions[b.block_id] ?? { exclude: false, reason: '' }
      const reasonMissing = b.extraction_status === 'review' && d.exclude && !d.reason.trim()
      return (
        <Flex vertical gap={8}>
          {b.extraction_status === 'review' ? (
            <Radio.Group
              optionType="button"
              value={d.exclude ? 'exclude' : 'confirm'}
              onChange={(e) => decide(b.block_id, { exclude: e.target.value === 'exclude' })}
              options={[
                { value: 'confirm', label: '확인' },
                { value: 'exclude', label: '제외' },
              ]}
            />
          ) : (
            <Checkbox checked={d.exclude} onChange={(e) => decide(b.block_id, { exclude: e.target.checked })}>
              제외 (실패 블록은 제외만 가능)
            </Checkbox>
          )}
          {d.exclude && (
            <Input
              aria-label={`${b.block_id} 제외 사유`}
              placeholder={b.extraction_status === 'review' ? '제외 사유 (필수)' : '제외 사유 (선택)'}
              value={d.reason}
              status={reasonMissing ? 'error' : undefined}
              onChange={(e) => decide(b.block_id, { reason: e.target.value })}
            />
          )}
        </Flex>
      )
    },
  }

  return (
    <PageCard title="추출 확인" subtitle="문서에서 읽은 원문을 확인합니다. 원문은 고치지 않고, 확인하거나 제외만 합니다.">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title={errorMessage(loadError)}
          action={<Button onClick={reload}>다시 불러오기</Button>}
        />
      ) : !blocks ? (
        <Flex justify="center">
          <Spin />
        </Flex>
      ) : (
        <Flex vertical gap={20}>
          <Typography.Text>
            전체 {blocks.length}건 · 실패 {toCheck.filter((b) => b.extraction_status === 'fail').length}건 · 확인 필요{' '}
            {toCheck.filter((b) => b.extraction_status === 'review').length}건 · 정상 {passed.length}건
          </Typography.Text>

          {notice && <Alert type="warning" showIcon title={notice} />}
          {sheets.length > 0 && (
            <Alert type="info" showIcon title={`요구사항을 읽지 않은 시트가 있습니다: ${sheets.join(', ')}`} />
          )}

          <section aria-label="확인할 원문">
            <Typography.Title level={5}>확인할 원문 {toCheck.length}건</Typography.Title>
            <Table
              rowKey="block_id"
              size="small"
              pagination={false}
              columns={[...columns, decisionColumn]}
              dataSource={toCheck}
              scroll={{ x: 960 }}
            />
          </section>

          {passed.length > 0 && (
            <Collapse
              items={[
                {
                  key: 'passed',
                  label: `정상 ${passed.length}건 보기`,
                  children: (
                    <Table
                      rowKey="block_id"
                      size="small"
                      pagination={passed.length > 20 ? { pageSize: 20 } : false}
                      columns={columns}
                      dataSource={passed}
                      scroll={{ x: 720 }}
                    />
                  ),
                },
              ]}
            />
          )}

          {warnings.length > 0 && (
            <Alert
              type="warning"
              showIcon
              title="제외하는 원문을 관련 요구사항으로 적은 원문이 있습니다"
              description={
                <ul>
                  {warnings.map((w) => (
                    <li key={w.block_id}>
                      {w.block_id}({w.source_id})를 제외하면 {w.related_block_ids.join(', ')}의 관련 요구사항에 남습니다. 제외는 할 수
                      있습니다.
                    </li>
                  ))}
                </ul>
              }
            />
          )}

          {blocking.length > 0 && (
            <Alert
              type="info"
              showIcon
              title="보내기 전에 확인할 것"
              description={
                <ul>
                  {blocking.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              }
            />
          )}
          {actionError && <Alert type="error" showIcon title={actionError} />}

          <Flex gap={12} wrap>
            <Button
              type="primary"
              size="large"
              loading={sending}
              disabled={blocking.length > 0 || !canAnswer}
              onClick={() => send(buildResponse(blocks, decisions))}
            >
              확인하고 분석 시작
            </Button>
            <Popconfirm
              title="실행을 중단할까요?"
              description="이 실행은 취소되고 되돌릴 수 없습니다."
              okText="전체 중단"
              cancelText="계속 확인"
              onConfirm={() => send(STOP_RESPONSE)}
            >
              <Button danger size="large" disabled={sending || !canAnswer}>
                전체 중단
              </Button>
            </Popconfirm>
          </Flex>
        </Flex>
      )}
    </PageCard>
  )
}

/** 줄바꿈이 있는 서버 문장을 그대로 보인다 */
function Lines({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>
          {line}
          {i < lines.length - 1 && <br />}
        </span>
      ))}
    </>
  )
}

export default ExtractionPanel
