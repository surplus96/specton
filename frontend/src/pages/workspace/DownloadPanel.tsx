import RunEyebrow from '../run/RunEyebrow.tsx'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { Pack, RunStatus } from '../../api/types.ts'
import type { ArtifactRef, DesignItem, Finding } from '../../api/viewItems.ts'
import Button from '../../ui/Button.tsx'
import Loading from '../../ui/Loading.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import DownloadCard from './DownloadCard.tsx'
import { PACK_LABELS } from '../upload/rules.ts'
import Pipeline from './Pipeline.tsx'
import type { WorkspaceTab } from './pipeline.ts'
import ResultSummary from './ResultSummary.tsx'
import { isApproved, toArtifacts } from './rules.ts'

// UI-07 내려받기: 설계 문서 카드(시안: 어두운 판 + 문서 4종 타일) · 결과 요약 · 문서가 만들어진 순서.
// 생성 대기·파일 없음·승인 전 PDF는 칸마다 이유를 적는다. 초안 파일 이름에는 서버가 -draft를 붙인다.
type Props = {
  run: RunStatus
  label: string
}

/** 카드 위 작은 글: 설계에 쓴 업무 분야 (예: 재고관리 요구사항) */
function subjectOf(design: readonly DesignItem[]): string {
  const pack = design.find((d) => d.type === 'entity')?.pack as Pack | undefined
  return pack && PACK_LABELS[pack] ? `${PACK_LABELS[pack].label} 요구사항` : '요구사항'
}

function DownloadPanel({ run, label }: Props) {
  const navigate = useNavigate()
  const [, setParams] = useSearchParams()
  const [artifacts, setArtifacts] = useState<ArtifactRef[] | null>(null)
  const [design, setDesign] = useState<DesignItem[]>([])
  // null: 검토 지적을 불러오지 못함 (요약의 지적 칸만 비우고 다운로드는 그대로)
  const [findings, setFindings] = useState<Finding[] | null>([])
  const [loadError, setLoadError] = useState<unknown>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let alive = true
    setArtifacts(null)
    setLoadError(null)
    // 다운로드에 필요한 것은 design(산출물 목록)뿐이다. review는 요약용이라 따로 받고 실패해도 파일은 받을 수 있다
    getView(run.run_id, 'design', run.revision)
      .then((designView) => {
        if (!alive) return
        setDesign(designView.items as DesignItem[])
        setArtifacts(toArtifacts(designView.artifacts))
      })
      .catch((err: unknown) => alive && setLoadError(err))
    getView(run.run_id, 'review', run.revision)
      .then((reviewView) => alive && setFindings(reviewView.items as Finding[]))
      .catch(() => alive && setFindings(null))
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, reloadKey])

  const approved = artifacts ? isApproved(artifacts) : false

  function openWorkspace(tab: WorkspaceTab) {
    setParams((p) => {
      const q = new URLSearchParams(p)
      q.set('view', 'workspace')
      q.set('tab', tab)
      return q
    })
  }

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={<RunEyebrow screen="내려받기" label={label} run={run} />}
        title={
          <>
            <strong>{approved ? '승인한 설계 문서' : '설계 문서 내려받기'}</strong>
          </>
        }
        actions={
          <Button variant="secondary" onClick={() => navigate('/')}>
            새 문서로 시작
          </Button>
        }
      />
      {loadError ? (
        <Notice kind="error" title={errorMessage(loadError)} action={<Button variant="secondary" size="sm" onClick={() => setReloadKey((k) => k + 1)}>다시 불러오기</Button>} />
      ) : !artifacts ? (
        <Loading text="산출물 목록을 불러오는 중이에요" />
      ) : (
        <>
          <div className="decide">
            <DownloadCard runId={run.run_id} artifacts={artifacts} approved={approved} subject={subjectOf(design)} />
            <ResultSummary design={design} findings={findings} />
          </div>

          <section aria-label="산출물 흐름" className="stack-sm" style={{ gap: 12 }}>
            <h2 className="section-title" style={{ margin: 0 }}>
              문서가 만들어진 순서
            </h2>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>
              카드를 누르면 결과 보기로 가요.
            </p>
            <Pipeline design={design} artifacts={artifacts} onOpen={openWorkspace} />
          </section>

        </>
      )}
    </div>
  )
}

export default DownloadPanel
