import type { ArtifactRef, DesignEntity, DesignFunction, DesignItem, Finding, Severity } from '../../api/viewItems.ts'
import { dark } from '../../theme.ts'
import { SEVERITY_LABEL, STAGE_LABEL, sortFindings, sourceText, targetText } from '../review/rules.ts'
import type { SqlReview } from '../review/sqlValidation.ts'
import { KIND_LABEL as ARTIFACT_LABEL, missingKinds } from '../workspace/rules.ts'
import { findingEntities } from './erd.ts'
import { KIND_LABEL, STATE_LABEL, type PipelineNode } from './pipeline.ts'
import { stepEvents, stepResult, type StepData } from './stepDetail.ts'
import { COLUMN_TITLE, MARK_LABEL, refText, type TraceNode } from './trace.ts'
import type { SseEvent } from '../../api/types.ts'

// 오른쪽 「상세·검증」 패널 (#281). 위: 고른 항목의 상세 / 아래: 검증 결과(SQL·미완성 가지·지적).
export type Selection =
  | { kind: 'entity'; id: string }
  | { kind: 'trace'; key: string }
  | { kind: 'pipeline'; id: string }
  | { kind: 'finding'; id: string }

const SEVERITY_COLOR: Record<Severity, string> = { critical: '#f87171', major: '#fbbf24', minor: dark.inkMuted }

