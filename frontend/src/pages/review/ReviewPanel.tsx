import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Flex, Input, Popconfirm, Radio, Spin, Typography } from 'antd'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import type { DesignItem, Finding, Severity } from '../../api/viewItems.ts'
import PageCard from '../../layout/PageCard.tsx'
import { useResume } from '../run/useResume.ts'
import DesignTables from './DesignTables.tsx'
import FindingsTable from './FindingsTable.tsx'
import ReviewSummary from './ReviewSummary.tsx'
import SqlValidationPanel from './SqlValidationPanel.tsx'
import { sqlReview, type SqlReview } from './sqlValidation.ts'
import {
  HITL_REASON_TEXT,
  SEVERITY_LABEL,
  branchText,
  buildResponse,
  canApprove,
  countBySeverity,
  nameIndex,
  problems,
  reviewNotices,
  reviewDiagnostics,
  type Decision,
} from './rules.ts'

// UI-06 최종 검토 (docs/09, ADR-0010, 구현 가이드 강의 10).
// 지적 목록과 설계 결과를 보고 승인·수정 요청·보류를 고른다. 차단 오류(critical)가 있으면 승인할 수 없다.
type Props = {
  run: RunStatus
  events: SseEvent[]
  onChanged: () => Promise<void>
}

const SUBMIT_LABEL: Record<Decision, string> = {
  approve: '승인하고 내보내기',
  revise: '수정 요청 보내기',
  hold: '보류',
}

