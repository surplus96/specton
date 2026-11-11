import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// 개발 서버에서 FastAPI로 요청을 넘긴다. UI는 API만 호출한다.
// API 주소는 VITE_DEV_API_ORIGIN(.env.local)으로 바꿀 수 있고, 기본은 http://localhost:8000 이다.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiOrigin = env.VITE_DEV_API_ORIGIN || 'http://localhost:8000'
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/runs': apiOrigin,
        '/health': apiOrigin,
      },
    },
    build: {
      // mermaid·React Flow는 해당 화면을 열 때만 따로 불러온다
      chunkSizeWarningLimit: 1500,
    },
  }
})
