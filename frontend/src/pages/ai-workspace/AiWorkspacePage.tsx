import '@xyflow/react/dist/style.css'
import './aiWorkspace.css'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { AnalysedRequirement, DesignItem, ExtractionBlock, Finding } from '../../api/viewItems.ts'
import { dark } from '../../theme.ts'
import { nameIndex } from '../review/rules.ts'
import { sqlReview } from '../review/sqlValidation.ts'
import { CONNECTION_LABEL } from '../run/activity.ts'
import { useRunStatus } from '../run/useRunStatus.ts'
import { STATUS_LABEL, isApproved, revisionOptions, toArtifacts } from '../workspace/rules.ts'
import DetailPanel, { type Selection } from './DetailPanel.tsx'
import ErdCanvas from './ErdCanvas.tsx'
import PipelineGraph from './PipelineGraph.tsx'
import TraceCanvas from './TraceCanvas.tsx'
import { erdModel, findingEntities } from './erd.ts'
import { pipelineNodes, pipelineProgress } from './pipeline.ts'
import { buildTrace, traceSummary } from './trace.ts'

// AI Workspace: 개발용 결과 확인 페이지 (/workspace?run=<id>, #281).
// 실행 상태(왼쪽) · ERD/문서 추적 캔버스(가운데) · 상세·검증(오른쪽)을 한 화면에.
// API만 부르고(상태 조회·SSE·view) 계약은 바꾸지 않는다. 기존 UI-02~07 흐름은 그대로 두고 링크로만 잇는다.
// 이 페이지만 어두운 캔버스다(색은 theme.ts의 dark 토큰). 큰 라이브러리(React Flow·elkjs)는 이 페이지에서만 불러온다.

type Loaded = {
  revision: number
  design: DesignItem[]
  findings: Finding[]
  requirements: AnalysedRequirement[]
  blocks: ExtractionBlock[]
  rawArtifacts: unknown[]
}

type Tab = 'erd' | 'trace'

const cssVars = {
  '--aiws-page': dark.page,
  '--aiws-panel': dark.panel,
  '--aiws-canvas': dark.canvas,
  '--aiws-card': dark.card,
  '--aiws-card-hover': dark.cardHover,
  '--aiws-border': dark.border,
  '--aiws-line': dark.line,
  '--aiws-ink': dark.ink,
  '--aiws-ink-muted': dark.inkMuted,
  '--aiws-accent': dark.accent,
  '--aiws-focus': dark.focus,
} as CSSProperties

function AiWorkspacePage() {
  const [params] = useSearchParams()
  const runId = params.get('run')
  if (!runId) {
    return (
      <div className="aiws" style={{ ...cssVars, padding: 32 }}>
        <p>
          실행 ID가 없습니다. 실행 화면에서 「작업공간 열기」로 들어오세요. <Link to="/">처음으로</Link>
        </p>
      </div>
    )
  }
  return <Workspace key={runId} runId={runId} />
}

