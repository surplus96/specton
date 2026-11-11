import { Link } from 'react-router'
import Button from '../ui/Button.tsx'
import Notice from '../ui/Notice.tsx'
import { isActive } from './runMeta.ts'
import SampleDemo from './start/SampleDemo.tsx'
import UploadPanel from './start/UploadPanel.tsx'
import { ActiveRunCard, RunCard } from './start/RunCards.tsx'
import { useRuns } from './useRuns.ts'

// 새 작업 (/) — F안 시안
// - 첫 방문(실행 없음): 큰 제목 + 업로드 + 진행 방식 + 작동 과정 샘플(가상 데이터)
// - 작업 있음: 지금 진행 중(끝나지 않은 가장 최근 실행, 실시간) → 이어서 할 작업 → 새 작업
// 목록을 불러오지 못해도 업로드는 그대로 쓸 수 있고, 실패는 「없음」과 따로 알린다.
function StartPage() {
  const { runs, failed, reload } = useRuns(20)
  const loading = runs === null && !failed
  const list = runs ?? []
  const active = list.find((r) => isActive(r.status))
  const others = list.filter((r) => r !== active).slice(0, 4)
  const firstVisit = !loading && list.length === 0

  const loadFailed = failed && (
    <Notice kind="warning" title="지난 작업을 불러오지 못했어요." action={<Button variant="secondary" size="sm" onClick={reload}>다시 시도</Button>}>
      새 문서는 그대로 올릴 수 있어요.
    </Notice>
  )

  if (loading) {
    return (
      <div className="stack-lg" aria-busy="true">
        <div className="skeleton" style={{ height: 56, maxWidth: 520 }} />
        <div className="skeleton" style={{ height: 300 }} />
      </div>
    )
  }

  if (firstVisit) {
    return (
      <div className="stack-lg screen">
        {loadFailed}
        <header>
          <p className="eyebrow">첫 작업 안내</p>
          <h1 className="hero">
            어떤 <strong>요구사항</strong>을 설계할까요?
          </h1>
        </header>
        <UploadPanel />
        <SampleDemo />
      </div>
    )
  }

  return (
    <div className="stack-lg screen">
      {loadFailed}
      {active && (
        <section aria-labelledby="now-title">
          <h2 className="section-title" id="now-title">
            지금 진행 중
          </h2>
          <ActiveRunCard runId={active.run_id} />
        </section>
      )}
      {others.length > 0 && (
        <section aria-labelledby="next-title">
          <div className="row row--between" style={{ marginBottom: 16 }}>
            <h2 className="section-title" id="next-title" style={{ margin: 0 }}>
              이어서 할 작업
            </h2>
            <Link to="/history" className="topbar__link" style={{ padding: '4px 8px' }}>
              전체 보기 →
            </Link>
          </div>
          <div className="work-grid">
            {others.map((r) => (
              <RunCard key={r.run_id} run={r} />
            ))}
          </div>
        </section>
      )}
      <section aria-labelledby="new-title">
        <h2 className="section-title" id="new-title">
          새 작업
        </h2>
        <UploadPanel />
      </section>
    </div>
  )
}

export default StartPage
