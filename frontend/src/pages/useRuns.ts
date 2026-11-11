// 내 실행 목록 (GET /runs). 사이드바·시작 화면·지난 작업이 같이 쓴다.
// 이 브라우저 세션이 시작한 실행만 서버가 돌려준다(ADR-0011). 실패는 「없음」과 따로 알린다.
import { useCallback, useEffect, useState } from 'react'
import { listRuns } from '../api/client.ts'
import { RUNS_CHANGED } from '../api/runNames.ts'
import type { RunSummary } from '../api/types.ts'

export type RunsState = {
  runs: RunSummary[] | null
  failed: boolean
  reload: () => void
}

export function useRuns(limit = 20): RunsState {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [key, setKey] = useState(0)
  const reload = useCallback(() => setKey((k) => k + 1), [])

  useEffect(() => {
    let alive = true
    setFailed(false)
    listRuns({ limit })
      .then((list) => alive && setRuns(list))
      .catch(() => {
        if (!alive) return
        setFailed(true)
        setRuns((prev) => prev ?? null)
      })
    return () => {
      alive = false
    }
  }, [limit, key])

  useEffect(() => {
    window.addEventListener(RUNS_CHANGED, reload)
    const timer = window.setInterval(() => { if (!document.hidden) reload() }, 15_000)
    return () => {
      window.removeEventListener(RUNS_CHANGED, reload)
      window.clearInterval(timer)
    }
  }, [reload])

  return { runs, failed, reload }
}
