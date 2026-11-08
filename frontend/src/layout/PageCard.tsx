import type { ReactNode } from 'react'
import { Typography } from 'antd'
import { colors } from '../theme.ts'

// 화면 본문을 담는 흰 카드. 그림자 없이 얇은 테두리만 둔다.
type Props = {
  title: string
  subtitle?: string
  children?: ReactNode
}

function PageCard({ title, subtitle, children }: Props) {
  return (
    <section
      style={{
        background: colors.canvas,
        border: `1.5px solid ${colors.border}`,
        borderRadius: 18,
        padding: 32,
      }}
    >
      <Typography.Title level={2} style={{ marginTop: 0, fontWeight: 600, letterSpacing: '-0.02em' }}>
        {title}
      </Typography.Title>
      {subtitle && <Typography.Paragraph type="secondary">{subtitle}</Typography.Paragraph>}
      {children}
    </section>
  )
}

export default PageCard
