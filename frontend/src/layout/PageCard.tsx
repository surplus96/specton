import type { ReactNode } from 'react'
import { Flex, Typography } from 'antd'
import { colors, type } from '../theme.ts'

// 화면 본문을 담는 흰 카드. 그림자 없이 얇은 테두리만 둔다.
// `actions`를 주면 제목 오른쪽(좁으면 아래)에 버튼 등을 둔다.
type Props = {
  title: string
  subtitle?: string
  actions?: ReactNode
  children?: ReactNode
}

function PageCard({ title, subtitle, actions, children }: Props) {
  return (
    <section
      style={{
        background: colors.canvas,
        border: `1.5px solid ${colors.border}`,
        borderRadius: 18,
        padding: 32,
      }}
    >
      <Flex justify="space-between" align="flex-start" gap={16} wrap>
        <Typography.Title level={1} style={{ marginTop: 0, ...type.title }}>
          {title}
        </Typography.Title>
        {actions}
      </Flex>
      {subtitle && <Typography.Paragraph type="secondary">{subtitle}</Typography.Paragraph>}
      {children}
    </section>
  )
}

export default PageCard
