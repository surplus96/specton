import { useEffect, useState } from 'react'
import { Typography } from 'antd'
import type { RunState, SseEvent } from '../../api/types.ts'
import StatusTag from '../../layout/StatusTag.tsx'
import { colors, weights } from '../../theme.ts'
import { STATUS_LABEL } from '../workspace/rules.ts'
import type { Connection } from './followRun.ts'
import { CONNECTION_LABEL, activityItems, clockTime, formatElapsed } from './activity.ts'
import { isFinished } from './screens.ts'

// 서버 작업 패널: UI-01부터 결과까지 화면 옆(넓은 화면) 또는 아래(좁은 화면)에 붙어,
// 서버가 지금 하는 일을 이벤트(SSE)로 받아 실시간으로 보인다. 최신 기록이 맨 위.
// 실행 전(UI-01)에는 events 없이 안내 문장(idleText)만 보인다.
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

  // 진행 중에는 1초마다 경과 시간을 다시 그린다
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
    <section
      aria-label="서버 작업"
      style={{
        background: colors.canvas,
        border: `1.5px solid ${colors.border}`,
        borderRadius: 18,
        padding: 20,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: weights.display, letterSpacing: '-0.02em' }}>서버 작업</h2>
        {conn && <StatusTag tone={conn.tone}>{conn.label}</StatusTag>}
      </div>
      {status && (
        <div style={{ marginTop: 6, color: colors.inkMuted }}>
          지금 상태: <strong style={{ color: colors.ink, fontWeight: weights.strong }}>{STATUS_LABEL[status]}</strong>
        </div>
      )}
      {start !== null && end !== null && (
        <div style={{ marginTop: 2, color: colors.inkMuted }}>
          경과: <strong style={{ color: colors.ink, fontWeight: weights.display, fontSize: 20 }}>{formatElapsed(end - start)}</strong>
        </div>
      )}

      {items.length === 0 ? (
        <Typography.Paragraph type="secondary" style={{ margin: '16px 0 0' }}>
          {idleText ?? '서버 소식을 기다리고 있습니다…'}
        </Typography.Paragraph>
      ) : (
        <ol aria-live="polite" style={{ listStyle: 'none', margin: '16px 0 0', padding: 0, display: 'grid', gap: 10 }}>
          {items.map((item, i) => {
            const newest = i === 0
            return (
              <li
                key={item.id}
                style={{
                  borderLeft: `4px solid ${newest ? colors.primary : colors.line}`,
                  background: newest ? colors.primarySoft : 'transparent',
                  borderRadius: 6,
                  padding: '8px 10px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <StatusTag tone={item.tone}>{item.label}</StatusTag>
                  {item.stage && <span style={{ color: colors.inkMuted, fontWeight: weights.strong }}>{item.stage}</span>}
                  {item.count > 1 && <span style={{ color: colors.inkMuted }}>×{item.count}</span>}
                  <span style={{ marginLeft: 'auto', color: newest ? colors.primary : colors.inkMuted, fontWeight: weights.strong }}>
                    {[newest ? '최신' : null, item.at !== null ? clockTime(item.at) : null].filter(Boolean).join(' · ')}
                  </span>
                </div>
                <div style={{ marginTop: 4, color: colors.ink, lineHeight: 1.5 }}>{item.message}</div>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

export default ActivityPanel
