import { Alert, Button, Flex, Segmented, Spin, Typography } from 'antd'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ApiError, errorMessage } from '../api/errors.ts'
import StageSteps, { type ScreenId } from '../layout/StageSteps.tsx'
import PageCard from '../layout/PageCard.tsx'
import WithActivity from '../layout/WithActivity.tsx'
import ActivityPanel from './run/ActivityPanel.tsx'
import ExtractionPanel from './extraction/ExtractionPanel.tsx'
import RequirementsPanel from './requirements/RequirementsPanel.tsx'
import ReviewPanel from './review/ReviewPanel.tsx'
import ProgressPanel from './run/ProgressPanel.tsx'
import { displayStage, screenFor, unreachedScreens } from './run/screens.ts'
import { useRunStatus } from './run/useRunStatus.ts'
import DownloadPanel from './workspace/DownloadPanel.tsx'
import WorkspacePanel from './workspace/WorkspacePanel.tsx'
import { VIEW_LABEL, chosenView, resultViews, type ResultView } from './workspace/rules.ts'

// 실행 하나의 화면 (/?run=<runId>, App.tsx).
// 상태를 조회하고 이벤트(SSE)로 따라가며, 상태에 맞는 화면(UI-02~07)을 고른다 (run/screens.ts).
// 결과가 있으면(최종 검토 대기·완료) 위쪽에서 결과 작업공간(UI-05)으로 바꿔 볼 수 있다 (&view=workspace).
// 새로고침해도 상태 조회와 주소로 같은 화면에 돌아온다.
// 모든 화면 옆(좁으면 아래)에 서버 작업 패널을 붙여 이벤트를 실시간으로 보인다 (run/ActivityPanel).
const SCREEN_OF_VIEW: Record<ResultView, ScreenId> = {
  review: 'UI-06',
  workspace: 'UI-05',
  downloads: 'UI-07',
}

const WORKSPACE_NEW_TAB = import.meta.env.MODE !== 'mock'

function RunPage({ runId }: { runId: string }) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { run, events, receivedAt, connection, loadError, refresh } = useRunStatus(runId)

  if (loadError) {
    const notFound = loadError instanceof ApiError && loadError.status === 404
    return (
      <PageCard title={notFound ? '실행을 찾을 수 없습니다' : '실행을 불러오지 못했습니다'} subtitle={`실행 ID: ${runId}`}>
        <Alert
          type={notFound ? 'warning' : 'error'}
          showIcon
          title={errorMessage(loadError)}
          action={<Button onClick={() => navigate('/start')}>업로드로 돌아가기</Button>}
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

  const view = chosenView(run.status, params.get('view'))
  const screen = view ? SCREEN_OF_VIEW[view] : screenFor(run.status, run.interrupt?.kind)
  const unreached = unreachedScreens(run.status, displayStage(run.stage, events))

  function chooseView(next: ResultView) {
    setParams((p) => {
      const q = new URLSearchParams(p)
      q.set('view', next)
      return q
    })
  }

  return (
    <Flex vertical gap={24}>
      <StageSteps current={screen} unreached={unreached} />
      {/* 개발용 AI Workspace (#281). 기존 흐름은 그대로 두고 새 탭으로 연다.
          mock은 실행을 탭 메모리에만 두므로 같은 탭에서 연다 (새 탭에서는 실행을 찾지 못함) */}
      <Flex justify="flex-end" style={{ marginTop: -12 }}>
        <Link
          to={`/workspace?run=${encodeURIComponent(run.run_id)}`}
          {...(WORKSPACE_NEW_TAB ? { target: '_blank', rel: 'noopener' } : {})}
        >
          작업공간 열기 (개발용){WORKSPACE_NEW_TAB ? ' ↗' : ''}
        </Link>
      </Flex>
      <WithActivity side={<ActivityPanel events={events} receivedAt={receivedAt} connection={connection} status={run.status} />}>
        <Flex vertical gap={24}>
          {view && (
            <Segmented<ResultView>
              aria-label="볼 화면"
              value={view}
              onChange={chooseView}
              options={resultViews(run.status).map((v) => ({ value: v, label: VIEW_LABEL[v] }))}
            />
          )}
          {screen === 'UI-04' ? (
            <ProgressPanel run={run} events={events} connection={connection} onChanged={refresh} />
          ) : screen === 'UI-02' ? (
            <ExtractionPanel run={run} events={events} onChanged={refresh} />
          ) : screen === 'UI-03' ? (
            <RequirementsPanel run={run} onChanged={refresh} />
          ) : screen === 'UI-05' ? (
            <WorkspacePanel run={run} />
          ) : screen === 'UI-06' ? (
            <ReviewPanel run={run} events={events} onChanged={refresh} />
          ) : (
            <DownloadPanel run={run} />
          )}
        </Flex>
      </WithActivity>
    </Flex>
  )
}

export default RunPage
