import { Alert, Button, Flex, Spin, Typography } from 'antd'
import { useNavigate } from 'react-router'
import { ApiError, errorMessage } from '../api/errors.ts'
import StageSteps, { SCREENS } from '../layout/StageSteps.tsx'
import PageCard from '../layout/PageCard.tsx'
import ExtractionPanel from './extraction/ExtractionPanel.tsx'
import RequirementsPanel from './requirements/RequirementsPanel.tsx'
import ProgressPanel from './run/ProgressPanel.tsx'
import { screenFor } from './run/screens.ts'
import { useRunStatus } from './run/useRunStatus.ts'

// 실행 하나의 화면 (/?run=<runId>, App.tsx).
// 상태를 조회하고 이벤트(SSE)로 따라가며, 상태에 맞는 화면(UI-02~07)을 고른다 (run/screens.ts).
// 새로고침해도 상태 조회로 같은 화면에 돌아온다.
function RunPage({ runId }: { runId: string }) {
  const navigate = useNavigate()
  const { run, events, connection, loadError, refresh } = useRunStatus(runId)

  if (loadError) {
    const notFound = loadError instanceof ApiError && loadError.status === 404
    return (
      <PageCard title={notFound ? '실행을 찾을 수 없습니다' : '실행을 불러오지 못했습니다'} subtitle={`실행 ID: ${runId}`}>
        <Alert
          type={notFound ? 'warning' : 'error'}
          showIcon
          title={errorMessage(loadError)}
          action={<Button onClick={() => navigate('/')}>업로드로 돌아가기</Button>}
        />
      </PageCard>
    )
  }

  if (!run) {
    return (
      <Flex vertical align="center" gap={12}>
        <Spin size="large" />
        <Typography.Text type="secondary">실행 상태를 불러오고 있습니다</Typography.Text>
      </Flex>
    )
  }

  const screen = screenFor(run.status, run.interrupt?.kind)
  return (
    <Flex vertical gap={24}>
      <StageSteps current={screen} />
      {screen === 'UI-04' ? (
        <ProgressPanel run={run} events={events} connection={connection} onChanged={refresh} />
      ) : screen === 'UI-02' ? (
        <ExtractionPanel run={run} events={events} onChanged={refresh} />
      ) : screen === 'UI-03' ? (
        <RequirementsPanel run={run} onChanged={refresh} />
      ) : (
        <PageCard
          title={SCREENS.find((s) => s.id === screen)?.title ?? screen}
          subtitle={run.interrupt?.message ?? events.slice(-1)[0]?.data.message ?? run.status}
        >
          <Alert type="info" showIcon title={`${screen} 화면은 다음 단계에서 만듭니다.`} description={`지금 상태: ${run.status}`} />
        </PageCard>
      )}
    </Flex>
  )
}

export default RunPage
