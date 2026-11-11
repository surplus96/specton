import type { ArtifactRef, DesignEntity, DesignFunction, DesignItem, Finding, Severity } from '../../api/viewItems.ts'
import { dark } from '../../theme.ts'
import { SEVERITY_LABEL, STAGE_LABEL, plainText, sortFindings, sourceText, targetText } from '../review/rules.ts'
import type { SqlReview } from '../review/sqlValidation.ts'
import { KIND_LABEL as ARTIFACT_LABEL, missingKinds } from '../workspace/rules.ts'
import { findingEntities } from './erd.ts'
import { KIND_LABEL, STATE_LABEL, type PipelineNode } from './pipeline.ts'
import { stepEvents, stepResult, type StepData } from './stepDetail.ts'
import { COLUMN_TITLE, MARK_LABEL, refText, type TraceNode } from './trace.ts'
import type { SseEvent } from '../../api/types.ts'
import { nodeEvent, nodeState } from './nodeEvents.ts'
import { useState } from 'react'
import { downloadArtifact } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'

// 오른쪽 「상세·검증」 패널 (#281). 위: 고른 항목의 상세 / 아래: 검증 결과(SQL·미완성 가지·지적).
export type Selection =
  | { kind: 'entity'; id: string }
  | { kind: 'trace'; key: string }
  | { kind: 'pipeline'; id: string }
  | { kind: 'finding'; id: string }

const SEVERITY_COLOR: Record<Severity, string> = { critical: 'var(--darktones-failed-fg)', major: 'var(--darktones-awaiting-fg)', minor: dark.inkMuted }

const SQL_LABEL: Record<SqlReview['status'], { text: string; color: string }> = {
  missing: { text: 'SQL을 아직 못 만들었어요', color: dark.inkMuted },
  unverified: { text: '미검증', color: dark.inkMuted },
  passed: { text: '통과', color: 'var(--darktones-done-fg)' },
  failed: { text: '실패', color: 'var(--darktones-failed-fg)' },
  error: { text: '오류', color: 'var(--darktones-awaiting-fg)' },
}

type Props = {
  selection: Selection | null
  design: DesignItem[]
  findings: Finding[]
  artifacts: ArtifactRef[]
  sql: SqlReview
  names: Map<string, string>
  traceNodes: TraceNode[]
  pipeline: PipelineNode[]
  /** 단계 상세(#289): 실행의 SSE 이벤트와 고른 revision의 중간 결과 */
  events: readonly SseEvent[]
  step: StepData | null
  onFinding: (f: Finding) => void
}

function Title({ children }: { children: React.ReactNode }) {
  return <div className="aiws-section-title">{children}</div>
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '84px 1fr', gap: 8, padding: '3px 16px', fontSize: 13 }}>
      <span style={{ color: dark.inkMuted }}>{label}</span>
      <span>{children}</span>
    </div>
  )
}

function findingsOf(entityId: string, design: DesignItem[], findings: Finding[]): Finding[] {
  const of = findingEntities(design)
  return findings.filter((f) => of(f).includes(entityId))
}

function StepFiles({ node, step }: { node: PipelineNode; step: StepData }) {
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const files = step.artifacts.filter((a) => a.kind === node.id)
  async function read(file: ArtifactRef, show: boolean) {
    if (!step.runId) return
    setError(null)
    try {
      const { blob, fileName } = await downloadArtifact(step.runId, file.kind, file.file_format, step.revision)
      if (show) setPreview((await blob.text()).slice(0, 4000))
      else {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = fileName
        a.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      }
    } catch (err) { setError(errorMessage(err)) }
  }
  return <div style={{ padding: '0 16px', fontSize: 12 }}>
    {files.map((file) => <div key={file.file_format}>
      <button type="button" onClick={() => void read(file, false)}>{file.file_format.toUpperCase()} 파일 받기</button>
      {file.file_format === 'sql' && <button type="button" onClick={() => void read(file, true)}>SQL 미리 보기</button>}
    </div>)}
    {error && <p role="alert">{error}</p>}
    {preview !== null && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{preview}</pre>}
  </div>
}

