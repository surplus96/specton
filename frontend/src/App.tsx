import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router'
import AppLayout from './layout/AppLayout.tsx'
import LazyBoundary from './layout/LazyBoundary.tsx'
import AboutPage from './pages/AboutPage.tsx'
import NotFoundPage from './pages/NotFoundPage.tsx'
import RunPage from './pages/RunPage.tsx'
import RunsPage from './pages/RunsPage.tsx'
import StartPage from './pages/StartPage.tsx'
import Loading from './ui/Loading.tsx'

// AI Workspace(개발용 결과 확인, #281): React Flow·elkjs가 커서 이 주소에서만 불러온다
const AiWorkspacePage = lazy(() => import('./pages/ai-workspace/AiWorkspacePage.tsx'))

// 주소 → 화면
//   /                  새 작업(시작 화면). 첫 방문이면 안내, 작업이 있으면 진행 중 작업도 보인다
//   /?run=<id>         실행 하나의 화면. UI-02~07 중 무엇을 보일지는 실행 상태로 정한다 (새로고침해도 같은 실행)
//   /history           지난 작업 (/history?search=1 이면 검색 칸에 바로 커서)
//   /about             서비스 안내 · 팀 소개 (Docs)
//   /start, /intro     예전 주소 → / , /about
//   /workspace?run=<id>  AI Workspace (개발용, 공통 왼쪽 메뉴 안에 표시)
// 주의: /runs·/health로 시작하는 주소는 API용이다(vite.config.ts 프록시·Caddy). 화면 주소에 쓰지 않는다.
function Home() {
  const [params] = useSearchParams()
  const runId = params.get('run')
  // key: 실행 ID가 바뀌면 화면 상태를 새로 시작한다
  return runId ? <RunPage key={runId} runId={runId} /> : <StartPage />
}

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route
          path="workspace"
          element={
            <LazyBoundary>
              <Suspense fallback={<Loading text="작업공간을 불러오는 중이에요" />}>
                <AiWorkspacePage />
              </Suspense>
            </LazyBoundary>
          }
        />
        <Route index element={<Home />} />
        <Route path="history" element={<RunsPage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="start" element={<Navigate to="/" replace />} />
        <Route path="intro" element={<Navigate to="/about" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
