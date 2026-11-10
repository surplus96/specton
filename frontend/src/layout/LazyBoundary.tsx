import { Component, type ReactNode } from 'react'

// 따로 불러오는(lazy) 화면의 오류 경계 (#281).
// 배포 뒤 파일 이름(해시)이 바뀌었거나 네트워크가 끊겨 화면 파일을 받지 못하면 앱 전체가 빈 화면이 되지 않게
// 안내와 다시 불러오기 버튼을 보인다. 화면 안의 다른 오류도 같은 안내로 막는다.
type Props = { children: ReactNode }
type State = { failed: boolean }

class LazyBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div role="alert" style={{ padding: 32 }}>
        <p>화면을 불러오지 못했습니다. 새 버전이 배포되었거나 네트워크가 끊겼을 수 있습니다.</p>
        <button type="button" onClick={() => window.location.reload()}>
          다시 불러오기
        </button>{' '}
        <a href="/">처음으로</a>
      </div>
    )
  }
}

export default LazyBoundary
