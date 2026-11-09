import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { ConfigProvider } from 'antd'
import koKR from 'antd/locale/ko_KR'
import './index.css'
import App from './App.tsx'
import { theme } from './theme.ts'

// mock 서버 (구현 가이드 강의 08)
//   npm run dev                 진짜 FastAPI(8000)에 붙는다 (vite.config.ts 프록시)
//   npm run dev -- --mode mock  mock 서버로 띄운다 (npm run dev:mock 과 같음)
// 화면 코드는 같은 API 함수(api/client.ts)를 부르고, mock은 그 요청을 중간에서 대신 받는다.
// 배포 빌드(npm run build)에서는 import.meta.env.DEV가 false라 mock 코드가 들어가지 않는다.
async function startMock() {
  if (import.meta.env.DEV && import.meta.env.MODE === 'mock') {
    const { startMockWorker } = await import('./mocks/browser.ts')
    await startMockWorker()
  }
}

// BrowserRouter: 주소(URL)에 따라 화면을 바꾼다.
// ConfigProvider: theme.ts의 색·글꼴과 한국어 문구를 모든 Ant Design 부품에 적용한다.
startMock().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <ConfigProvider theme={theme} locale={koKR}>
          <App />
        </ConfigProvider>
      </BrowserRouter>
    </StrictMode>,
  )
})
