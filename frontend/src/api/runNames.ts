// 실행 ↔ 올린 파일 이름 (이 브라우저에서만).
// API의 실행 목록(RunSummary)에는 파일 이름이 없다. 백엔드를 고치지 않고, 이 브라우저에서 올린 실행만
// 파일 이름을 기억해 카드 제목·검색에 쓴다. 다른 브라우저에서 만든 실행은 이름 없이 날짜로 보인다.
// 저장소를 쓸 수 없는 환경(사생활 보호 창 등)에서도 화면은 그대로 동작한다.

const KEY = 'specton.runNames.v1'
export const RUNS_CHANGED = 'specton:runs-changed'

type Store = Record<string, string>

function read(): Store {
  try {
    const raw = window.localStorage.getItem(KEY)
    const data: unknown = raw ? JSON.parse(raw) : {}
    return data && typeof data === 'object' && !Array.isArray(data)
      ? Object.fromEntries(Object.entries(data).filter(([, value]) => typeof value === 'string'))
      : {}
  } catch {
    return {}
  }
}

export function rememberRunName(runId: string, fileName: string): void {
  try {
    const store = read()
    store[runId] = fileName
    window.localStorage.setItem(KEY, JSON.stringify(store))
  } catch {
    // 저장하지 못해도 실행은 그대로 쓴다
  }
}

export function runFileName(runId: string): string | null {
  return read()[runId] ?? null
}

/** 확장자를 뺀 이름. 카드 제목에 쓴다 */
export function titleFromFile(fileName: string): string {
  const dot = fileName.lastIndexOf('.')
  return (dot > 0 ? fileName.slice(0, dot) : fileName).replace(/[_]+/g, ' ').trim()
}

/** 카드 제목과 파일 이름. 이 브라우저에서 올리지 않은 실행은 「설계 실행」 */
export function runTitle(runId: string): { title: string; file: string | null } {
  const file = runFileName(runId)
  return { title: file ? titleFromFile(file) : '설계 실행', file }
}

/** 실행 목록이 바뀌었다고 알린다(새 실행·취소 등). 사이드바·시작 화면이 다시 읽는다 */
export function notifyRunsChanged(): void {
  window.dispatchEvent(new Event(RUNS_CHANGED))
}