const SQL_LABEL: Record<SqlReview['status'], { text: string; color: string }> = {
  missing: { text: '없음 (DDL 미생성)', color: dark.inkMuted },
  unverified: { text: '미검증', color: dark.inkMuted },
  passed: { text: '통과', color: '#4ade80' },
  failed: { text: '실패', color: '#f87171' },
  error: { text: '오류', color: '#fbbf24' },
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

// 여러 노드가 한 서버 단계를 같이 쓰는 노드. 상태는 단계 이벤트로 추정한다(노드 단위 이벤트는 #289 2단계)
const SHARED_STAGE = new Set(['a02', 'a03', 'a04', 'normalize', 'ddl', 'erd', 'rtm', 'rules', 'A05', 'A06', 'A07', 'A08'])

function StepDetail({ node, events, step }: { node: PipelineNode; events: readonly SseEvent[]; step: StepData | null }) {
  const rows = step ? stepResult(node.id, step) : []
  const log = step ? stepEvents(node.id, events, step.revision) : []
  return (
    <>
      <Row label="상태 근거">
        {SHARED_STAGE.has(node.id) ? '서버 단계 이벤트로 추정 (노드 단위 이벤트 없음)' : '서버 상태·이벤트 기준'}
      </Row>
      <Title>중간 결과</Title>
      {rows.length === 0 ? (
        <p style={{ padding: '0 16px', color: dark.inkMuted, fontSize: 13 }}>이 단계는 보여 줄 중간 결과가 없습니다.</p>
      ) : (
        rows.map((r) => (
          <Row key={r.label} label={r.label}>
            {r.value}
          </Row>
        ))
      )}
      <Title>이벤트 기록 {log.length}건</Title>
      {log.length === 0 ? (
        <p style={{ padding: '0 16px', color: dark.inkMuted, fontSize: 13 }}>이 revision에서 이 단계의 이벤트가 없습니다.</p>
      ) : (
        <ol style={{ margin: 0, padding: '0 16px 0 36px', fontSize: 12 }}>
          {log.map((e) => (
            <li key={e.id} style={{ padding: '2px 0' }}>
              <span style={{ color: dark.inkMuted }}>
                #{e.id} {e.event}
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
    return <p style={{ padding: '0 16px', color: dark.inkMuted, fontSize: 13 }}>캔버스나 단계 그래프에서 항목을 고르면 여기에 상세가 보입니다.</p>
  }
  if (selection.kind === 'pipeline') {
    const n = pipeline.find((p) => p.id === selection.id)
    if (!n) return null
    return (
      <>
        <Row label="단계">{n.title}</Row>
        <Row label="상태">
          {STATE_LABEL[n.state].icon} {STATE_LABEL[n.state].text}
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
        <Row label="항목">{n.title}</Row>
        {n.mark && <Row label="연결">{MARK_LABEL[n.mark]}</Row>}
        {n.detail && n.column !== 'block' && <Row label="내용">{n.detail}</Row>}
        {(n.column === 'block' || n.column === 'requirement') && (
          <>
            <Row label="원문 위치">{refText(n.sourceRef)}</Row>
            <Row label="원문">
              <span style={{ color: dark.inkMuted }}>{n.sourceText ?? '(원문 문장 없음)'}</span>
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
      <Row label="엔티티">{entity.name}</Row>
      <Row label="설명">{entity.description}</Row>
      <Row label="속성">{entity.attributes.length}개</Row>
      <Row label="관련 REQ">{entity.req_ids.join(', ') || '없음'}</Row>
      <Row label="CRUD 기능">{crud.length ? crud.map((c) => <div key={c}>{c}</div>) : '없음'}</Row>
      <Row label="지적">{related.length ? related.map((f) => <div key={f.id}>{f.id} {targetText(f.targets[0], names)}</div>) : '없음'}</Row>
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

      <Title>검증 결과</Title>
      <Row label="SQL 검증">
        <span style={{ color: SQL_LABEL[sql.status].color, fontWeight: 600 }}>{SQL_LABEL[sql.status].text}</span>
        {sql.validatedAt && <span style={{ color: dark.inkMuted }}> · {new Date(sql.validatedAt).toLocaleString('ko-KR')}</span>}
      </Row>
      <Row label="미완성">
        {missing.length ? (
          <span style={{ color: '#fbbf24' }}>{missing.map((k) => ARTIFACT_LABEL[k]).join(', ')}</span>
        ) : (
          <span style={{ color: '#4ade80' }}>없음 (DDL·ERD·RTM 모두 있음)</span>
        )}
      </Row>

      <Title>지적 {findings.length}건</Title>
      <div style={{ padding: '0 8px 16px' }}>
        {sorted.length === 0 && <p style={{ padding: '0 8px', color: dark.inkMuted, fontSize: 13 }}>지적이 없습니다.</p>}
        {sorted.map((f) => {
          const open = activeFinding === f.id
          return (
            <button key={f.id} type="button" className={`aiws-list-item${open ? ' active' : ''}`} aria-expanded={open} onClick={() => onFinding(f)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                <span className="aiws-chip" style={{ borderColor: SEVERITY_COLOR[f.severity], color: SEVERITY_COLOR[f.severity] }}>
                  {SEVERITY_LABEL[f.severity]}
                </span>
                <span className="aiws-chip">{f.source === 'rule' ? '코드 규칙' : 'AI 검토'}</span>
                <span style={{ color: dark.inkMuted }}>{sourceText(f)}</span>
              </div>
              <div style={{ fontSize: 13, marginTop: 4 }}>{f.targets.map((t) => targetText(t, names)).join(', ') || '대상 없음'}</div>
              {open && (
                <div style={{ fontSize: 12, marginTop: 6, color: dark.inkMuted, display: 'grid', gap: 4 }}>
                  {f.evidence.map((e, i) => (
                    <div key={i}>
                      {e.req_id && <strong>{e.req_id} </strong>}「{e.quote}」
                    </div>
                  ))}
                  <div style={{ color: dark.ink }}>제안: {f.suggestion}</div>
                  <div>돌아갈 단계: {f.target_stage ? STAGE_LABEL[f.target_stage] : '판단 필요'}</div>
                </div>
              )}
            </button>
          )
        })}
      </div>

      <Title>표시</Title>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '0 16px 20px' }}>
        <span className="aiws-chip">AI 판단: A01~A09 (LLM)</span>
        <span className="aiws-chip">코드 생성: ID·SQL·ERD·RTM·규칙</span>
        <span className="aiws-chip">사람 확인: 추출·분석·최종 검토</span>
      </div>
    </div>
  )
}

export default DetailPanel
