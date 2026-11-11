import { useEffect, useState } from 'react'
import type { RunState } from '../../api/types.ts'
import { formatElapsed } from './activity.ts'
import { isFinished } from './screens.ts'

// 설계 중 화면의 진행 시간. 이 화면이 처음 받은 이벤트부터 잰다(서버 이벤트에 시각이 없음).
// 진행 중이면 1초마다 다시 그리고, 끝났으면 마지막 이벤트까지의 시간에서 멈춘다. 새로고침하면 그때부터 잰다.
type Props = {
  receivedAt: Record<number, number>
  status: RunState
}

function Elapsed({ receivedAt, status }: Props) {
  const running = !isFinished(status)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])

  const times = Object.values(receivedAt)
  if (times.length === 0) return null
  const start = Math.min(...times)
  const end = running ? Math.max(now, ...times) : Math.max(...times)
  return (
    <span className="muted" style={{ fontSize: 15, whiteSpace: 'nowrap' }} aria-label={`진행 시간 ${formatElapsed(end - start)}`}>
      진행 시간 <strong style={{ color: 'var(--ink)', fontSize: 18 }}>{formatElapsed(end - start)}</strong>
    </span>
  )
}

export default Elapsed
