import type { ReactNode } from 'react'
import { tones, type Tone } from '../theme.ts'

// 상태 칩(심각도·판정·초안/승인본·실행 상태). 색만으로 뜻을 전하지 않도록 children에 반드시 글자를 넣는다.
type Props = {
  tone: Tone
  children: ReactNode
  /** 앞에 라임 점 (지금 할 일 한 개를 가리킬 때) */
  dot?: boolean
}

function StatusTag({ tone, children, dot }: Props) {
  const { bg, fg } = tones[tone]
  return (
    <span className="tag" style={{ background: bg, color: fg }}>
      {dot && <span className="tag__dot" aria-hidden="true" />}
      {children}
    </span>
  )
}

export default StatusTag
