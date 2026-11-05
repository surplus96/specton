// 브라우저에서 mock 서버를 켠다. main.tsx가 개발 모드일 때만 불러온다.
import { setupWorker } from 'msw/browser'
import { createMockBackend } from './backend.ts'

export const mockBackend = createMockBackend()

export function startMockWorker() {
  return setupWorker(...mockBackend.handlers).start({
    // mock이 없는 요청(화면 파일·이미지 등)은 그대로 보낸다
    onUnhandledRequest: 'bypass',
  })
}
