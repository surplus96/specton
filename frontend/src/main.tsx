import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import './index.css'
import App from './App.tsx'
import { setApiBaseUrl } from './api/client.ts'

// API 주소: 비우면 화면과 같은 주소(개발은 Vite 프록시, 배포는 Caddy)로 부른다.
// 다른 도메인의 API를 쓰려면 빌드할 때 VITE_API_BASE_URL을 넣는다 (이때는 백엔드 CORS·쿠키 설정이 필요하다).
const apiBase = import.meta.env.VITE_API_BASE_URL
if (apiBase) setApiBaseUrl(apiBase)

// mock 서버 (구현 가이드 강의 08)
//   npm run dev                 진짜 FastAPI(8000)에 붙는다 (vite.config.ts 프록시)
//   npm run dev -- --mode mock  mock 서버로 띄운다 (npm run dev:mock 과 같음)
// 배포 빌드(npm run build)에서는 import.meta.env.DEV가 false라 mock 코드가 들어가지 않는다.
async function startMock() {
  if (import.meta.env.DEV && import.meta.env.MODE === 'mock') {
    const { startMockWorker } = await import('./mocks/browser.ts')
    await startMockWorker()
  }
}

startMock().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>,
  )
})
