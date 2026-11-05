import { Route, Routes } from 'react-router'
import AppLayout from './layout/AppLayout.tsx'
import HomePage from './pages/HomePage.tsx'
import UploadPage from './pages/UploadPage.tsx'
import RunPage from './pages/RunPage.tsx'
import NotFoundPage from './pages/NotFoundPage.tsx'

// 주소 → 화면 연결표 (docs/09-ui-flow.md)
//   /            첫 화면(팀·프로젝트 소개)
//   /new         UI-01 실행 시작(업로드)
//   /run/:runId  실행 하나의 화면. UI-02~07 중 무엇을 보일지는 실행 상태로 정한다(4단계에서 연결)
//   그 밖        없는 주소 안내
// 주의: /runs 로 시작하는 주소는 API용이다(vite.config.ts 프록시). 화면 주소에 쓰지 않는다.
function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="new" element={<UploadPage />} />
        <Route path="run/:runId" element={<RunPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
