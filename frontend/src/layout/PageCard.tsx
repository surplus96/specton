import type { ReactNode } from 'react'
import { Typography } from 'antd'
import { colors, type } from '../theme.ts'

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
      <Typography.Title level={1} style={{ marginTop: 0, ...type.title }}>
        {title}
      </Typography.Title>
      {subtitle && <Typography.Paragraph type="secondary">{subtitle}</Typography.Paragraph>}
      {children}
    </section>
  )
}

export default PageCard
