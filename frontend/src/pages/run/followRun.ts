// 실행 하나를 따라가기: 상태 조회 + 이벤트(SSE) 연결 + 다시 연결.
// React와 분리해 테스트한다. 화면은 useRunStatus 훅으로 쓴다.
//
// - 화면의 기준은 항상 상태 조회(GET /runs/{id}) 결과다. 이벤트는 「바뀌었으니 다시 조회하라」는 신호와
//   진행 문장 기록으로 쓴다. 이벤트만으로 상태를 맞춰 가면 놓친 이벤트가 있을 때 화면이 틀어진다.
// - 연결이 끊기면 마지막 이벤트 ID부터 다시 받는다(Last-Event-ID). 연결 종료는 실행 취소가 아니다.
// - 409 EVENT_REPLAY_EXPIRED면 상태를 다시 조회하고 처음부터 다시 받는다 (docs/06 「SSE」).
import { getRun } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import { readEvents } from '../../api/events.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import { isFinished } from './screens.ts'

export type Connection = 'connecting' | 'live' | 'retrying' | 'closed'

export type FollowHandlers = {
  onStatus: (status: RunStatus) => void
  onEvent: (event: SseEvent) => void
  /** 이벤트를 처음부터 다시 받게 됐다. 쌓아 둔 이벤트를 비운다. */
  onReset: () => void
  onConnection: (connection: Connection) => void
}

export type FollowOptions = {
  signal: AbortSignal
  /** 끊긴 뒤 처음 다시 연결하기까지 기다리는 시간(ms). 실패가 이어지면 두 배씩, maxRetryMs까지 */
  retryMs?: number
  maxRetryMs?: number
  /** 이벤트가 몰려 와도 상태 조회는 한 번만 하도록 모으는 시간(ms) */
  refreshMs?: number
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve()
    const timer = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => (clearTimeout(timer), resolve()), { once: true })
  })
}

/**
 * 실행을 끝날 때까지 따라간다. 끝난 실행이면 지난 이벤트를 받은 뒤 돌아온다.
 * 처음 상태 조회가 실패하거나(404 등) 이벤트 연결이 404면 ApiError를 던진다.
 */
export async function followRun(runId: string, handlers: FollowHandlers, options: FollowOptions): Promise<void> {
  const { signal, retryMs = 1000, maxRetryMs = 10_000, refreshMs = 100 } = options
  let after = 0
  let wait = retryMs
  let refreshTimer: ReturnType<typeof setTimeout> | undefined

  const load = async () => {
    const status = await getRun(runId)
    if (!signal.aborted) handlers.onStatus(status)
    return status
  }
  const refreshSoon = () => {
    if (refreshTimer !== undefined) return
    refreshTimer = setTimeout(() => {
      refreshTimer = undefined
      if (!signal.aborted) load().catch(() => {}) // 실패하면 다음 이벤트·재연결 때 다시 조회한다
    }, refreshMs)
  }
  signal.addEventListener('abort', () => clearTimeout(refreshTimer), { once: true })

  handlers.onConnection('connecting')
  let status = await load()

  while (!signal.aborted) {
    try {
      await readEvents(runId, {
        after,
        signal,
        onEvent: (event) => {
          after = event.id
          wait = retryMs
          handlers.onConnection('live')
          handlers.onEvent(event)
          refreshSoon()
        },
      })
    } catch (err) {
      if (signal.aborted) return
      if (err instanceof ApiError && err.code === 'EVENT_REPLAY_EXPIRED') {
        after = 0
        handlers.onReset()
        status = await load()
        continue
      }
      if (err instanceof ApiError && err.status === 404) throw err
      // 그 밖(연결 실패·서버 오류)은 잠시 뒤 다시 연결한다
    }
    if (signal.aborted) return

    // 스트림이 닫혔다: 끝났는지 상태로 확인한다
    try {
      status = await load()
    } catch {
      // 조회도 안 되면 아래에서 기다렸다가 다시 시도한다
    }
    if (isFinished(status.status)) {
      handlers.onConnection('closed')
      return
    }
    handlers.onConnection('retrying')
    await sleep(wait, signal)
    wait = Math.min(wait * 2, maxRetryMs)
  }
}
