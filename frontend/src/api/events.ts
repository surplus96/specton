// 실행 진행 이벤트(SSE) 받기. GET /runs/{id}/events (docs/06-api.md「SSE」, 구현 가이드 강의 08)
//
// - 서버는 이름 있는 이벤트(event: status 등)를 보낸다. onmessage로는 받지 못해 이름마다 addEventListener로 받는다.
// - 끊기면 브라우저가 Last-Event-ID를 붙여 알아서 다시 연결한다. 직접 다시 열지 않는다.
// - 실행이 끝나면 서버가 스트림을 닫는데, 브라우저는 이것도 끊김으로 보고 다시 연결한다.
//   그래서 끝 이벤트(completed·cancelled·error)를 받으면 직접 close()한다.
// - 브라우저가 다시 연결하지 못하고 연결을 닫으면(404·409 응답 등) onClosed를 부른다.
//   그때 할 일(상태 다시 읽기·새로 열기)은 부른 쪽(followRun)이 정한다.
import { eventsUrl } from './client.ts'
import type { SseEvent } from './types.ts'

type EventName = SseEvent['event']

const EVENT_NAMES: readonly EventName[] = ['status', 'interrupt', 'artifact', 'error', 'completed', 'cancelled']

/** EventSource.CLOSED. 전역 EventSource가 없는 테스트 환경에서도 읽히게 값으로 둔다. */
const CLOSED = 2

/** 받으면 연결을 닫는 이벤트 */
export const FINAL_EVENTS: ReadonlySet<EventName> = new Set(['completed', 'cancelled', 'error'])

/** EventSource 생성자. 테스트에서 바꿔 넣는다 (Node에는 EventSource가 없다). */
export type EventSourceFactory = (url: string) => EventSource

const browserEventSource: EventSourceFactory = (url) => new EventSource(url, { withCredentials: true })

export type WatchHandlers = {
  onEvent: (event: SseEvent) => void
  /** 연결이 열렸다(처음·다시 연결 모두) */
  onOpen?: () => void
  /** 연결이 완전히 닫혔다. finished: 끝 이벤트를 받아 직접 닫음 / lost: 브라우저가 다시 연결을 포기함 */
  onClosed: (reason: 'finished' | 'lost') => void
}

/** 이벤트 연결을 연다. 돌려준 함수를 부르면 닫는다 (React useEffect 정리 함수에서 부른다). */
export function watchRun(runId: string, handlers: WatchHandlers, open: EventSourceFactory = browserEventSource): () => void {
  const source = open(eventsUrl(runId))
  let closed = false
  const close = (reason?: 'finished' | 'lost') => {
    if (closed) return
    closed = true
    source.close()
    if (reason) handlers.onClosed(reason)
  }

  source.addEventListener('open', () => handlers.onOpen?.())

  for (const name of EVENT_NAMES) {
    source.addEventListener(name, (raw: Event) => {
      // 'error'는 서버가 보낸 error 이벤트(data 있음)와 브라우저의 연결 오류(data 없음)가 같은 이름으로 온다
      if (!(raw instanceof MessageEvent) || typeof raw.data !== 'string') {
        if (name === 'error' && source.readyState === CLOSED) close('lost')
        return // 연결 중(CONNECTING)이면 브라우저가 다시 붙는다
      }
      let data: SseEvent['data']
      try {
        data = JSON.parse(raw.data) as SseEvent['data']
      } catch {
        return // 모양이 깨진 이벤트는 버린다
      }
      handlers.onEvent({ id: Number(raw.lastEventId), event: name, data })
      if (FINAL_EVENTS.has(name)) close('finished')
    })
  }

  return () => close()
}
