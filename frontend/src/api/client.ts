// 백엔드 API를 부르는 함수 모음. 화면 코드는 fetch를 직접 쓰지 않고 이 함수들만 쓴다.
// 엔드포인트와 규칙: docs/06-api.md, 계약: docs/api/openapi.json
import { ApiError } from './errors.ts'
import type {
  ArtifactKind,
  FileFormat,
  Pack,
  ResumeRequest,
  RunState,
  RunStatus,
  RunSummary,
  RunView,
  ViewSection,
} from './types.ts'

// 개발 중에는 같은 주소('')로 부르고 Vite 프록시가 FastAPI(8000)로 넘긴다.
// 테스트처럼 브라우저 밖에서는 절대 주소가 필요해 바꿀 수 있게 둔다.
let baseUrl = ''

export function setApiBaseUrl(url: string): void {
  baseUrl = url.replace(/\/$/, '')
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response
  try {
    // credentials: 세션 쿠키(specton_session)를 함께 보낸다 (ADR-0011)
    res = await fetch(baseUrl + path, { credentials: 'include', ...init })
  } catch (cause) {
    throw new ApiError(0, null, cause)
  }
  if (!res.ok) throw await ApiError.fromResponse(res)
  return res
}

async function sendJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init)
  return (await res.json()) as T
}

function jsonBody(body: unknown): RequestInit {
  return { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

const runPath = (runId: string) => `/runs/${encodeURIComponent(runId)}`

/** POST /runs — 파일을 올려 실행을 만든다. 202는 접수됐다는 뜻이지 설계 성공이 아니다. */
export function createRun(file: File, pack: Pack): Promise<RunStatus> {
  const form = new FormData()
  form.append('file', file)
  form.append('pack', pack)
  return sendJson<RunStatus>('/runs', { method: 'POST', body: form })
}

/** GET /runs — 내 실행 목록 (UI-01 「이전 실행」) */
export function listRuns(options: { status?: RunState; limit?: number } = {}): Promise<RunSummary[]> {
  const query = new URLSearchParams()
  if (options.status) query.set('status', options.status)
  if (options.limit) query.set('limit', String(options.limit))
  const qs = query.toString()
  return sendJson<RunSummary[]>(`/runs${qs ? `?${qs}` : ''}`)
}

/** GET /runs/{id} — 현재 상태. 화면을 처음 열 때·새로고침 뒤 상태 복구에 쓴다. */
export function getRun(runId: string): Promise<RunStatus> {
  return sendJson<RunStatus>(runPath(runId))
}

/** GET /runs/{id}/view — 화면용 데이터 (추출 블록·요구사항·설계·지적) */
export function getView(runId: string, section: ViewSection, revision?: number): Promise<RunView> {
  const query = new URLSearchParams({ section })
  if (revision !== undefined) query.set('revision', String(revision))
  return sendJson<RunView>(`${runPath(runId)}/view?${query}`)
}

/** POST /runs/{id}/resume — 확인 화면(UI-02·03·06)의 답을 보낸다. 409면 새로고침 안내. */
export function resumeRun(runId: string, request: ResumeRequest): Promise<RunStatus> {
  return sendJson<RunStatus>(`${runPath(runId)}/resume`, { method: 'POST', ...jsonBody(request) })
}

/** POST /runs/{id}/cancel — 취소 요청. 실행 중이면 cancel_requested, 대기 중이면 바로 cancelled. */
export function cancelRun(runId: string, expectedRevision: number): Promise<RunStatus> {
  return sendJson<RunStatus>(`${runPath(runId)}/cancel`, {
    method: 'POST',
    ...jsonBody({ expected_revision: expectedRevision }),
  })
}

/** GET /runs/{id}/events 주소 — SSE 연결(EventSource)에 쓴다 (4단계) */
export function eventsUrl(runId: string): string {
  return `${baseUrl}${runPath(runId)}/events`
}

/** GET /runs/{id}/artifacts/{kind} — 산출물 파일을 받는다. 파일 이름은 서버가 정한다. */
export async function downloadArtifact(
  runId: string,
  kind: ArtifactKind,
  fileFormat: FileFormat,
  revision: number,
): Promise<{ blob: Blob; fileName: string }> {
  const query = new URLSearchParams({ file_format: fileFormat, revision: String(revision) })
  const res = await send(`${runPath(runId)}/artifacts/${kind}?${query}`)
  const fileName =
    fileNameFrom(res.headers.get('Content-Disposition')) ?? `specton-${kind}-r${revision}.${fileFormat}`
  return { blob: await res.blob(), fileName }
}

function fileNameFrom(disposition: string | null): string | null {
  if (!disposition) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (encoded) return decodeURIComponent(encoded[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : null
}

/** GET /health — 서버가 살아 있는지 */
export function health(): Promise<{ status: string; version?: string }> {
  return sendJson('/health')
}
