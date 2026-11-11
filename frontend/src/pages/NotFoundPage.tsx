import { useNavigate } from 'react-router'
import Button from '../ui/Button.tsx'

// 없는 주소로 들어왔을 때
function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <section className="screen" style={{ padding: '64px 0' }}>
      <p className="eyebrow mono">404</p>
      <h1 className="title">
        없는 <strong>화면</strong>이에요
      </h1>
      <p className="muted" style={{ margin: '12px 0 28px' }}>
        주소를 확인하거나 새 작업 화면으로 돌아가 주세요.
      </p>
      <Button onClick={() => navigate('/')}>새 작업으로</Button>
    </section>
  )
}

export default NotFoundPage