function StepDetail({ node, events, step }: { node: PipelineNode; events: readonly SseEvent[]; step: StepData | null }) {
  const rows = step ? stepResult(node.id, step) : []
  const log = step ? stepEvents(node.id, events, step.revision) : []
  const recorded = step ? nodeEvent(node.id, events, step.revision) : undefined
  return (
    <>
      <Row label="진행 상태 안내">
        {recorded ? '이 단계의 실제 처리 기록이에요.' : '전체 진행 기록으로 표시했어요. 이 단계의 실제 처리 상태와 다를 수 있어요.'}
      </Row>
      <Title>중간 결과</Title>
      {node.state === 'skipped' && <p style={{ padding: '0 16px', fontSize: 13 }}>이 단계는 실행하지 않았습니다. 지적 0건은 검토 통과를 뜻하지 않습니다.</p>}
      {rows.length === 0 ? (
        <p style={{ padding: '0 16px', color: dark.inkMuted, fontSize: 13 }}>이 단계는 보여 줄 중간 결과가 없습니다.</p>
      ) : (
        rows.map((r) => (
          <Row key={r.label} label={r.label}>
            {r.value}
          </Row>
        ))
      )}
      {step && step.runId && <StepFiles key={`${step.runId}:${step.revision}:${node.id}`} node={node} step={step} />}
      <Title>진행 기록 {log.length}건</Title>
      {log.length === 0 ? (
        <p style={{ padding: '0 16px', color: dark.inkMuted, fontSize: 13 }}>이 설계안에서는 기록이 없어요.</p>
      ) : (
        <ol style={{ margin: 0, padding: '0 16px 0 36px', fontSize: 12 }}>
          {log.map((e) => (
            <li key={e.id} style={{ padding: '2px 0' }}>
              <span style={{ color: dark.inkMuted }}>
                {e.at ? new Date(e.at).toLocaleTimeString('ko-KR') : '(시각 기록 없음)'}
              </span>{' '}
              {e.message}
              {e.summary && <div style={{ color: dark.inkMuted }}>{e.summary}</div>}
            </li>
          ))}
        </ol>
      )}
    </>
  )
}

function SelectionDetail({ selection, design, findings, names, traceNodes, pipeline, events, step }: Props) {
  if (!selection) {
    return <p style={{ padding: '0 16px', color: dark.inkMuted, fontSize: 13 }}>왼쪽 단계나 가운데 그림에서 하나를 누르면 여기서 자세히 볼 수 있어요.</p>
  }
  if (selection.kind === 'pipeline') {
    const n = pipeline.find((p) => p.id === selection.id)
    if (!n) return null
    const observed = step ? nodeEvent(n.id, events, step.revision) : undefined
    const historical = step && step.revision !== step.runRevision
    const state = observed ? nodeState(observed) : historical ? null : n.state
    return (
      <>
        <Row label="단계">{n.title}</Row>
        <Row label="상태">
          {state ? `${STATE_LABEL[state].icon} ${STATE_LABEL[state].text}` : '선택 revision의 노드 상태 기록 없음'}
        </Row>
        <Row label="처리">{KIND_LABEL[n.kind]}</Row>
        {n.note && <Row label="설명">{n.note}</Row>}
        <StepDetail node={n} events={events} step={step} />
      </>
    )
  }
  if (selection.kind === 'trace') {
    const n = traceNodes.find((t) => t.key === selection.key)
    if (!n) return null
    return (
      <>
        <Row label="종류">{COLUMN_TITLE[n.column]}</Row>
        <Row label="이름">{n.title}</Row>
        {n.mark && <Row label="연결">{MARK_LABEL[n.mark]}</Row>}
        {n.detail && n.column !== 'block' && <Row label="내용">{n.detail}</Row>}
        {(n.column === 'block' || n.column === 'requirement') && (
          <>
            <Row label="원문 위치">{refText(n.sourceRef)}</Row>
            <Row label="원문">
              <span style={{ color: dark.inkMuted }}>{n.sourceText ?? '(문장 없음)'}</span>
            </Row>
          </>
        )}
      </>
    )
  }
  const entityId = selection.kind === 'entity' ? selection.id : null
  if (!entityId) return null
  const entity = design.find((d): d is DesignEntity => d.type === 'entity' && d.id === entityId)
  if (!entity) return null
  const crud = design
    .filter((d): d is DesignFunction => d.type === 'function')
    .flatMap((f) => f.entity_ops.filter((op) => op.entity_id === entityId).map((op) => `${f.id} ${f.name} (${op.operations.join(' ')})`))
  const related = findingsOf(entityId, design, findings)
  return (
    <>
      <Row label="테이블">{entity.name}</Row>
      <Row label="설명">{entity.description}</Row>
      <Row label="항목">{entity.attributes.length}개</Row>
      <Row label="근거 요구사항">{entity.req_ids.join(', ') || '없음'}</Row>
      <Row label="이 테이블을 쓰는 기능">{crud.length ? crud.map((c) => <div key={c}>{c}</div>) : '없음'}</Row>
      <Row label="검토 의견">{related.length ? related.map((f) => <div key={f.id}>{targetText(f.targets[0], names)}</div>) : '없음'}</Row>
    </>
  )
}

