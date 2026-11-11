import { useNavigate } from 'react-router'
import { runTitle } from '../../api/runNames.ts'
import type { RunSummary } from '../../api/types.ts'
import Icon from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import Button from '../../ui/Button.tsx'
import { recentMessages } from '../run/screens.ts'
import { useRunStatus } from '../run/useRunStatus.ts'
import { dotDate, fourStepStates, runAction, runBadge, runMessage } from '../runMeta.ts'
import FourSteps from './FourSteps.tsx'

// 시작 화면의 실행 카드 (F안 「작업 있음」).

function Badge({ status }: { status: RunSummary['status'] }) {
  const b = runBadge(status)
  return (
    <StatusTag tone={b.tone} dot={b.dot}>
      {b.check && <Icon name="check" size={14} />}
      {b.text}
    </StatusTag>
  )
}

/** 지금 진행 중 카드: 상태를 실시간으로 따라가며 네 단계와 최신 소식을 보인다 */
export function ActiveRunCard({ runId }: { runId: string }) {
  const navigate = useNavigate()
  const { run, events, connection } = useRunStatus(runId)
  const { title, file } = runTitle(runId)
  const open = () => navigate(`/?run=${encodeURIComponent(runId)}`)

  if (!run) {
    return <div className="card card--strong skeleton" style={{ height: 240 }} aria-label="진행 중인 작업을 불러오는 중" />
  }
  const latest = recentMessages(events, 1)[0]
  const message = run.interrupt?.message ?? (run.status.startsWith('awaiting') ? null : latest) ?? runMessage(run.status)

  return (
    <article className="card card--strong screen stack" style={{ padding: 28 }}>
      <div className="row row--between" style={{ alignItems: 'flex-start' }}>
        <div className="stack-sm" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 10 }}>
            <Badge status={run.status} />
            {connection === 'live' && <span className="subtle" style={{ fontSize: 13 }}>실시간</span>}
            {connection === 'retrying' && <span className="subtle" style={{ fontSize: 13 }}>다시 연결 중</span>}
          </div>
          <h3 className="h3" style={{ fontSize: 22 }}>
            {title}
          </h3>
          <div className="muted" style={{ fontSize: 15 }}>
            {file ?? `실행 ${runId.slice(0, 8)}`} · 확인 받기 · revision {run.revision}
          </div>
        </div>
        <Button onClick={open}>{runAction(run.status)}</Button>
      </div>
      <FourSteps states={fourStepStates(run.status, run.stage)} />
      <div className="message-box" aria-live="polite">
        {message}
      </div>
    </article>
  )
}

/** 이어서 할 작업 카드 */
export function RunCard({ run }: { run: RunSummary }) {
  const navigate = useNavigate()
  const { title, file } = runTitle(run.run_id)
  return (
    <button
      type="button"
      className="card card--link work-card"
      onClick={() => navigate(`/?run=${encodeURIComponent(run.run_id)}`)}
      aria-label={`${title}, ${runBadge(run.status).text}, ${dotDate(run.created_at)}. 열기`}
    >
      <div className="work-card__top">
        <Badge status={run.status} />
        <span className="row" style={{ gap: 8 }}>
          <span className="subtle" style={{ fontSize: 14 }}>
            {dotDate(run.created_at)}
          </span>
          <span className="badge">r{run.revision}</span>
        </span>
      </div>
      <div className="work-card__title">{title}</div>
      <div className="muted" style={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {file ?? `실행 ID ${run.run_id}`}
      </div>
    </button>
  )
}
