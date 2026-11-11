import type { ReactNode } from 'react'
import Icon, { type IconName } from '../layout/Icon.tsx'

// 안내·경고·오류 상자. 아이콘 + 색 + 글자 (디자인 시스템 「상태 표시」)
type Kind = 'info' | 'success' | 'warning' | 'error' | 'plain'

const ICON: Record<Kind, IconName> = {
  info: 'info',
  success: 'checkCircle',
  warning: 'alert',
  error: 'alert',
  plain: 'info',
}

type Props = {
  kind?: Kind
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
}

function Notice({ kind = 'info', title, children, action }: Props) {
  return (
    <div className={`notice notice--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <Icon name={ICON[kind]} size={18} />
      <div className="notice__body">
        <div className="notice__title">{title}</div>
        {children && <div className="notice__desc">{children}</div>}
      </div>
      {action && <div className="notice__action">{action}</div>}
    </div>
  )
}

export default Notice
