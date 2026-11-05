import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { ConfigProvider } from 'antd'
import koKR from 'antd/locale/ko_KR'
import './index.css'
import App from './App.tsx'
import { theme } from './theme.ts'

// mock 서버: `npm run dev`에서는 기본으로 켜진다. 진짜 FastAPI에 붙이려면
// frontend/.env.local 파일에 VITE_API_MOCK=off 를 적고 dev 서버를 다시 켠다.
// 배포 빌드(npm run build)에서는 import.meta.env.DEV가 false라 mock 코드가 들어가지 않는다.
async function startMock() {
  if (import.meta.env.DEV && import.meta.env.VITE_API_MOCK !== 'off') {
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
