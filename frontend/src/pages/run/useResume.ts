// 확인 화면(UI-02·03·06) 공통: 확인 답 보내기 (POST /runs/{id}/resume).
// - 요청 중에는 sending으로 버튼을 막는다
// - interrupt_id와 revision은 지금 읽은 상태(getRun)에서 넣는다 (구현 가이드 강의 10)
// - 409면 같은 요청을 자동으로 다시 보내지 않는다. 상태를 다시 읽고, 화면 데이터도 다시 읽게
//   reloadKey를 올린 뒤 「다른 곳에서 먼저 처리되었습니다」를 안내한다 (강의 04·11)
// - 422 등은 서버 문장을 그대로 보인다 (「REQ-02: …」처럼 대상 ID로 시작)
import { useCallback, useState } from 'react'
import { resumeRun } from '../../api/client.ts'
import { ApiError, errorMessage } from '../../api/errors.ts'
import type { ResumeRequest, RunStatus } from '../../api/types.ts'

export const CONFLICT_NOTICE = '다른 곳에서 먼저 처리되었습니다. 최신 상태를 불러왔습니다.'

export function useResume(run: RunStatus, onChanged: () => Promise<void>) {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const interruptId = run.interrupt?.interrupt_id ?? null

  const send = useCallback(
    /** 보냈으면 true. 실패하면 false (오류·안내는 error·notice에 담긴다) */
    async (response: ResumeRequest['response']): Promise<boolean> => {
      if (!interruptId) return false
      setSending(true)
      setError(null)
      setNotice(null)
      try {
        await resumeRun(run.run_id, { interrupt_id: interruptId, expected_revision: run.revision, response })
        await onChanged()
        return true
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setNotice(CONFLICT_NOTICE)
          await onChanged().catch(() => {})
          setReloadKey((k) => k + 1)
        } else {
          setError(errorMessage(err))
        }
        return false
      } finally {
        setSending(false)
      }
    },
    [run.run_id, run.revision, interruptId, onChanged],
  )

  return {
    send,
    sending,
    error,
    notice,
    /** 화면 데이터를 다시 읽을 때 의존값으로 쓴다 (409 뒤, 「다시 불러오기」) */
    reloadKey,
    reload: () => setReloadKey((k) => k + 1),
    /** 지금 답할 수 있는지 (확인 요청이 있을 때만) */
    canAnswer: interruptId !== null,
  }
}