function Workspace({ runId }: { runId: string }) {
  const { run, events, connection, loadError } = useRunStatus(runId)
  const [picked, setPicked] = useState<number | null>(null)
  const [data, setData] = useState<Loaded | null>(null)
  const [viewError, setViewError] = useState<unknown>(null)
  const [tab, setTab] = useState<Tab>('erd')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [focus, setFocus] = useState<{ id: string; at: number } | null>(null)
  const [panelOpen, setPanelOpen] = useState(true)

  const revision = picked ?? run?.revision ?? 0
  const artifactEvents = events.filter((e) => e.event === 'artifact').length
  const ready = run !== null
  const status = run?.status
  const stage = run?.stage

  // 상태·단계·산출물이 바뀌면 view를 다시 읽는다 (상태 조회가 기준, 이벤트는 신호)
  useEffect(() => {
    if (!ready) return
    let alive = true
    setViewError(null)
    Promise.all([
      getView(runId, 'design', revision),
      getView(runId, 'review', revision),
      getView(runId, 'requirements', revision),
      getView(runId, 'extraction'),
    ])
      .then(([design, review, requirements, extraction]) => {
        if (!alive) return
        setData({
          revision,
          design: design.items as DesignItem[],
          findings: review.items as Finding[],
          requirements: requirements.items as AnalysedRequirement[],
          blocks: extraction.items as ExtractionBlock[],
          rawArtifacts: design.artifacts ?? [],
        })
      })
      .catch((err: unknown) => alive && setViewError(err))
    return () => {
      alive = false
    }
  }, [runId, revision, ready, status, stage, artifactEvents])

  // 고른 revision의 데이터만 쓴다. revision을 바꾼 직후 받기 전에는 이전 revision 데이터를 섞어 보이지 않고 「불러오는 중」
  const shown = data && data.revision === revision ? data : null
  const artifacts = useMemo(() => toArtifacts(shown?.rawArtifacts), [shown])
  const names = useMemo(() => nameIndex(shown?.design ?? []), [shown])
  const erd = useMemo(() => erdModel(shown?.design ?? [], shown?.findings ?? []), [shown])
  const trace = useMemo(
    () => buildTrace({ blocks: shown?.blocks ?? [], requirements: shown?.requirements ?? [], design: shown?.design ?? [], findings: shown?.findings ?? [] }),
    [shown],
  )
  const pipeline = useMemo(() => {
    if (!run) return []
    // 실행 단계 그래프는 지금 revision 기준이다. 지난 revision을 볼 때는 산출물·지적을 섞지 않는다
    const current = shown && shown.revision === run.revision
    return pipelineNodes({ run, events, artifacts: current ? artifacts : [], findings: current ? shown.findings : [] })
  }, [run, events, artifacts, shown])

  if (loadError) {
    return (
      <div className="aiws" style={{ ...cssVars, padding: 32 }}>
        <p role="alert">{errorMessage(loadError)}</p>
        <Link to="/">처음으로</Link>
      </div>
    )
  }

  const progress = pipelineProgress(pipeline)
  const approved = isApproved(artifacts)
  const summary = traceSummary(trace)
  const sql = sqlReview(shown?.rawArtifacts, revision)

  function onFinding(f: Finding) {
    setSelection({ kind: 'finding', id: f.id })
    // 카드 배지·상세 목록과 같은 규칙(erd.ts findingEntities)으로 이동할 엔티티를 고른다
    const entityId = findingEntities(shown?.design ?? [])(f)[0]
    if (entityId) {
      setTab('erd')
      setFocus({ id: entityId, at: Date.now() })
    } else {
      setFocus(null) // 이전 이동 대상을 남기지 않는다 (ERD로 돌아갔을 때 상관없는 엔티티 강조 방지)
      setTab('trace') // 요구사항·기능 지적은 추적에서 그 지적까지의 길을 밝힌다
    }
  }

  const TABS = [
    ['erd', `ERD (${erd.cards.length})`],
    ['trace', '문서 추적'],
  ] as const

  // 탭은 좌우 방향키·Home·End로도 옮긴다 (WAI-ARIA 탭 패턴)
  function onTabKey(e: React.KeyboardEvent) {
    const order = TABS.map(([key]) => key)
    const at = order.indexOf(tab)
    const next =
      e.key === 'ArrowRight' ? order[(at + 1) % order.length] : e.key === 'ArrowLeft' ? order[(at + order.length - 1) % order.length] : e.key === 'Home' ? order[0] : e.key === 'End' ? order[order.length - 1] : null
    if (!next) return
    e.preventDefault()
    setTab(next)
    document.getElementById(`aiws-tab-${next}`)?.focus()
  }

  const traceSelected = selection?.kind === 'trace' ? selection.key : selection?.kind === 'finding' ? `finding:${selection.id}` : null
  const erdSelected = selection?.kind === 'entity' ? selection.id : selection?.kind === 'finding' ? (focus?.id ?? null) : null

  return (
    <div className="aiws" style={cssVars}>
      <header className="aiws-header">
        <Link to={`/?run=${encodeURIComponent(runId)}`} style={{ color: dark.accent }}>
          ← 실행 화면
        </Link>
        <strong style={{ fontSize: 18 }}>AI Workspace</strong>
        <span className="aiws-chip" title={runId}>
          실행 {runId.slice(0, 8)}
        </span>
        {run && <span className="aiws-chip">{STATUS_LABEL[run.status]}</span>}
        <span className="aiws-chip">{CONNECTION_LABEL[connection].label}</span>
        <span style={{ color: dark.inkMuted, fontSize: 13 }}>
          단계 {progress.done}/{progress.total}
        </span>
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: 13, color: dark.inkMuted, display: 'flex', alignItems: 'center', gap: 6 }}>
          revision
          <select
            value={revision}
            onChange={(e) => setPicked(Number(e.target.value))}
            style={{ background: dark.card, color: dark.ink, border: `1px solid ${dark.border}`, borderRadius: 6, padding: '2px 6px' }}
          >
            {revisionOptions(run?.revision ?? 0).map((r) => (
              <option key={r} value={r}>
                {r === run?.revision ? `${r} (최신)` : r}
              </option>
            ))}
          </select>
        </label>
        {artifacts.length > 0 && (
          <span className="aiws-chip" style={{ borderColor: approved ? '#4ade80' : '#fbbf24', color: approved ? '#4ade80' : '#fbbf24' }}>
            {approved ? '승인본' : '초안'}
          </span>
        )}
        <button type="button" className="aiws-chip" style={{ cursor: 'pointer', background: 'transparent' }} onClick={() => setPanelOpen((o) => !o)} aria-expanded={panelOpen}>
          {panelOpen ? '패널 닫기 ›' : '‹ 패널 열기'}
        </button>
      </header>

      <div className={`aiws-body${panelOpen ? '' : ' panel-closed'}`}>
        <aside className="aiws-side">
          <div className="aiws-section-title">실행 단계</div>
          <div style={{ padding: '0 12px' }}>
            <PipelineGraph
              nodes={pipeline}
              selected={selection?.kind === 'pipeline' ? selection.id : null}
              onSelect={(id) => setSelection(id ? { kind: 'pipeline', id } : null)}
            />
          </div>
        </aside>

        <main className="aiws-center">
          <div role="tablist" aria-label="캔버스" onKeyDown={onTabKey} style={{ display: 'flex', gap: 4, padding: '8px 12px', borderBottom: `1px solid ${dark.border}`, alignItems: 'center' }}>
            {TABS.map(([key, label]) => (
              <button
                key={key}
                id={`aiws-tab-${key}`}
                type="button"
                role="tab"
                aria-selected={tab === key}
                aria-controls="aiws-tabpanel"
                tabIndex={tab === key ? 0 : -1}
                className={`aiws-list-item${tab === key ? ' active' : ''}`}
                style={{ width: 'auto' }}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
            <span style={{ flex: 1 }} />
            {tab === 'trace' && (
              <span style={{ fontSize: 13, color: dark.inkMuted }}>
                요구사항 {summary.requirements} · 미연결 {summary.unlinkedRequirements} · 제외 {summary.excludedBlocks} · 확인(원문 없음) {summary.noSourceBlocks}
              </span>
            )}
          </div>
          <div id="aiws-tabpanel" role="tabpanel" aria-labelledby={`aiws-tab-${tab}`} style={{ minHeight: 0 }}>
            {viewError ? (
              <p role="alert" style={{ padding: 20 }}>
                {errorMessage(viewError)}
              </p>
            ) : !shown ? (
              <p style={{ padding: 20, color: dark.inkMuted }}>불러오는 중…</p>
            ) : tab === 'erd' ? (
              erd.cards.length === 0 ? (
                <p style={{ padding: 20, color: dark.inkMuted }}>이 revision에는 아직 엔티티가 없습니다.</p>
              ) : (
                <ErdCanvas
                  cards={erd.cards}
                  lines={erd.lines}
                  selected={erdSelected}
                  focus={focus}
                  onSelect={(id) => setSelection(id ? { kind: 'entity', id } : null)}
                />
              )
            ) : (
              <TraceCanvas graph={trace} selected={traceSelected} onSelect={(key) => setSelection(key ? { kind: 'trace', key } : null)} />
            )}
          </div>
        </main>

        {/* 닫힌 패널은 inert: 보이지 않는 버튼에 Tab 포커스가 들어가지 않는다 */}
        <aside className="aiws-right" inert={!panelOpen}>
          {shown && (
            <DetailPanel
              selection={selection}
              design={shown.design}
              findings={shown.findings}
              artifacts={artifacts}
              sql={sql}
              names={names}
              traceNodes={trace.nodes}
              pipeline={pipeline}
              onFinding={onFinding}
            />
          )}
        </aside>
      </div>
    </div>
  )
}

export default AiWorkspacePage
