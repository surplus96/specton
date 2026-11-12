import type { CSSProperties } from 'react'
import Button from '../ui/Button.tsx'
import Notice from '../ui/Notice.tsx'
import { isActive } from './runMeta.ts'
import HowItWorks from './start/HowItWorks.tsx'
import UploadPanel from './start/UploadPanel.tsx'
import { ActiveRunCard } from './start/RunCards.tsx'
import { useRuns } from './useRuns.ts'

// 새 작업 (/) — F안 시안
// - 첫 방문(실행 없음): 큰 제목 + 업로드 + 작동 과정 세 단계 안내
// - 작업 있음: 새 작업 → 지금 진행 중(끝나지 않은 가장 최근 실행, 실시간)
// 목록을 불러오지 못해도 업로드는 그대로 쓸 수 있고, 실패는 「없음」과 따로 알린다.
function StartPage() {
  const { runs, failed, reload } = useRuns(20)
  const loading = runs === null && !failed
  const list = runs ?? []
  const active = list.find((r) => isActive(r.status))
  const firstVisit = !loading && list.length === 0

  const loadFailed = failed && (
    <Notice kind="warning" title="지난 작업을 불러오지 못했어요." action={<Button variant="secondary" size="sm" onClick={reload}>다시 시도</Button>}>
      새 문서는 그대로 올릴 수 있어요.
    </Notice>
  )

  return (
    <div className="stack-lg screen">
      {loadFailed}
      {loading && <p role="status">지난 작업을 불러오는 중이에요.</p>}
      <h1 className="hero">
        어떤{' '}
        <strong className="drop-word" aria-label="요구사항">
          {[...'요구사항'].map((ch, i) => (
            <span key={i} aria-hidden="true" style={{ '--i': i } as CSSProperties}>
              {ch}
            </span>
          ))}
        </strong>
        을 설계할까요?
      </h1>
      <section aria-labelledby="new-title">
        <h2 className="section-title" id="new-title">
          새 작업
        </h2>
        <UploadPanel />
      </section>
      {active && (
        <section aria-labelledby="now-title">
          <h2 className="section-title" id="now-title">
            지금 진행 중
          </h2>
          <ActiveRunCard runId={active.run_id} />
        </section>
      )}
      {firstVisit && <HowItWorks />}
    </div>
  )
}

export default StartPage
