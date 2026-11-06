// 실행 진행 이벤트(SSE) 읽기. GET /runs/{id}/events (docs/06-api.md「SSE」)
//
// 브라우저 EventSource 대신 fetch로 읽는다.
// - EventSource는 409(EVENT_REPLAY_EXPIRED) 같은 오류 본문을 읽지 못해 다음 행동을 정할 수 없다.
// - fetch는 Node 테스트에서도 돌고, 세션 쿠키·Last-Event-ID를 직접 다룰 수 있다.
// 다시 연결하기는 이 파일이 아니라 화면 훅(useRunStatus)이 맡는다.
import { eventsUrl } from './client.ts'
import { ApiError } from './errors.ts'
import type { SseEvent } from './types.ts'

const EVENT_NAMES: ReadonlySet<string> = new Set([
  'status',
  'interrupt',
  'artifact',
  'error',
  'completed',
  'cancelled',
])

/** 끝난 실행을 알리는 이벤트. 이 이벤트 뒤에는 다시 연결하지 않는다. */
export const FINAL_EVENTS: ReadonlySet<SseEvent['event']> = new Set(['completed', 'cancelled'])

/**
 * SSE 한 덩어리("id: …\nevent: …\ndata: …")를 이벤트로 바꾼다.
 * 주석 줄(": keep-alive")만 있거나 모양이 맞지 않으면 null.
 */
export function parseFrame(frame: string): SseEvent | null {
  let id: number | null = null
  let event: string | null = null
  const data: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line === '' || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'id') id = /^\d+$/.test(value) ? Number(value) : null
    else if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  if (id === null || event === null || !EVENT_NAMES.has(event) || data.length === 0) return null
  try {
    return { id, event: event as SseEvent['event'], data: JSON.parse(data.join('\n')) }
  } catch {
    return null
  }
}

/**
 * 이벤트 스트림을 연결해 이벤트마다 onEvent를 부른다. 서버가 스트림을 닫으면 끝난다.
 * - after: 마지막으로 받은 이벤트 ID. 0이면 처음부터 받는다.
 * - 연결 전 오류(404·409 등)는 ApiError로 던진다. 도중에 끊기면 그냥 끝난다.
 */
export async function readEvents(
  runId: string,
  options: { after: number; signal?: AbortSignal; onEvent: (event: SseEvent) => void },
): Promise<void> {
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  if (options.after > 0) headers['Last-Event-ID'] = String(options.after)
  let res: Response
  try {
    res = await fetch(eventsUrl(runId), { credentials: 'same-origin', headers, signal: options.signal })
  } catch (cause) {
    if (options.signal?.aborted) return
    throw new ApiError(0, null, cause)
  }
  if (!res.ok) throw await ApiError.fromResponse(res)
  if (!res.body) return

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  // fetch를 중단해도 읽기가 바로 끝나지 않는 환경이 있어(테스트의 mock 등) 읽기도 직접 끊는다
  const stop = () => void reader.cancel().catch(() => {})
  options.signal?.addEventListener('abort', stop, { once: true })
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += value
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const event = parseFrame(frame)
        if (event) options.onEvent(event)
      }
    }
  } catch (err) {
    if (options.signal?.aborted) return
    // 도중에 끊긴 연결은 실패가 아니다(docs/06: 연결 종료는 실행 취소가 아님). 부른 쪽이 다시 연결한다.
    if (err instanceof TypeError || (err instanceof DOMException && err.name === 'AbortError')) return
    throw err
  } finally {
    options.signal?.removeEventListener('abort', stop)
    reader.releaseLock()
  }
}
