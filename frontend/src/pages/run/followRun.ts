// 실행 하나를 따라가기: 상태 조회 + 이벤트(SSE) 연결 (구현 가이드 강의 04·08).
// React와 분리해 테스트한다. 화면은 useRunStatus 훅으로 쓴다.
//
// - 화면의 기준은 항상 상태 조회(GET /runs/{id}) 결과다. 이벤트는 「다시 읽어라」는 신호와 진행 기록에만 쓴다.
// - 끊기면 브라우저(EventSource)가 알아서 다시 붙는다. 끝 이벤트를 받으면 watchRun이 직접 닫는다.
// - 연결이 완전히 닫히면(onClosed) 상태를 다시 읽고, 아직 끝나지 않았으면 새로 연다.
//   새 연결은 처음 이벤트부터 다시 보내므로 id가 같은 이벤트는 한 번만 넘긴다.
//   (409 EVENT_REPLAY_EXPIRED도 여기로 온다: 상태를 다시 읽은 뒤 SSE를 새로 연다, 강의 11)
import { getRun } from '../../api/client.ts'
import { watchRun, type EventSourceFactory } from '../../api/events.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import { isFinished } from './screens.ts'

export type Connection = 'connecting' | 'live' | 'retrying' | 'closed'

export type FollowHandlers = {
  onStatus: (status: RunStatus) => void
  onEvent: (event: SseEvent) => void
  onConnection: (connection: Connection) => void
}

export type FollowOptions = {
  signal: AbortSignal
  /** 연결이 닫힌 뒤 새로 열기까지 기다리는 시간(ms). 이어서 닫히면 두 배씩, maxRetryMs까지 */
  retryMs?: number
  maxRetryMs?: number
  /** 이벤트가 몰려 와도 상태 조회는 한 번만 하도록 모으는 시간(ms) */
  refreshMs?: number
  /** EventSource 생성자 (테스트용) */
  open?: EventSourceFactory
}

/**
 * 실행을 끝날 때까지 따라간다. 끝나거나 signal로 멈추면 돌아온다.
 * 상태 조회가 실패하면(없는 실행 404 등) 그 오류로 끝난다.
 */
export function followRun(runId: string, handlers: FollowHandlers, options: FollowOptions): Promise<void> {
  const { signal, retryMs = 1000, maxRetryMs = 10_000, refreshMs = 100, open } = options
  const seen = new Set<number>()
  let wait = retryMs
  let closeSource: (() => void) | undefined
  let refreshTimer: ReturnType<typeof setTimeout> | undefined
  let retryTimer: ReturnType<typeof setTimeout> | undefined

  return new Promise<void>((resolve, reject) => {
    const stop = () => {
      clearTimeout(refreshTimer)
      clearTimeout(retryTimer)
      closeSource?.()
    }
    const finish = () => {
      stop()
      resolve()
    }
    const fail = (err: unknown) => {
      stop()
      reject(err)
    }
    signal.addEventListener('abort', finish, { once: true })

    const load = async () => {
      const status = await getRun(runId)
      if (!signal.aborted) handlers.onStatus(status)
      return status
    }
    const refreshSoon = () => {
      if (refreshTimer !== undefined) return
      refreshTimer = setTimeout(() => {
        refreshTimer = undefined
        if (!signal.aborted) load().catch(() => {}) // 실패하면 다음 이벤트·재연결 때 다시 읽는다
      }, refreshMs)
    }

    const connect = () => {
      if (signal.aborted) return
      closeSource = watchRun(
        runId,
        {
          onOpen: () => {
            wait = retryMs
            handlers.onConnection('live')
          },
          onEvent: (event) => {
            if (seen.has(event.id)) return
            seen.add(event.id)
            handlers.onEvent(event)
            refreshSoon()
          },
          onClosed: () => {
            if (signal.aborted) return
            load().then(
              (status) => {
                if (signal.aborted) return
                if (isFinished(status.status)) {
                  handlers.onConnection('closed')
                  finish()
                  return
                }
                handlers.onConnection('retrying')
                retryTimer = setTimeout(connect, wait)
                wait = Math.min(wait * 2, maxRetryMs)
              },
              fail,
            )
          },
        },
        open,
      )
    }

    handlers.onConnection('connecting')
    load().then(() => connect(), fail)
  })
}
