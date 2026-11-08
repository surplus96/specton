import type { ReactNode } from 'react'
import { tones, type Tone } from '../theme.ts'

// 상태 표시(심각도·판정·초안/승인본·실행 상태). 진한 바탕 + 흰 글자, 주의만 연노랑 + 검정 글자.
// antd 기본 Tag의 연한 바탕은 프로젝터에서 흐려져서 쓰지 않는다 (theme.ts 「상태 표시 색」).
// 색만으로 뜻을 전하지 않도록 children에 반드시 글자(차단·완료 등)를 넣는다.
type Props = {
  tone: Tone
  children: ReactNode
}

function StatusTag({ tone, children }: Props) {
  const { bg, fg } = tones[tone]
  return (
    <span
      style={{
        display: 'inline-block',
        background: bg,
        color: fg,
        fontSize: 15,
        fontWeight: 700,
        lineHeight: 1.4,
        padding: '2px 10px',
        borderRadius: 6,
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

export default StatusTag
