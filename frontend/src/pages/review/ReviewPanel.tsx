import RunEyebrow from '../run/RunEyebrow.tsx'
import { useEffect, useMemo, useState } from 'react'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import type { DesignItem, Finding, Severity } from '../../api/viewItems.ts'
import { useViewSection } from '../useViewSection.ts'
import SectionState from '../../ui/SectionState.tsx'
import Icon from '../../layout/Icon.tsx'
import Button from '../../ui/Button.tsx'
import ConfirmButton from '../../ui/ConfirmButton.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import { useResume } from '../run/useResume.ts'
import { toArtifacts } from '../workspace/rules.ts'
import { reviewChecklist } from './checklist.ts'
import DesignTables from './DesignTables.tsx'
import FindingsTable from './FindingsTable.tsx'
import ReviewSummary from './ReviewSummary.tsx'
import { revisionText } from '../runMeta.ts'
import SqlValidationPanel from './SqlValidationPanel.tsx'
import { sqlReview } from './sqlValidation.ts'
import {
  HITL_REASON_TEXT,
  reviewDiagnostics,
  SEVERITY_LABEL,
  branchText,
  buildResponse,
  canApprove,
  countBySeverity,
  nameIndex,
  problems,
  reviewNotices,
  type Decision,
} from './rules.ts'

// UI-06 최종 검토 (docs/09, ADR-0010). 「최종 결정 해주세요」
// 산출물 확인 목록과 결정 카드를 위에, 지적·설계 결과를 아래에 둔다.
// 승인(확인 대화) · 수정 요청(내용 필수) · 보류(메모). 차단(critical) 지적이 있으면 승인할 수 없다.
type Props = {
  run: RunStatus
  events: SseEvent[]
  onChanged: () => Promise<void>
  label: string
}

