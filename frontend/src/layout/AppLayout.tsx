import { Layout } from 'antd'
import { Link, Outlet, useLocation } from 'react-router'
import { colors, weights } from '../theme.ts'

// 모든 화면이 공유하는 틀: 맨 위 바 + 가운데 본문.
// <Outlet /> 자리에 주소에 맞는 화면(HomePage, UploadPage, RunPage …)이 들어간다.
// 첫 화면(/)은 흰 바(남색 글자 + 파랑 「ton」), 그 밖의 화면은 남색 바(아래 파랑 선).
// 실행 화면도 주소가 /?run=<id>라 경로만으로는 같으므로, run 파라미터가 없을 때만 첫 화면으로 본다.
function AppLayout() {
  const { pathname, search } = useLocation()
  const home = pathname === '/' && !new URLSearchParams(search).has('run')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          ...(home
            ? { background: colors.canvas, borderBottom: `1px solid ${colors.line}` }
            : { borderBottom: `4px solid ${colors.primary}` }),
        }}
      >
        <Link
          to="/"
          style={{ color: home ? colors.navy : colors.onDark, fontWeight: weights.display, fontSize: 22, letterSpacing: '-0.02em' }}
        >
          Spec<span style={{ color: home ? colors.primary : colors.onDarkMuted }}>ton</span>
        </Link>
        <span style={{ color: home ? colors.inkMuted : colors.onDarkMuted, fontSize: 15 }}>요구사항 문서 → 설계 산출물</span>
      </Layout.Header>
      <Layout.Content style={{ padding: home ? '0 clamp(16px, 2.5vw, 36px)' : '32px clamp(16px, 2.5vw, 36px) 64px' }}>
        <div style={{ maxWidth: 1480, margin: '0 auto' }}>
          <Outlet />
        </div>
      </Layout.Content>
    </Layout>
  )
}

export default AppLayout
