// 실행 화면용 훅: followRun을 React 상태로 바꾼다.
import { useCallback, useEffect, useState } from 'react'
import { getRun } from '../../api/client.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import { followRun, type Connection } from './followRun.ts'

export type RunLive = {
  run: RunStatus | null
  events: SseEvent[]
  connection: Connection
  /** 처음 상태 조회 실패(없는 실행 등). 화면 전체를 안내로 바꾼다. */
  loadError: unknown
  /** 취소처럼 화면에서 요청을 보낸 뒤 상태를 바로 다시 읽는다 */
  refresh: () => Promise<void>
}

export function useRunStatus(runId: string): RunLive {
  const [run, setRun] = useState<RunStatus | null>(null)
  const [events, setEvents] = useState<SseEvent[]>([])
  const [connection, setConnection] = useState<Connection>('connecting')
  const [loadError, setLoadError] = useState<unknown>(null)

  useEffect(() => {
    const controller = new AbortController()
    setRun(null)
    setEvents([])
    setLoadError(null)
    followRun(
      runId,
      {
        onStatus: setRun,
        onEvent: (event) => setEvents((prev) => [...prev, event]),
        onReset: () => setEvents([]),
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

  return { run, events, connection, loadError, refresh }
}
