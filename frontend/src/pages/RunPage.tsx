import { useEffect, useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ApiError, errorMessage } from '../api/errors.ts'
import { runFileName } from '../api/runNames.ts'
import Icon from '../layout/Icon.tsx'
import StageSteps, { type ScreenId } from '../layout/StageSteps.tsx'
import Button from '../ui/Button.tsx'
import Loading from '../ui/Loading.tsx'
import Notice from '../ui/Notice.tsx'
import Segmented from '../ui/Segmented.tsx'
import ExtractionPanel from './extraction/ExtractionPanel.tsx'
import RequirementsPanel from './requirements/RequirementsPanel.tsx'
import ReviewPanel from './review/ReviewPanel.tsx'
import ActivityPanel from './run/ActivityPanel.tsx'
import ProgressPanel from './run/ProgressPanel.tsx'
import { displayStage, screenFor, unreachedScreens } from './run/screens.ts'
import { useRunStatus } from './run/useRunStatus.ts'
import DownloadPanel from './workspace/DownloadPanel.tsx'
import WorkspacePanel from './workspace/WorkspacePanel.tsx'
import { VIEW_LABEL, chosenView, resultViews, type ResultView } from './workspace/rules.ts'

// 실행 하나의 화면 (/?run=<runId>).
// 상태를 조회하고 이벤트(SSE)로 따라가며, 상태에 맞는 화면(UI-02~07)을 고른다 (run/screens.ts).
// 결과가 있으면(최종 검토 대기·완료) 위쪽에서 결과 작업공간(UI-05)으로 바꿔 볼 수 있다 (&view=workspace).
// 새로고침해도 상태 조회와 주소로 같은 화면에 돌아온다.
// 서버 작업 패널은 설계 진행(UI-04)에서는 오른쪽에, 표가 넓은 확인·결과 화면에서는 본문 아래에 둔다.
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
  const file = runFileName(runId)
  const lastScreen = useRef<ScreenId | null>(null)
  const viewParam = params.get('view')
  const currentScreen: ScreenId | null = run
    ? (() => {
        const v = chosenView(run.status, viewParam)
        return v ? SCREEN_OF_VIEW[v] : screenFor(run.status, run.interrupt?.kind)
      })()
    : null

  // 화면이 바뀌면 맨 위로 (스크롤한 채로 새 화면 중간에 떨어지지 않게)
  useEffect(() => {
    if (!currentScreen) return
    if (lastScreen.current !== null && lastScreen.current !== currentScreen) window.scrollTo({ top: 0 })
    lastScreen.current = currentScreen
  }, [currentScreen])

  const label = file ?? '이름 없는 작업'

  if (loadError) {
    const notFound = loadError instanceof ApiError && loadError.status === 404
    return (
      <section className="screen" style={{ paddingTop: 24 }}>
        <p className="eyebrow">실행 ID {runId}</p>
        <h1 className="title" style={{ marginBottom: 24 }}>
          {notFound ? (
            <>
              실행을 <strong>찾을 수 없어요</strong>
            </>
          ) : (
            <>
              실행을 <strong>불러오지 못했어요</strong>
            </>
          )}
        </h1>
        <Notice
          kind={notFound ? 'warning' : 'error'}
          title={errorMessage(loadError)}
          action={
            <div className="row">
              {!notFound && (
                <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
                  다시 불러오기
                </Button>
              )}
              <Button size="sm" onClick={() => navigate('/')}>
                새 작업으로
              </Button>
            </div>
          }
        >
          {notFound ? '다른 브라우저에서 시작했거나 세션이 바뀌면 이 실행을 볼 수 없어요.' : undefined}
        </Notice>
      </section>
    )
  }

  if (!run) return <Loading text="실행 상태를 불러오고 있어요" />

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
    <div>
      <StageSteps current={screen} unreached={unreached} />
      <div className="row row--between" style={{ marginBottom: 20 }}>
        {view ? (
          <Segmented<ResultView>
            label="볼 화면"
            value={view}
            onChange={chooseView}
            options={resultViews(run.status).map((v) => ({ value: v, label: VIEW_LABEL[v] }))}
          />
        ) : (
          <span />
        )}
        {/* 개발용 AI Workspace (#281). mock은 실행을 탭 메모리에만 두므로 같은 탭에서 연다 */}
        <Link
          className="topbar__link"
          style={{ fontSize: 14 }}
          to={`/workspace?run=${encodeURIComponent(run.run_id)}`}
          {...(WORKSPACE_NEW_TAB ? { target: '_blank', rel: 'noopener' } : {})}
        >
          작업공간 열기 (개발용)
          {WORKSPACE_NEW_TAB && <Icon name="external" size={14} />}
        </Link>
      </div>
      <div className={`run-layout${screen === 'UI-04' ? ' run-layout--side' : ''}`}>
        <div className="screen" key={screen} style={{ minWidth: 0 }}>
          {screen === 'UI-04' ? (
            <ProgressPanel run={run} events={events} connection={connection} onChanged={refresh} label={label} />
          ) : screen === 'UI-02' ? (
            <ExtractionPanel run={run} events={events} onChanged={refresh} label={label} />
          ) : screen === 'UI-03' ? (
            <RequirementsPanel run={run} onChanged={refresh} label={label} />
          ) : screen === 'UI-05' ? (
            <WorkspacePanel run={run} label={label} onReview={run.status === 'awaiting_review' ? () => chooseView('review') : undefined} />
          ) : screen === 'UI-06' ? (
            <ReviewPanel run={run} events={events} onChanged={refresh} label={label} />
          ) : (
            <DownloadPanel run={run} label={label} />
          )}
        </div>
        <aside className="run-layout__side">
          <ActivityPanel events={events} receivedAt={receivedAt} connection={connection} status={run.status} />
        </aside>
      </div>
    </div>
  )
}

export default RunPage