function ReviewPanel({ run, events, onChanged, label }: Props) {
  const interruptId = run.interrupt?.interrupt_id
  const [decision, setDecision] = useState<Exclude<Decision, 'approve'> | null>(null)
  const [feedback, setFeedback] = useState('')
  const [held, setHeld] = useState(false)
  const [severity, setSeverity] = useState<Severity | null>(null)
  const { send, sending, error, notice, reloadKey, canAnswer } = useResume(run, onChanged)

  const reviewSection = useViewSection(run.run_id, run.revision, 'review', `${interruptId}:${reloadKey}`)
  const designSection = useViewSection(run.run_id, run.revision, 'design', `${interruptId}:${reloadKey}`)
  const findings = reviewSection.data?.items as Finding[] | undefined
  const design = useMemo(() => (designSection.data?.items ?? []) as DesignItem[], [designSection.data])
  const artifacts = useMemo(() => toArtifacts(designSection.data?.artifacts), [designSection.data])
  const sql = sqlReview(designSection.data?.artifacts, run.revision)
  useEffect(() => {
    setDecision(null)
    setFeedback('')
    setSeverity(null)
    setHeld(false)
  }, [run.run_id, run.revision, interruptId])

  const names = useMemo(() => nameIndex(design), [design])
  const counts = countBySeverity(findings ?? [])
  const approvable = Boolean(reviewSection.data && designSection.data) && sql.status === 'passed' && canApprove(findings ?? [])
  const { failedBranches, hitlReason } = reviewNotices(events, interruptId)
  const diagnostics = reviewDiagnostics(events, interruptId)
  const blocking = decision ? problems(decision, feedback, findings ?? []) : []
  const checklist = reviewChecklist(design, artifacts, run.revision, sql)

  async function submit(d: Decision) {
    setHeld(false)
    const sent = await send(buildResponse(d, d === 'approve' ? '' : feedback))
    if (sent && d === 'hold') { setHeld(true); setDecision(null); setFeedback('') } // 보류는 같은 확인 요청으로 계속 기다린다
  }

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={<RunEyebrow screen="최종 승인" label={label} run={run} />}
        title={
          <>
            <strong>최종 결정</strong> 해주세요
          </>
        }
      />
      <SectionState title="검토 지적" error={reviewSection.error} loading={!reviewSection.data && !reviewSection.error} reload={reviewSection.reload} />
      <SectionState title="설계 결과" error={designSection.error} loading={!designSection.data && !designSection.error} reload={designSection.reload} />
      {!findings && designSection.data && <DesignTables items={design} names={names} />}
      {findings && (
        <>
          {notice && <Notice kind="warning" title={notice} />}
          {held && <Notice title="보류했어요. 같은 확인 요청으로 계속 기다려요." />}
          {failedBranches.length > 0 && (
            <Notice kind="warning" title={`일부 검토가 빠졌어요: ${failedBranches.map(branchText).join(', ')}`}>
              빠진 관점의 지적은 아래 목록에 없어요. 승인 전에 확인해 주세요.
            </Notice>
          )}
          {(hitlReason || diagnostics.length > 0) && <details className="more">
            <summary>검토 경위 보기</summary>
            {hitlReason && <p>{HITL_REASON_TEXT[hitlReason] ?? hitlReason}</p>}
            {diagnostics.map((message, index) => <p key={index}>{message}</p>)}
          </details>}
          {/* SQL은 승인을 막는 상태일 때만 별도 안내한다. */}
          {designSection.data && sql.status !== 'passed' && <SqlValidationPanel result={sql} />}

          <section aria-label="검토 지적" className="stack-sm" style={{ gap: 14 }}>
            <h2 className="section-title" style={{ margin: 0 }}>
              검토가 필요한 항목
            </h2>
            <ReviewSummary findings={findings} names={names} selected={severity} onSelect={setSeverity} />
            <div className="row">
              <strong>검토 지적 {severity ? `${SEVERITY_LABEL[severity]} ${counts[severity]}건` : `${findings.length}건`}</strong>
              {severity && (
                <Button variant="secondary" size="sm" onClick={() => setSeverity(null)}>
                  전체 보기
                </Button>
              )}
            </div>
            <FindingsTable findings={severity ? findings.filter((f) => f.severity === severity) : findings} names={names} />
          </section>

          <section aria-label="설계 결과" className="stack-sm" style={{ gap: 14 }}>
            <h2 className="section-title" style={{ margin: 0 }}>
              설계 결과
            </h2>
            {designSection.data && <DesignTables items={design} names={names} />}
          </section>
          <div className="decide">
            <div className="check-list" aria-label="만들어진 산출물">
              {!approvable && counts.critical > 0 && <Notice kind="error" title={`차단 오류 ${counts.critical}건이 남아 있습니다.`} />}
              {designSection.data && checklist.map((c) => (
                <div key={c.key} className="check-list__row">
                  <span className={`state-dot state-dot--${c.ok ? 'done' : 'wait'}`} aria-hidden="true">
                    {c.ok && <Icon name="check" size={13} strokeWidth={3} />}
                  </span>
                  <b>{c.title}</b>
                  <span className="muted">
                    {c.detail}
                    <span className="check-list__state"> · {c.state}</span>
                  </span>
                </div>
              ))}
            </div>

            <div className="decision-card" aria-label="결정">
              <span className="muted" style={{ fontSize: 14 }}>
                검토 지적 {findings.length}건 · 차단 {counts.critical} · 주요 {counts.major} · 참고 {counts.minor}
              </span>
              <h3>이 설계 초안을 승인할까요?</h3>
              {!approvable && (
                <Notice kind="error" title={counts.critical ? `차단 오류 ${counts.critical}건이 남아 있어 승인할 수 없어요.` : !designSection.data ? '설계 결과를 읽어야 승인할 수 있어요.' : '현재 SQL 검증을 통과해야 승인할 수 있어요.'}>
                  위의 검사 결과와 조회 상태를 확인해 주세요.
                </Notice>
              )}
              {decision && (
                <div className="field">
                  <label htmlFor="feedback">{decision === 'revise' ? '수정 요청 내용' : '보류 메모'}</label>
                  <textarea
                    id="feedback"
                    className="textarea"
                    rows={3}
                    placeholder={decision === 'revise' ? '무엇을 고쳐야 하는지 적어 주세요 (필수)' : '메모 (선택)'}
                    aria-invalid={decision === 'revise' && !feedback.trim()}
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                  />
                  {blocking.length > 0 && <span className="field__error">{blocking[0]}</span>}
                </div>
              )}
              {error && <Notice kind="error" title={error} />}
              {decision ? (
                <div className="row">
                  <Button variant="ghost" onClick={() => setDecision(null)} disabled={sending}>
                    돌아가기
                  </Button>
                  <Button
                    className="grow"
                    loading={sending}
                    loadingText="보내는 중"
                    disabled={blocking.length > 0 || !canAnswer}
                    onClick={() => submit(decision)}
                  >
                    {decision === 'revise' ? '수정 요청 보내기' : '보류'}
                  </Button>
                </div>
              ) : (
                <div className="row" style={{ flexWrap: 'nowrap' }}>
                  <Button variant="secondary" className="grow" onClick={() => setDecision('revise')} disabled={sending || !canAnswer}>
                    수정 요청
                  </Button>
                  <ConfirmButton
                    variant="accent"
                    className="grow"
                    loading={sending}
                    loadingText="승인 중"
                    disabled={!approvable || !canAnswer}
                    title={`${revisionText(run.revision)}을 승인할까요?`}
                    description="승인하면 산출물을 내보내요. 승인본 PDF도 이때 만들어져요."
                    okText="승인"
                    cancelText="취소"
                    onConfirm={() => submit('approve')}
                  >
                    승인
                  </ConfirmButton>
                </div>
              )}
              {!decision && (
                <button type="button" className="link-btn" style={{ justifySelf: 'start', fontSize: 14 }} onClick={() => setDecision('hold')} disabled={sending || !canAnswer}>
                  지금은 보류하기
                </button>
              )}
              {!approvable && !decision && <span className="subtle" style={{ fontSize: 13 }}>승인 · 필수 확인 조건을 충족하지 않았어요</span>}
            </div>
          </div>

        </>
      )}
    </div>
  )
}

export default ReviewPanel
