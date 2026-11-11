import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus } from '../../api/types.ts'
import type { ArtifactRef, DesignItem, Finding } from '../../api/viewItems.ts'
import StatusTag from '../../layout/StatusTag.tsx'
import Button from '../../ui/Button.tsx'
import DataTable from '../../ui/DataTable.tsx'
import Loading from '../../ui/Loading.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import DownloadAll from './DownloadAll.tsx'
import DownloadButton from './DownloadButton.tsx'
import Pipeline from './Pipeline.tsx'
import type { WorkspaceTab } from './pipeline.ts'
import ResultSummary from './ResultSummary.tsx'
import { FORMAT_LABEL, KIND_LABEL, downloadRows, isApproved, toArtifacts, type DownloadRow } from './rules.ts'

// UI-07 다운로드: 승인 완료 카드(전체 내려받기) · 결과 요약 · 산출물 파이프라인 · 형식별 내려받기.
// 생성 대기·파일 없음·승인 전 PDF는 칸마다 이유를 적는다. 초안 파일 이름에는 서버가 -draft를 붙인다.
type Props = {
  run: RunStatus
  label: string
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
        eyebrow={`다운로드 · ${label} · revision ${run.revision}`}
        title={
          <>
            <strong>설계 초안</strong>, {approved ? '완성.' : '내려받기'}
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
            <div className={`decision-card${approved ? ' decision-card--done' : ''}`}>
              <span style={{ fontSize: 14, opacity: 0.8 }}>{approved ? '승인 완료' : '초안 · 승인 전'}</span>
              <h3>{approved ? '설계 초안, 완성.' : '승인 전 초안이에요.'}</h3>
              <span style={{ opacity: 0.8 }}>
                {approved ? '형식별로 내려받을 수 있어요.' : '파일 이름 끝에 -draft가 붙고, PDF는 승인한 뒤에 만들어져요.'}
              </span>
              <DownloadAll runId={run.run_id} artifacts={artifacts} variant={approved ? 'accent' : 'primary'} />
            </div>
            <ResultSummary design={design} findings={findings} />
          </div>

          <section aria-label="산출물 흐름" className="stack-sm" style={{ gap: 12 }}>
            <h2 className="section-title" style={{ margin: 0 }}>
              산출물 파이프라인
            </h2>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>
              카드를 누르면 결과 작업공간에서 내용을 봐요.
            </p>
            <Pipeline design={design} artifacts={artifacts} onOpen={openWorkspace} />
          </section>

          <section aria-label="산출물" className="stack-sm" style={{ gap: 12 }}>
            <div className="row">
              <h2 className="section-title" style={{ margin: 0 }}>
                형식별 내려받기
              </h2>
              <StatusTag tone={approved ? 'success' : 'warning'}>{approved ? '승인본' : '초안 (승인 전)'}</StatusTag>
            </div>
            <DataTable<DownloadRow>
              label="산출물"
              rows={downloadRows(artifacts, approved)}
              rowKey={(r) => r.kind}
              minWidth={560}
              columns={[
                { key: 'kind', title: '산출물', width: 180, render: (r) => <strong>{KIND_LABEL[r.kind]}</strong> },
                {
                  key: 'files',
                  title: '내려받기',
                  render: (r) => (
                    <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                      {r.files.map(({ format, file }) =>
                        file.state === 'ready' ? (
                          <DownloadButton key={format} runId={run.run_id} artifact={file.artifact} />
                        ) : (
                          <span key={format} className="stack-sm" style={{ gap: 2 }}>
                            <Button variant="secondary" size="sm" disabled>
                              {FORMAT_LABEL[format]} · {file.state === 'needs-approval' ? '승인 후' : '없음'}
                            </Button>
                            <span className="subtle" style={{ fontSize: 12 }}>
                              {file.state === 'needs-approval' ? 'PDF는 승인한 뒤에 만들어져요' : '아직 만들어지지 않았어요'}
                            </span>
                          </span>
                        ),
                      )}
                    </div>
                  ),
                },
              ]}
            />
          </section>
        </>
      )}
    </div>
  )
}

export default DownloadPanel
