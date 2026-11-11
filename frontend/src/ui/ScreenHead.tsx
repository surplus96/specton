import type { ReactNode } from 'react'

// 화면 머리: 작은 위치 글(눈썹) + 큰 제목(강조어만 굵게) + 설명 + 오른쪽 행동
type Props = {
  eyebrow: ReactNode
  title: ReactNode
  lead?: ReactNode
  actions?: ReactNode
}

function ScreenHead({ eyebrow, title, lead, actions }: Props) {
  return (
    <header className="screen-head">
      <div style={{ minWidth: 0 }}>
        <p className="eyebrow">{eyebrow}</p>
        <h1 className="title">{title}</h1>
        {lead && <p className="lead">{lead}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  )
}

export default ScreenHead
