import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// 개발 서버에서 FastAPI(8000)로 요청을 넘긴다. UI는 API만 호출한다.
const API_ORIGIN = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/runs': API_ORIGIN,
      '/health': API_ORIGIN,
    },
  },
})
