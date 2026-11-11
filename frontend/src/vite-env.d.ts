/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 주소. 비우면 화면과 같은 주소로 부른다 (.env.example 참고) */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
