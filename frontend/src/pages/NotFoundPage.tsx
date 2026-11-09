import { Button, Result } from 'antd'
import { useNavigate } from 'react-router'

// 없는 주소로 들어왔을 때
function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <Result
      status="404"
      title="없는 화면입니다"
      subTitle="주소를 확인하거나 처음 화면으로 돌아가 주세요."
      extra={
        <Button type="primary" onClick={() => navigate('/')}>
          처음 화면으로
        </Button>
      }
    />
  )
}

export default NotFoundPage
