import { useEffect, useState } from 'react'
import type { RunState, SseEvent } from '../../api/types.ts'
import StatusTag from '../../layout/StatusTag.tsx'
import { STATUS_LABEL } from '../workspace/rules.ts'
import type { Connection } from './followRun.ts'
import { CONNECTION_LABEL, activityItems, clockTime, formatElapsed } from './activity.ts'
import { isFinished } from './screens.ts'

// 서버 작업 패널: 서버가 지금 하는 일을 이벤트(SSE)로 받아 실시간으로 보인다. 최신 기록이 맨 위.
// 시각은 이 화면이 이벤트를 받은 시각이다(서버 이벤트에 시각이 없음). 새로고침하면 그때부터 잰다.
type Props = {
  events?: readonly SseEvent[]
  receivedAt?: Record<number, number>
  connection?: Connection
  status?: RunState
  idleText?: string
}

function ActivityPanel({ events = [], receivedAt = {}, connection, status, idleText }: Props) {
  const items = activityItems(events, receivedAt)
  const conn = connection ? CONNECTION_LABEL[connection] : null
  const running = status !== undefined && !isFinished(status)

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])

  const times = Object.values(receivedAt)
  const start = times.length > 0 ? Math.min(...times) : null
  const end = running ? Math.max(now, ...times) : times.length > 0 ? Math.max(...times) : null

  return (
    <section className="activity" aria-label="서버 작업">
      <div className="row row--between">
        <h2 className="h3">서버 작업</h2>
        {conn && <StatusTag tone={conn.tone}>{conn.label}</StatusTag>}
      </div>
      {status && (
        <div className="muted" style={{ marginTop: 8, fontSize: 14 }}>
          지금 상태 <strong style={{ color: 'var(--ink)' }}>{STATUS_LABEL[status]}</strong>
        </div>
      )}
      {start !== null && end !== null && (
        <div className="muted" style={{ fontSize: 14 }}>
          경과 <strong style={{ color: 'var(--ink)', fontSize: 18 }}>{formatElapsed(end - start)}</strong>
        </div>
      )}
      {items.length === 0 ? (
        <p className="muted" style={{ margin: '14px 0 0', fontSize: 14 }}>
          {idleText ?? '서버 소식을 기다리고 있어요…'}
        </p>
      ) : (
        <ol aria-live="polite">
          {items.map((item, i) => (
            <li key={item.id} className={i === 0 ? 'is-new' : undefined}>
              <div className="activity__meta">
                <StatusTag tone={item.tone}>{item.label}</StatusTag>
                {item.stage && <span>{item.stage}</span>}
                {item.count > 1 && <span>×{item.count}</span>}
                <time>{[i === 0 ? '최신' : null, item.at !== null ? clockTime(item.at) : null].filter(Boolean).join(' · ')}</time>
              </div>
              <div style={{ marginTop: 4 }}>{item.message}</div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export default ActivityPanel
