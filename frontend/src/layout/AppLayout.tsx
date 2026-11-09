import { Layout } from 'antd'
import { Link, Outlet } from 'react-router'
import { colors, weights } from '../theme.ts'

// 모든 화면이 공유하는 틀: 맨 위 남색 바(아래 파랑 선) + 가운데 본문.
// <Outlet /> 자리에 주소에 맞는 화면(HomePage, UploadPage, RunPage …)이 들어간다.
function AppLayout() {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          borderBottom: `4px solid ${colors.primary}`,
        }}
      >
        <Link to="/" style={{ color: colors.onDark, fontWeight: weights.display, fontSize: 22, letterSpacing: '-0.02em' }}>
          Spec<span style={{ color: colors.onDarkMuted }}>ton</span>
        </Link>
        <span style={{ color: colors.onDarkMuted, fontSize: 15 }}>요구사항 문서 → 설계 산출물</span>
      </Layout.Header>
      <Layout.Content style={{ padding: '32px clamp(16px, 2.5vw, 36px) 64px' }}>
        <div style={{ maxWidth: 1480, margin: '0 auto' }}>
          <Outlet />
        </div>
      </Layout.Content>
    </Layout>
  )
}

export default AppLayout
