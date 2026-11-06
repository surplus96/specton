import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Collapse, Flex, Input, Radio, Spin, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus } from '../../api/types.ts'
import type { AnalysedRequirement } from '../../api/viewItems.ts'
import PageCard from '../../layout/PageCard.tsx'
import { useResume } from '../run/useResume.ts'
import {
  ACTION_LABEL,
  buildResponse,
  changedCount,
  initialAnswers,
  needsAttention,
  problems,
  sortRequirements,
  splitFromSameSource,
  switchAction,
  typeText,
  type Action,
  type Answer,
  type Answers,
} from './rules.ts'

// UI-03 분석 확인 (docs/09, 구현 가이드 강의 10).
// 요구사항마다 유지·수정·분할을 고른다. 답하지 않은 요구사항은 유지로 본다.
// 품질 경고·질문이 있거나 같은 원문에서 나뉜 요구사항을 먼저 보인다.
type Props = {
  run: RunStatus
  onChanged: () => Promise<void>
}

function RequirementsPanel({ run, onChanged }: Props) {
  const interruptId = run.interrupt?.interrupt_id
  const [reqs, setReqs] = useState<AnalysedRequirement[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [answers, setAnswers] = useState<Answers>({})
  const { send, sending, error, notice, reloadKey, reload, canAnswer } = useResume(run, onChanged)

  useEffect(() => {
    let alive = true
    setReqs(null)
    setLoadError(null)
    getView(run.run_id, 'requirements', run.revision)
      .then((view) => {
        if (!alive) return
        const items = view.items as AnalysedRequirement[]
        setReqs(items)
        setAnswers(initialAnswers(items))
      })
      .catch((err: unknown) => alive && setLoadError(err))
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, interruptId, reloadKey])

  const split = useMemo(() => splitFromSameSource(reqs ?? []), [reqs])
  const sorted = useMemo(() => sortRequirements(reqs ?? []), [reqs])
  const toCheck = sorted.filter((r) => needsAttention(r, split))
  const others = sorted.filter((r) => !needsAttention(r, split))
  const blocking = problems(answers)
  const changed = changedCount(answers)

  const setAnswer = (reqId: string, answer: Answer) => setAnswers((prev) => ({ ...prev, [reqId]: answer }))

  const columns: TableColumnsType<AnalysedRequirement> = [
    { title: 'ID', dataIndex: 'id', width: 84 },
    { title: '원문 ID', dataIndex: 'source_id', width: 96, render: (id: string | null) => id ?? '—' },
    {
      title: '요구사항',
      key: 'text',
      render: (_, r) => (
        <Flex vertical gap={4}>
          <span>{r.text}</span>
          {split.has(r.id) && (
            <Typography.Text type="secondary">같은 원문에서 나뉜 요구사항입니다</Typography.Text>
          )}
          {r.source_text && r.source_text !== r.text && (
            <Typography.Text type="secondary">원문: {r.source_text}</Typography.Text>
          )}
        </Flex>
      ),
    },
    { title: '유형', key: 'type', width: 120, render: (_, r) => typeText(r) },
    {
      title: '품질 경고·질문',
      key: 'issues',
      width: 220,
      render: (_, r) =>
        r.quality_issues.length === 0 ? (
          '—'
        ) : (
          <Flex vertical gap={6}>
            {r.quality_issues.map((issue, i) => (
              <div key={i}>
                <Tag color="orange">경고</Tag>
                {issue.message}
                {issue.question && <div>질문: {issue.question}</div>}
              </div>
            ))}
          </Flex>
        ),
    },
  ]

  const answerColumn: TableColumnsType<AnalysedRequirement>[number] = {
    title: '답',
    key: 'answer',
    width: 270,
    render: (_, r) => {
      const a = answers[r.id] ?? { action: 'keep', texts: [] }
      return (
        <Flex vertical gap={8}>
          <Radio.Group
            optionType="button"
            value={a.action}
            onChange={(e) => setAnswer(r.id, switchAction(r, e.target.value as Action))}
            options={(['keep', 'edit', 'split'] as const).map((v) => ({ value: v, label: ACTION_LABEL[v] }))}
          />
          {a.action !== 'keep' &&
            a.texts.map((text, i) => (
              <Flex key={i} gap={6} align="start">
                <Input.TextArea
                  aria-label={`${r.id} ${a.action === 'edit' ? '수정 문장' : `분할 문장 ${i + 1}`}`}
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  value={text}
                  status={!text.trim() ? 'error' : undefined}
                  placeholder={a.action === 'split' ? `조각 ${i + 1}` : '바꿀 문장'}
                  onChange={(e) => setAnswer(r.id, { ...a, texts: a.texts.map((t, j) => (j === i ? e.target.value : t)) })}
                />
                {a.action === 'split' && a.texts.length > 2 && (
                  <Button
                    aria-label={`${r.id} 조각 ${i + 1} 지우기`}
                    onClick={() => setAnswer(r.id, { ...a, texts: a.texts.filter((_, j) => j !== i) })}
                  >
                    빼기
                  </Button>
                )}
              </Flex>
            ))}
          {a.action === 'split' && (
            <Flex vertical gap={4}>
              <Button size="small" onClick={() => setAnswer(r.id, { ...a, texts: [...a.texts, ''] })}>
                조각 더하기
              </Button>
              <Typography.Text type="secondary">첫 조각은 {r.id}, 나머지는 서버가 새 ID를 붙입니다.</Typography.Text>
            </Flex>
          )}
          {a.action === 'edit' && r.quality_issues.some((q) => q.question) && (
            <Typography.Text type="secondary">질문의 답을 문장에 넣어 고쳐 주세요.</Typography.Text>
          )}
        </Flex>
      )
    },
  }

  return (
    <PageCard title="분석 확인" subtitle="문서에서 뽑은 요구사항을 확인합니다. 고를 답이 없으면 그대로 두면 됩니다(유지).">
      {loadError ? (
        <Alert type="error" showIcon title={errorMessage(loadError)} action={<Button onClick={reload}>다시 불러오기</Button>} />
      ) : !reqs ? (
        <Flex justify="center">
          <Spin />
        </Flex>
      ) : (
        <Flex vertical gap={20}>
          <Typography.Text>
            요구사항 {reqs.length}건 · 확인할 것 {toCheck.length}건 · 바꾼 것 {changed}건
          </Typography.Text>
          {notice && <Alert type="warning" showIcon title={notice} />}

          <section aria-label="확인할 요구사항">
            <Typography.Title level={5}>확인할 요구사항 {toCheck.length}건</Typography.Title>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              columns={[...columns, answerColumn]}
              dataSource={toCheck}
              scroll={{ x: 960 }}
            />
          </section>

          {others.length > 0 && (
            <Collapse
              items={[
                {
                  key: 'others',
                  label: `문제가 없는 요구사항 ${others.length}건 (바꿀 때만 펼치세요)`,
                  children: (
                    <Table
                      rowKey="id"
                      size="small"
                      pagination={others.length > 20 ? { pageSize: 20 } : false}
                      columns={[...columns, answerColumn]}
                      dataSource={others}
                      scroll={{ x: 960 }}
                    />
                  ),
                },
              ]}
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
          {error && <Alert type="error" showIcon title={error} />}

          <Flex>
            <Button
              type="primary"
              size="large"
              loading={sending}
              disabled={blocking.length > 0 || !canAnswer}
              onClick={() => send(buildResponse(answers))}
            >
              {changed > 0 ? `${changed}건 바꾸고 설계 시작` : '그대로 설계 시작'}
            </Button>
          </Flex>
        </Flex>
      )}
    </PageCard>
  )
}

export default RequirementsPanel
