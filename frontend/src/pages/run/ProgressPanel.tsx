import RunEyebrow from '../run/RunEyebrow.tsx'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { cancelRun } from '../../api/client.ts'
import { errorMessage, nextAction } from '../../api/errors.ts'
import { notifyRunsChanged } from '../../api/runNames.ts'
import type { ErrorCode, RunStatus, SseEvent } from '../../api/types.ts'
import Icon from '../../layout/Icon.tsx'
import Button from '../../ui/Button.tsx'
import ConfirmButton from '../../ui/ConfirmButton.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import type { Connection } from './followRun.ts'
import {
  PROGRESS_STAGES,
  canCancel,
  displayStage,
  failureOf,
  progressIndex,
  requirementsCheckSkipped,
} from './screens.ts'

// UI-04 설계 진행: 단계·진행 상태, 취소.
// 분석 확인을 건너뛰었으면 「분석 확인 생략」, 실패·취소면 원인과 다음 행동을 보인다.
// 단계 설명은 시안 문구. 가짜 진행률·예상 시간은 만들지 않는다.
type Props = {
  run: RunStatus
  events: SseEvent[]
  connection: Connection
  onChanged: () => Promise<void>
  label: string
}

const STAGE_DESC: Record<(typeof PROGRESS_STAGES)[number]['stage'], string> = {
  parsing: '원문을 문장 단위로 읽어요',
  analysing: '요구사항을 나누고 분류해요',
  designing: '기능과 테이블, 테이블 연결을 정해요',
  generating: '기능 명세 · ERD · DDL · RTM을 만들어요',
  reviewing: '네 가지 관점으로 검토하고, 고칠 곳이 있으면 다시 설계해요',
}

type RowState = 'done' | 'now' | 'wait' | 'fail'

function ProgressPanel({ run, events, connection, onChanged, label }: Props) {
  const navigate = useNavigate()
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const failure = run.status === 'failed' ? failureOf(run.error, events) : null
  const current = progressIndex(displayStage(run.stage, events))
  const stopped = run.status === 'failed' || run.status === 'cancelled'

  async function cancel() {
    setCancelling(true)
    setActionError(null)
    try {
      await cancelRun(run.run_id, run.revision)
      notifyRunsChanged()
    } catch (err) {
      // 409: 그새 상태가 바뀌었다. 최신 상태를 읽고 안내만 남긴다.
      setActionError(errorMessage(err))
    } finally {
      await onChanged().catch(() => {})
      setCancelling(false)
    }
  }

  function rowState(i: number): RowState {
    if (i < current) return 'done'
    if (i === current) return stopped ? 'fail' : run.status === 'queued' ? 'wait' : 'now'
    return 'wait'
  }

  const title =
    run.status === 'failed' ? (
      <>
        설계를 <strong>멈췄어요</strong>
      </>
    ) : run.status === 'cancelled' ? (
      <>
        실행을 <strong>취소했어요</strong>
      </>
    ) : run.status === 'cancel_requested' ? (
      <>
        <strong>취소</strong>하고 있어요
      </>
    ) : run.status === 'queued' ? (
      <>
        곧 <strong>시작</strong>해요
      </>
    ) : (
      <>
        나머지는 <strong>알아서</strong> 진행 중이에요
      </>
    )

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={<RunEyebrow screen="설계 중" label={label} run={run} />}
        title={title}
        actions={
          canCancel(run.status) && (
            <ConfirmButton
              variant="danger"
              loading={cancelling}
              loadingText="취소 요청 중"
              title="설계를 그만둘까요?"
              description="진행 중인 작업이 끝나면 멈춰요. 되돌릴 수 없어요."
              okText="그만두기"
              cancelText="계속하기"
              danger
              onConfirm={cancel}
            >
              그만두기
            </ConfirmButton>
          )
        }
      />

      {requirementsCheckSkipped(events) && (
        <Notice kind="plain" title="요구사항 확인 생략 · 확인할 항목 없음">
          확인할 경고·질문·분할이 없어 요구사항 확인 없이 설계로 넘어왔어요. 사람이 승인한 것은 아니에요.
        </Notice>
      )}

      <ol className="steps-list" style={{ listStyle: 'none', margin: 0 }} aria-label="진행 단계">
        {PROGRESS_STAGES.map((s, i) => {
          const st = rowState(i)
          const text = st === 'done' ? '완료' : st === 'now' ? '진행 중' : st === 'fail' ? (run.status === 'failed' ? '실패' : '멈춤') : '대기'
          return (
            <li key={s.stage} className={`steps-list__row${st === 'wait' ? ' steps-list__row--wait' : ''}`} aria-current={st === 'now' ? 'step' : undefined}>
              <span className={`state-dot state-dot--${st}`} aria-hidden="true">
                {st === 'done' && <Icon name="check" size={13} strokeWidth={3} />}
                {st === 'fail' && <Icon name="x" size={13} strokeWidth={3} />}
              </span>
              <span className="steps-list__name">{s.title}</span>
              <span className="steps-list__desc">{STAGE_DESC[s.stage]}</span>
              <span className="steps-list__state">{text}</span>
            </li>
          )
        })}
      </ol>
      {!stopped && <p className="muted" style={{ margin: 0 }}>확인이 필요한 곳이 생기면 멈추고 알려 드려요.</p>}

      {run.status === 'queued' && <Notice title="실행을 기다리고 있어요">다른 실행이 끝나면 시작해요.</Notice>}
      {run.status === 'cancel_requested' && (
        <Notice kind="warning" title="취소를 요청했어요">
          지금 하던 단계가 끝나면 멈춰요. 길면 5분쯤 걸려요.
        </Notice>
      )}
      {run.status === 'cancelled' && (
        <Notice kind="plain" title="실행을 취소했어요" action={<Button size="sm" onClick={() => navigate('/')}>새 작업</Button>} />
      )}
      {failure && <FailureNotice failure={failure} onRestart={() => navigate('/')} />}
      {connection === 'retrying' && <p className="muted" style={{ margin: 0 }}>연결이 끊겨 다시 연결하고 있어요…</p>}
      {actionError && <Notice kind="warning" title={actionError} />}
    </div>
  )
}

function FailureNotice({ failure, onRestart }: { failure: NonNullable<ReturnType<typeof failureOf>>; onRestart: () => void }) {
  // 서버 문구를 그대로 보이고, 다음 행동은 오류 코드로 정한다 (api/errors.ts)
  const action = nextAction(failure.code as ErrorCode, failure.retryable)
  const label = action === 'reupload' ? '다른 파일로 다시 시작' : '새로 시작'
  return (
    <Notice kind="error" title={failure.message} action={<Button size="sm" onClick={onRestart}>{label}</Button>}>
      {failure.detail ? (
        <details className="more">
          <summary>자세히 보기</summary>
          {failure.detail}
        </details>
      ) : action === 'retry' ? (
        '잠시 후 같은 파일로 다시 시작해 보세요.'
      ) : null}
    </Notice>
  )
}

export default ProgressPanel
