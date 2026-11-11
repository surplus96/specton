import { useEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useSearchParams } from 'react-router'
import Icon from './Icon.tsx'

// 모든 화면이 공유하는 틀 (F안 시안): 왼쪽 딥 포레스트 사이드바 + 오른쪽 흰 작업 영역.
// 사이드바: 새 작업 · 작업 검색 · AI Workspace. 좁은 화면은 덮개로 연다.
// 좁은 화면의 위쪽 바에는 메뉴 열기만 제공한다.
const COLLAPSE_KEY = 'specton.sidebar.collapsed'

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

export function Logo() {
  return (
    <span className="logo" aria-label="SPECTON">
      <b aria-hidden="true">SPEC</b>
      <i aria-hidden="true">+</i>
      <span aria-hidden="true">ON</span>
    </span>
  )
}

function AppLayout() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const sidebar = useRef<HTMLElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)
  const [drawer, setDrawer] = useState(false)
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 960px)').matches)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 960px)')
    const change = () => setNarrow(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  const location = useLocation()
  const [params] = useSearchParams()
  const currentRun = params.get('run')
  const isWorkspace = location.pathname === '/workspace'
  const workspaceUrl = currentRun ? `/workspace?run=${encodeURIComponent(currentRun)}` : '/workspace'

  // 화면을 옮기면 좁은 화면의 덮개를 닫는다
  useEffect(() => setDrawer(false), [location.pathname, location.search])

  useEffect(() => {
    const opened = narrow && drawer
    if (opened) {
      sidebar.current?.querySelector<HTMLButtonElement>('button[aria-label="메뉴 닫기"]')?.focus()
      const onKey = (event: KeyboardEvent) => {
        if (event.key === 'Escape') { event.preventDefault(); setDrawer(false) }
        if (event.key === 'Tab') {
          const controls = sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)')
          if (!controls?.length) return
          const first = controls[0], last = controls[controls.length - 1]
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
        }
      }
      document.addEventListener('keydown', onKey)
      wasOpen.current = true
      return () => document.removeEventListener('keydown', onKey)
    }
    if (wasOpen.current) { menuButton.current?.focus(); wasOpen.current = false }
  }, [drawer, narrow])

  function toggleCollapse() {
    setCollapsed((c) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
      } catch {
        // 기억하지 못해도 괜찮다
      }
      return !c
    })
  }

  const isNew = location.pathname === '/' && !currentRun
  const searching = location.pathname === '/history'

  return (
    <><a className="skip-link" href="#main">본문으로 건너뛰기</a>
    <div className={`shell${collapsed ? ' shell--collapsed' : ''}${drawer ? ' shell--drawer' : ''}${isWorkspace ? ' shell--workspace' : ''}`}>
      <aside ref={sidebar} id="app-menu" className="sidebar" aria-label="메뉴" inert={narrow && !drawer}>
        <div className="sidebar__top">
          <Link to="/" style={{ textDecoration: 'none' }} aria-label="SPECTON 처음 화면">
            <Logo />
          </Link>
          <button
            type="button"
            className="icon-btn sidebar__collapse"
            onClick={toggleCollapse}
            aria-label={collapsed ? '메뉴 펼치기' : '메뉴 접기'}
            aria-expanded={!collapsed}
          >
            <Icon name="sidebar" />
          </button>
          {drawer && (
            <button type="button" className="icon-btn" onClick={() => setDrawer(false)} aria-label="메뉴 닫기">
              <Icon name="x" />
            </button>
          )}
        </div>

        <nav className="nav" aria-label="주 메뉴">
          <Link to="/" aria-current={isNew ? 'page' : undefined} title="새 작업">
            <Icon name="plus" />
            <span className="nav__text">새 작업</span>
          </Link>
          <Link to="/history?search=1" aria-current={searching ? 'page' : undefined} title="작업 검색">
            <Icon name="search" />
            <span className="nav__text">작업 검색</span>
          </Link>
          <Link to={workspaceUrl} aria-current={isWorkspace ? 'page' : undefined} title="AI Workspace · 개발자용">
            <Icon name="code" />
            <span className="nav__text">AI Workspace <small>개발자용</small></span>
          </Link>
        </nav>

        <div className="sidebar__foot">요구사항 문서 → 설계 산출물</div>
      </aside>

      {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}

      <div className="main" inert={narrow && drawer}>
        {narrow && (
          <header className="topbar">
            <button ref={menuButton} type="button" aria-controls="app-menu" aria-expanded={drawer} className="icon-btn topbar__menu" onClick={() => setDrawer(true)} aria-label="메뉴 열기">
              <Icon name="menu" />
            </button>
          </header>
        )}
        <main className="content" id="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div></>
  )
}

export default AppLayout
