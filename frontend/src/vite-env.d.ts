/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'off'이면 개발 모드에서도 mock 서버를 켜지 않고 진짜 API를 부른다 */
  readonly VITE_API_MOCK?: string
}
