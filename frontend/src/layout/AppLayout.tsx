import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router'
import { runFileName, titleFromFile } from '../api/runNames.ts'
import { runBadge } from '../pages/runMeta.ts'
import { useRuns } from '../pages/useRuns.ts'
import Icon from './Icon.tsx'

// 모든 화면이 공유하는 틀 (F안 시안): 왼쪽 딥 포레스트 사이드바 + 오른쪽 흰 작업 영역.
// 사이드바: 새 작업 · 작업 검색 · 지난 작업 + 최근 작업 몇 개. 넓은 화면은 접을 수 있고, 좁은 화면은 덮개로 연다.
// 위쪽 바: Docs(서비스 안내) · Try SpecOn(새 작업)
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
  const [drawer, setDrawer] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const currentRun = location.pathname === '/' ? params.get('run') : null
  const { runs } = useRuns(20)
  const recent = (runs ?? []).slice(0, 6)

  // 화면을 옮기면 좁은 화면의 덮개를 닫는다
  useEffect(() => setDrawer(false), [location.pathname, location.search])

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
  const isRuns = location.pathname === '/history'
  const searching = isRuns && params.get('search') === '1'

  return (
    <div className={`shell${collapsed ? ' shell--collapsed' : ''}${drawer ? ' shell--drawer' : ''}`}>
      <aside className="sidebar" aria-label="메뉴">
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
          <Link to="/history" aria-current={isRuns && !searching ? 'page' : undefined} title="지난 작업">
            <Icon name="history" />
            <span className="nav__text">지난 작업</span>
          </Link>
        </nav>

        {recent.length > 0 && (
          <section className="sidebar__section" aria-label="최근 작업">
            <div className="sidebar__label">최근 작업</div>
            <div className="recent">
              {recent.map((r) => {
                const file = runFileName(r.run_id)
                return (
                  <Link
                    key={r.run_id}
                    to={`/?run=${encodeURIComponent(r.run_id)}`}
                    aria-current={currentRun === r.run_id ? 'page' : undefined}
                  >
                    <span className="recent__name">{file ? titleFromFile(file) : `실행 ${r.run_id.slice(0, 8)}`}</span>
                    <small>{runBadge(r.status).text}</small>
                  </Link>
                )
              })}
            </div>
          </section>
        )}

        <div className="sidebar__foot">요구사항 문서 → 설계 산출물</div>
      </aside>

      {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}

      <div className="main">
        <header className="topbar">
          <button type="button" className="icon-btn topbar__menu" onClick={() => setDrawer(true)} aria-label="메뉴 열기">
            <Icon name="menu" />
          </button>
          <Link className="topbar__link" to="/about">
            <Icon name="book" size={18} />
            Docs
          </Link>
          <button type="button" className="btn" onClick={() => navigate('/')} style={{ minHeight: 46 }}>
            Try SpecOn
            <Icon name="arrowRight" size={18} />
          </button>
        </header>
        <main className="content" id="main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default AppLayout
