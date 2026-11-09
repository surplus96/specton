import type { ReactNode } from 'react'

// 본문 + 서버 작업 패널 배치 (index.css .with-activity).
// 넓은 화면(1100px 이상)은 오른쪽 세로 칸에 붙고 스크롤해도 따라온다. 좁은 화면은 본문 아래로 내려간다.
type Props = {
  side: ReactNode
  children: ReactNode
}

function WithActivity({ side, children }: Props) {
  return (
    <div className="with-activity">
      <div className="with-activity__main">{children}</div>
      <aside className="with-activity__side">{side}</aside>
    </div>
  )
}

export default WithActivity
