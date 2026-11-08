import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Alert, Button, Flex, Popconfirm, Steps, Typography } from 'antd'
import { cancelRun } from '../../api/client.ts'
import { errorMessage, nextAction } from '../../api/errors.ts'
import type { ErrorCode, RunStatus, SseEvent } from '../../api/types.ts'
import PageCard from '../../layout/PageCard.tsx'
import type { Connection } from './followRun.ts'
import {
  PROGRESS_STAGES,
  canCancel,
  displayStage,
  failureOf,
  progressIndex,
  requirementsCheckSkipped,
} from './screens.ts'

// UI-04 설계 진행 (docs/09-ui-flow.md): 단계·진행 상태 조회, 취소.
// UI-03을 건너뛰었으면 「분석 확인 생략」, 실패·취소면 원인과 다음 행동을 보인다.
// 진행 기록(서버 소식)은 화면 옆 서버 작업 패널(ActivityPanel)이 보인다.
type Props = {
  run: RunStatus
  events: SseEvent[]
  connection: Connection
  onChanged: () => Promise<void>
}

function ProgressPanel({ run, events, connection, onChanged }: Props) {
  const navigate = useNavigate()
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const failure = run.status === 'failed' ? failureOf(run.error, events) : null
  const current = progressIndex(displayStage(run.stage, events))
  const stepStatus = failure ? 'error' : run.status === 'cancelled' ? 'wait' : 'process'

  async function cancel() {
    setCancelling(true)
    setActionError(null)
    try {
      await cancelRun(run.run_id, run.revision)
    } catch (err) {
      // 409: 그새 상태가 바뀌었다. 최신 상태를 읽고 안내만 남긴다.
      setActionError(errorMessage(err))
    } finally {
      await onChanged().catch(() => {})
      setCancelling(false)
    }
  }

  return (
    <PageCard title="설계 진행" subtitle={`실행 ID: ${run.run_id} · revision ${run.revision}`}>
      <Flex vertical gap={20}>
        {requirementsCheckSkipped(events) && (
          <Alert type="info" showIcon title="분석 확인 생략 (확인할 항목 없음)" />
        )}

        <Steps
          size="small"
          current={Math.min(Math.max(current, 0), PROGRESS_STAGES.length - 1)}
          status={current < 0 && run.status === 'queued' ? 'wait' : stepStatus}
          items={PROGRESS_STAGES.map((s) => ({ title: s.title }))}
        />

        {run.status === 'queued' && (
          <Alert type="info" showIcon title="실행을 기다리고 있습니다" description="다른 실행이 끝나면 시작합니다." />
        )}
        {run.status === 'cancel_requested' && (
          <Alert
            type="warning"
            showIcon
            title="취소를 요청했습니다"
            description="진행 중인 작업이 끝나면 취소됩니다. 최대 2분쯤 걸릴 수 있습니다."
          />
        )}
        {run.status === 'cancelled' && (
          <Alert
            type="info"
            showIcon
            title="실행을 취소했습니다"
            action={<Button onClick={() => navigate('/start')}>새 실행</Button>}
          />
        )}
        {failure && <FailureNotice failure={failure} onRestart={() => navigate('/start')} />}

        {connection === 'retrying' && (
          <Typography.Text type="secondary">연결이 끊겨 다시 연결하고 있습니다…</Typography.Text>
        )}
        {actionError && <Alert type="warning" showIcon title={actionError} />}

        {canCancel(run.status) && (
          <Flex>
            <Popconfirm
              title="실행을 취소할까요?"
              description="진행 중인 작업이 끝나면 멈춥니다. 되돌릴 수 없습니다."
              okText="실행 취소"
              cancelText="계속 진행"
              onConfirm={cancel}
            >
              <Button danger loading={cancelling}>
                실행 취소
              </Button>
            </Popconfirm>
          </Flex>
        )}
      </Flex>
    </PageCard>
  )
}

function FailureNotice({
  failure,
  onRestart,
}: {
  failure: NonNullable<ReturnType<typeof failureOf>>
  onRestart: () => void
}) {
  // 서버 문구를 그대로 보이고, 다음 행동은 오류 코드로 정한다 (api/errors.ts)
  const action = nextAction(failure.code as ErrorCode, failure.retryable)
  const label = action === 'reupload' ? '다른 파일로 다시 시작' : '새로 시작'
  return (
    <Alert
      type="error"
      showIcon
      title={failure.message}
      description={
        failure.detail ? (
          <details>
            <summary>자세히 보기</summary>
            {failure.detail}
          </details>
        ) : action === 'retry' ? (
          '잠시 후 같은 파일로 다시 시작해 보세요.'
        ) : undefined
      }
      action={<Button onClick={onRestart}>{label}</Button>}
    />
  )
}

export default ProgressPanel
