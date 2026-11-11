import { useEffect, useRef, useState } from 'react'
import type { RunStatus } from '../../api/types.ts'
import { STATUS_LABEL } from '../workspace/rules.ts'
import { runEyebrow } from './runHeader.ts'
export default function RunEyebrow({ screen, label, run }: { screen: string; label: string; run: Pick<RunStatus, 'run_id' | 'revision' | 'status'> }) {
  const [message, setMessage] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  async function copy() {
    try { await navigator.clipboard.writeText(run.run_id); setMessage('복사했어요') }
    catch { setMessage(`복사하지 못했어요. 실행 ID: ${run.run_id}`) }
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setMessage(''), 3000)
  }
  return <><span>{runEyebrow(screen, label, run.run_id, run.revision)} · {run.status === 'completed' ? '승인 완료' : run.status === 'exporting' ? '승인 후 내보내기' : STATUS_LABEL[run.status]}</span>{' '}
    <button type="button" className="link-btn" title={run.run_id} onClick={() => void copy()}>실행 ID 복사</button>
    <span role="status">{message}</span></>
}
