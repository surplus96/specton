import { useEffect, useMemo, useState } from 'react'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import type { ArtifactRef, DesignItem, Finding, Severity } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import Button from '../../ui/Button.tsx'
import ConfirmButton from '../../ui/ConfirmButton.tsx'
import Loading from '../../ui/Loading.tsx'
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
  reviewDiagnostics,
  reviewNotices,
  type Decision,
} from './rules.ts'

// UI-06 최종 검토 (docs/09, ADR-0010). 「마지막 결정은 사람이 합니다」
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
  const [findings, setFindings] = useState<Finding[] | null>(null)
  const [design, setDesign] = useState<DesignItem[]>([])
  const [artifacts, setArtifacts] = useState<ArtifactRef[]>([])
  const [sql, setSql] = useState<SqlReview>({ status: 'unverified', validatedAt: null })
  const [loadError, setLoadError] = useState<unknown>(null)
  const [decision, setDecision] = useState<Exclude<Decision, 'approve'> | null>(null)
  const [feedback, setFeedback] = useState('')
  const [held, setHeld] = useState(false)
  const [severity, setSeverity] = useState<Severity | null>(null)
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
        setArtifacts(toArtifacts(designView.artifacts))
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
  const checklist = reviewChecklist(design, artifacts, run.revision, sql)

  async function submit(d: Decision) {
    setHeld(false)
    const sent = await send(buildResponse(d, d === 'approve' ? '' : feedback))
    if (sent && d === 'hold') setHeld(true) // 보류는 같은 확인 요청으로 계속 기다린다
  }

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={`최종 검토 · ${label} · ${revisionText(run.revision)}`}
        title={
          <>
            마지막 결정은 <strong>사람이</strong> 합니다
          </>
        }
      />
      {loadError ? (
        <Notice kind="error" title={errorMessage(loadError)} action={<Button variant="secondary" size="sm" onClick={reload}>다시 불러오기</Button>} />
      ) : !findings ? (
        <Loading text="검토 지적과 설계 결과를 불러오는 중이에요" />
      ) : (
        <>
          {notice && <Notice kind="warning" title={notice} />}
          {held && <Notice title="보류했어요. 같은 확인 요청으로 계속 기다려요." />}
          {failedBranches.length > 0 && (
            <Notice kind="warning" title={`일부 검토가 빠졌어요: ${failedBranches.map(branchText).join(', ')}`}>
              빠진 관점의 지적은 아래 목록에 없어요. 승인 전에 확인해 주세요.
            </Notice>
          )}
          {hitlReason && <Notice title={HITL_REASON_TEXT[hitlReason] ?? hitlReason} />}
          {/* 근거 검사에서 제외한 지적·A09 재작업 판단 (#330). 지금 확인 요청의 것만 */}
          {reviewDiagnostics(events, interruptId).map((message, index) => (
            <Notice key={index} kind="plain" title={message} />
          ))}

          <div className="decide">
            <div className="check-list" aria-label="산출물 확인 목록">
              {checklist.map((c) => (
                <div key={c.key} className="check-list__row">
                  <span className={`state-dot state-dot--${c.ok ? 'done' : 'wait'}`} aria-hidden="true">
                    {c.ok && <Icon name="check" size={13} strokeWidth={3} />}
                  </span>
                  <b>{c.title}</b>
                  <span className="muted">
                    {c.detail}
                    <span className="sr-only">{c.ok ? ' · 확인됨' : ' · 확인 필요'}</span>
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
                <Notice kind="error" title={`차단 오류 ${counts.critical}건이 남아 있어 승인할 수 없어요.`}>
                  수정 요청으로 고친 뒤 다시 검토해 주세요.
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
              {!approvable && !decision && <span className="subtle" style={{ fontSize: 13 }}>승인 · 차단 오류가 있어 쓸 수 없어요</span>}
            </div>
          </div>

          <SqlValidationPanel result={sql} />

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
            <DesignTables items={design} names={names} />
          </section>
        </>
      )}
    </div>
  )
}

export default ReviewPanel
