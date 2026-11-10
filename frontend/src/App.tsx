import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router'
import AppLayout from './layout/AppLayout.tsx'
import HomePage from './pages/HomePage.tsx'
import UploadPage from './pages/UploadPage.tsx'
import RunPage from './pages/RunPage.tsx'
import NotFoundPage from './pages/NotFoundPage.tsx'

// AI Workspace(개발용 결과 확인, #281): React Flow·elkjs가 커서 이 주소에서만 불러온다
const AiWorkspacePage = lazy(() => import('./pages/ai-workspace/AiWorkspacePage.tsx'))

// 주소 → 화면 연결표 (docs/09-ui-flow.md, 구현 가이드 강의 04·09)
//   /             첫 화면: 팀·프로젝트 소개
//   /start        UI-01 실행 시작(업로드)
//   /?run=<id>    실행 하나의 화면. UI-02~07 중 무엇을 보일지는 실행 상태로 정한다.
//                 실행 ID가 주소에 있어 새로고침해도 같은 실행으로 돌아온다 (TC-F19)
//   /intro        예전 소개 주소 → / 로 보낸다
//   /workspace?run=<id>  AI Workspace: 실행 상태·문서 추적·ERD 캔버스·검증 결과 (개발용, #281). 어두운 화면이라 공통 틀 밖
//   그 밖         없는 주소 안내
// 주의: /runs 로 시작하는 주소는 API용이다(vite.config.ts 프록시). 화면 주소에 쓰지 않는다.
function StartPage() {
  const [params] = useSearchParams()
  const runId = params.get('run')
  // key: 실행 ID가 바뀌면 화면 상태를 새로 시작한다
  return runId ? <RunPage key={runId} runId={runId} /> : <HomePage />
}

function App() {
  return (
    <Routes>
      <Route
        path="workspace"
        element={
          <Suspense fallback={<div style={{ padding: 32 }}>작업공간을 불러오는 중…</div>}>
            <AiWorkspacePage />
          </Suspense>
        }
      />
      <Route element={<AppLayout />}>
        <Route index element={<StartPage />} />
        <Route path="start" element={<UploadPage />} />
        <Route path="intro" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