function DetailPanel(props: Props) {
  const { selection, findings, artifacts, sql, names, onFinding } = props
  const missing = missingKinds(artifacts)
  const sorted = sortFindings(findings)
  const activeFinding = selection?.kind === 'finding' ? selection.id : null
  return (
    <div aria-label="상세와 검증 결과">
      <Title>상세</Title>
      <SelectionDetail {...props} />

      <Title>점검 결과</Title>
      <Row label="SQL 테스트">
        <span style={{ color: SQL_LABEL[sql.status].color, fontWeight: 600 }}>{SQL_LABEL[sql.status].text}</span>
        {sql.validatedAt && <span style={{ color: dark.inkMuted }}> · {new Date(sql.validatedAt).toLocaleString('ko-KR')}</span>}
      </Row>
      <Row label="아직 없는 문서">
        {missing.length ? (
          <span style={{ color: 'var(--darktones-awaiting-fg)' }}>{missing.map((k) => ARTIFACT_LABEL[k]).join(', ')}</span>
        ) : (
          <span style={{ color: 'var(--darktones-done-fg)' }}>없어요 (문서 3종 다 있음)</span>
        )}
      </Row>

      <Title>검토 의견 {findings.length}건</Title>
      <div style={{ padding: '0 8px 16px' }}>
        {sorted.length === 0 && <p style={{ padding: '0 8px', color: dark.inkMuted, fontSize: 13 }}>의견이 없어요.</p>}
        {sorted.map((f) => {
          const open = activeFinding === f.id
          return (
            <button key={f.id} type="button" className={`aiws-list-item${open ? ' active' : ''}`} aria-expanded={open} onClick={() => onFinding(f)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                <span className="aiws-chip" style={{ borderColor: SEVERITY_COLOR[f.severity], color: SEVERITY_COLOR[f.severity] }}>
                  {SEVERITY_LABEL[f.severity]}
                </span>
                <span className="aiws-chip">{f.source === 'rule' ? '규칙 검사' : 'AI 검토'}</span>
                <span style={{ color: dark.inkMuted }}>{sourceText(f)}</span>
              </div>
              <div style={{ fontSize: 13, marginTop: 4 }}>{f.targets.map((t) => targetText(t, names)).join(', ') || '대상 없음'}</div>
              {open && (
                <div style={{ fontSize: 12, marginTop: 6, color: dark.inkMuted, display: 'grid', gap: 4 }}>
                  {f.evidence.map((e, i) => (
                    <div key={i}>
                      {e.req_id && <strong>{e.req_id} </strong>}「{plainText(e.quote)}」
                    </div>
                  ))}
                  <div style={{ color: dark.ink }}>이렇게 고쳐 보세요: {plainText(f.suggestion)}</div>
                  <div>고칠 곳: {f.kind === 'technical_identifier' ? '참고 · 기술용 이름 사용' : f.target_stage ? STAGE_LABEL[f.target_stage] : '판단 필요'}</div>
                </div>
              )}
            </button>
          )
        })}
      </div>

      <Title>표시</Title>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '0 16px 20px' }}>
        <span className="aiws-chip">AI가 판단: 요구사항 정리·설계·검토</span>
        <span className="aiws-chip">코드가 만듦: 이름·SQL·관계도·추적표·규칙 검사</span>
        <span className="aiws-chip">사람이 확인: 원문·요구사항·최종 승인</span>
      </div>
    </div>
  )
}

export default DetailPanel
