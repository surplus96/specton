// 실행 화면용 훅: followRun을 React 상태로 바꾼다.
import { useCallback, useEffect, useState } from 'react'
import { getRun } from '../../api/client.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import { followRun, type Connection } from './followRun.ts'

export type RunLive = {
  run: RunStatus | null
  events: SseEvent[]
  /** 이벤트 id → 이 화면이 받은 시각(ms). 서버 이벤트에는 시각이 없다 */
  receivedAt: Record<number, number>
  connection: Connection
  /** 상태 조회 실패(없는 실행 등). 화면 전체를 안내로 바꾼다. */
  loadError: unknown
  /** 취소처럼 화면에서 요청을 보낸 뒤 상태를 바로 다시 읽는다 */
  refresh: () => Promise<void>
}

export function useRunStatus(runId: string): RunLive {
  const [run, setRun] = useState<RunStatus | null>(null)
  const [events, setEvents] = useState<SseEvent[]>([])
  const [receivedAt, setReceivedAt] = useState<Record<number, number>>({})
  const [connection, setConnection] = useState<Connection>('connecting')
  const [loadError, setLoadError] = useState<unknown>(null)

  useEffect(() => {
    // 연결은 useEffect 안에서 열고, 정리 함수에서 닫는다 (강의 08)
    const controller = new AbortController()
    setRun(null)
    setEvents([])
    setReceivedAt({})
    setLoadError(null)
    followRun(
      runId,
      {
        onStatus: setRun,
        onEvent: (event) => {
          const at = Date.now()
          setEvents((prev) => [...prev, event])
          setReceivedAt((prev) => (event.id in prev ? prev : { ...prev, [event.id]: at }))
        },
        onConnection: setConnection,
      },
      { signal: controller.signal },
    ).catch((err: unknown) => {
      if (controller.signal.aborted) return
      setLoadError(err)
      setConnection('closed')
    })
    return () => controller.abort()
  }, [runId])

  const refresh = useCallback(async () => {
    setRun(await getRun(runId))
  }, [runId])

  return { run, events, receivedAt, connection, loadError, refresh }
}