function ReviewPanel({ run, events, onChanged }: Props) {
  const interruptId = run.interrupt?.interrupt_id
  const [findings, setFindings] = useState<Finding[] | null>(null)
  const [design, setDesign] = useState<DesignItem[]>([])
  const [sql, setSql] = useState<SqlReview>({ status: 'unverified', validatedAt: null })
  const [loadError, setLoadError] = useState<unknown>(null)
  const [decision, setDecision] = useState<Decision | null>(null)
  const [feedback, setFeedback] = useState('')
  const [held, setHeld] = useState(false)
  const [severity, setSeverity] = useState<Severity | null>(null) // 「검토가 필요한 항목」에서 고른 심각도
  const { send, sending, error, notice, reloadKey, reload, canAnswer } = useResume(run, onChanged)

  useEffect(() => {
    let alive = true
    setFindings(null)
    setSql({ status: 'unverified', validatedAt: null })
    setLoadError(null)
    setDecision(null)
    setFeedback('')
    setSeverity(null)
    Promise.all([getView(run.run_id, 'review', run.revision), getView(run.run_id, 'design', run.revision)])
      .then(([review, designView]) => {
        if (!alive) return
        setFindings(review.items as Finding[])
        setDesign(designView.items as DesignItem[])
        setSql(sqlReview(designView.artifacts, run.revision))
      })
      .catch((err: unknown) => alive && setLoadError(err))
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, interruptId, reloadKey])

  const names = useMemo(() => nameIndex(design), [design])
  const counts = countBySeverity(findings ?? [])
  const approvable = canApprove(findings ?? [])
  const { failedBranches, hitlReason } = reviewNotices(events, interruptId)
  const blocking = decision ? problems(decision, feedback, findings ?? []) : []

  async function submit() {
    if (!decision) return
    setHeld(false)
    const sent = await send(buildResponse(decision, feedback))
    if (sent && decision === 'hold') setHeld(true) // 보류는 같은 확인 요청으로 계속 기다린다
  }

  return (
    <PageCard title="최종 검토" subtitle={`revision ${run.revision} 설계를 확인하고 승인하거나 수정을 요청합니다.`}>
      {loadError ? (
        <Alert type="error" showIcon title={errorMessage(loadError)} action={<Button onClick={reload}>다시 불러오기</Button>} />
      ) : !findings ? (
        <Flex justify="center">
          <Spin />
        </Flex>
      ) : (
        <Flex vertical gap={20}>
          <Typography.Text>
            지적 {findings.length}건 · 차단 {counts.critical}건 · 주요 {counts.major}건 · 참고 {counts.minor}건
          </Typography.Text>

          {notice && <Alert type="warning" showIcon title={notice} />}
          {held && <Alert type="info" showIcon title="보류했습니다. 같은 확인 요청으로 계속 기다립니다." />}
          {failedBranches.length > 0 && (
            <Alert
              type="warning"
              showIcon
              title={`일부 검토가 빠졌습니다: ${failedBranches.map(branchText).join(', ')}`}
              description="빠진 관점의 지적은 아래 목록에 없습니다. 승인 전에 확인해 주세요."
            />
          )}
          {hitlReason && <Alert type="info" showIcon title={HITL_REASON_TEXT[hitlReason] ?? hitlReason} />}
          {reviewDiagnostics(events, interruptId).map((message, index) => (
            <Alert key={index} type="info" showIcon title={message} />
          ))}
          <SqlValidationPanel result={sql} />
          {!approvable && (
            <Alert
              type="error"
              showIcon
              title={`차단 오류 ${counts.critical}건이 남아 있어 승인할 수 없습니다.`}
              description="수정 요청으로 고친 뒤 다시 검토해 주세요."
            />
          )}

          <ReviewSummary findings={findings} names={names} selected={severity} onSelect={setSeverity} />

          <section aria-label="검토 지적">
            <Flex gap={8} align="center" wrap>
              <Typography.Title level={5} style={{ margin: 0 }}>
                검토 지적 {severity ? `${SEVERITY_LABEL[severity]} ${counts[severity]}건` : `${findings.length}건`}
              </Typography.Title>
              {severity && <Button onClick={() => setSeverity(null)}>전체 보기</Button>}
            </Flex>
            <div style={{ marginTop: 8 }}>
              <FindingsTable findings={severity ? findings.filter((f) => f.severity === severity) : findings} names={names} />
            </div>
          </section>

          <section aria-label="설계 결과">
            <Typography.Title level={5}>설계 결과</Typography.Title>
            <DesignTables items={design} names={names} />
          </section>

          <section aria-label="결정">
            <Typography.Title level={5}>결정</Typography.Title>
            <Flex vertical gap={12}>
              <Radio.Group
                value={decision}
                onChange={(e) => setDecision(e.target.value as Decision)}
                options={[
                  { value: 'approve', label: approvable ? '승인' : '승인 (차단 오류가 있어 불가)', disabled: !approvable },
                  { value: 'revise', label: '수정 요청' },
                  { value: 'hold', label: '보류' },
                ]}
              />
              {(decision === 'revise' || decision === 'hold') && (
                <Input.TextArea
                  aria-label={decision === 'revise' ? '수정 요청 내용' : '보류 메모'}
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  placeholder={decision === 'revise' ? '무엇을 고쳐야 하는지 적어 주세요 (필수)' : '메모 (선택)'}
                  status={decision === 'revise' && !feedback.trim() ? 'error' : undefined}
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                />
              )}
              {blocking.length > 0 && <Alert type="info" showIcon title={blocking[0]} />}
              {error && <Alert type="error" showIcon title={error} />}
              <Flex>
                {decision === 'approve' ? (
                  <Popconfirm
                    title={`revision ${run.revision}을 승인할까요?`}
                    description="승인하면 산출물을 내보냅니다."
                    okText="승인"
                    cancelText="취소"
                    onConfirm={submit}
                  >
                    <Button type="primary" size="large" loading={sending} disabled={blocking.length > 0 || !canAnswer}>
                      {SUBMIT_LABEL.approve}
                    </Button>
                  </Popconfirm>
                ) : (
                  <Button
                    type="primary"
                    size="large"
                    loading={sending}
                    disabled={!decision || blocking.length > 0 || !canAnswer}
                    onClick={submit}
                  >
                    {decision ? SUBMIT_LABEL[decision] : '결정을 골라 주세요'}
                  </Button>
                )}
              </Flex>
            </Flex>
          </section>
        </Flex>
      )}
    </PageCard>
  )
}

export default ReviewPanel
