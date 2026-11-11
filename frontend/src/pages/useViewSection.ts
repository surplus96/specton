import { useCallback, useEffect, useState } from 'react'
import { getView } from '../api/client.ts'
import type { RunView, ViewSection } from '../api/types.ts'

/** 섹션별 조회 상태를 분리한다. 이전 실행·revision 결과로 새 화면을 채우지 않는다. */
export function useViewSection(runId: string, revision: number, section: ViewSection, refreshKey: unknown = null) {
  const key = `${runId}:${revision}:${section}`
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<{ key: string; data: RunView | null; error: unknown }>({ key, data: null, error: null })
  useEffect(() => {
    let alive = true
    setState({ key, data: null, error: null })
    getView(runId, section, revision).then(
      (data) => { if (alive) setState({ key, data, error: null }) },
      (error: unknown) => { if (alive) setState({ key, data: null, error }) },
    )
    return () => { alive = false }
  }, [runId, revision, section, key, attempt, refreshKey])
  return { ...(state.key === key ? state : { data: null, error: null }), reload: useCallback(() => setAttempt((n) => n + 1), []) }
}
