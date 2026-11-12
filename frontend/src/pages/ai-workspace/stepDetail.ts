// AI Workspace 단계 상세 (#289 1단계). 단계 노드를 고르면 그 단계의 SSE 이벤트와 중간 결과를 보인다.
// 지금 API(SSE·view)에 있는 값만 쓰고 추정으로 메우지 않는다. 노드 단위 시작·끝·LLM 호출 수치는 2단계(서버)에서 더한다.
import type { SseEvent } from '../../api/types.ts'
import type { AnalysedRequirement, ArtifactRef, DesignItem, ExtractionBlock, Finding } from '../../api/viewItems.ts'
import { REVIEWER_LABEL, SEVERITY_LABEL } from '../review/rules.ts'
import { stagesOf, type PipelineNodeId } from './pipeline.ts'

export type StepData = {
  runId?: string
  /** 화면에 보이는 revision (이벤트도 이 revision만) */
  revision: number
  /** 실행의 현재 revision (재작업 횟수) */
  runRevision: number
  blocks: readonly ExtractionBlock[]
  requirements: readonly AnalysedRequirement[]
  design: readonly DesignItem[]
  findings: readonly Finding[]
  artifacts: readonly ArtifactRef[]
  normalization?: Record<string, unknown> | null
}

export type StepRow = { label: string; value: string }

export type StepEvent = { id: number; event: SseEvent['event']; message: string; summary: string | null; at: string | null }

const GENERATED = new Set<PipelineNodeId>(['ddl', 'erd', 'rtm'])

/** 노드가 속한 단계의 이벤트 중 고른 revision 것만, 이벤트 ID 순서로. 산출물 이벤트는 그 산출물 노드에만 붙인다 */
export function stepEvents(id: PipelineNodeId, events: readonly SseEvent[], revision: number): StepEvent[] {
  const stages = new Set(stagesOf(id))
  return events
    .filter((e) => e.data.revision === revision && (e.data.payload?.node === id || (!e.data.payload?.node && stages.has(e.data.stage ?? ''))))
    .filter((e) => !(e.event === 'artifact' && GENERATED.has(id) && e.data.payload?.kind !== id))
    .sort((a, b) => a.id - b.id)
    .map((e) => ({ id: e.id, event: e.event, message: e.data.message, summary: payloadSummary(e.data.payload), at: typeof e.data.payload?.at === 'string' ? e.data.payload.at : null }))
}

const list = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : [])

/** 사람 확인 종류 · 멈춘 이유 · 문제 코드 · SQL 테스트 상태를 쉬운 말로 (화면에 영어 키를 보이지 않는다) */
const ASK_TEXT: Record<string, string> = { extraction: '원문 확인', requirements: '요구사항 확인', review: '최종 승인' }
const HITL_TEXT: Record<string, string> = {
  rework_limit: '세 번 다시 설계해도 의견이 남음',
  repeated_findings: '같은 의견이 되풀이됨',
  router_undecided: '어디부터 다시 설계할지 정하지 못함',
  manual_review: '사람이 판단해야 하는 의견이 있음',
}
const CODE_TEXT: Record<string, string> = {
  LLM_OUTPUT_INVALID: 'AI 답이 형식에 맞지 않음',
  LLM_UNAVAILABLE: 'AI에 연결하지 못함',
  LLM_REFUSED: 'AI가 답하지 않음',
  BUDGET_EXCEEDED: 'AI 사용 한도를 넘음',
  EXTRACTION_FAILED: '문서를 읽지 못함',
}
export const SQL_TEST_TEXT: Record<string, string> = { passed: '통과', failed: '실패', error: '테스트 중 문제', unverified: '검증 미완료' }
const seconds = (ms: number) => `${(ms / 1000).toFixed(1)}초`

/** payload의 알려진 칸을 짧은 글로. 원문·비밀값은 payload에 없으므로(docs/06) 그대로 옮겨도 된다 */
export function payloadSummary(payload: Record<string, unknown> | undefined): string | null {
  if (!payload) return null
  const parts: string[] = []
  if (payload.result_saved === false) parts.push('결과 저장 안 됨')
  if (payload.recovered) parts.push('멈춘 곳에서 이어서 진행')
  if (typeof payload.duration_ms === 'number') parts.push(`${seconds(payload.duration_ms)} 걸림`)
  if (Array.isArray(payload.calls)) for (const c of payload.calls) {
    if (c && typeof c === 'object') parts.push(`AI 사용량: 읽은 글 ${c.input_tokens} · 쓴 글 ${c.output_tokens} (토큰) · 다시 물어봄 ${Math.max(0, Number(c.attempt) - 1)}번 · ${seconds(Number(c.duration_ms))}`)
  }
  if (payload.file_format) parts.push(`만든 파일: ${String(payload.file_format).toUpperCase()}${payload.approved ? ' (승인본)' : ''}`)
  else if (payload.interrupt_id && payload.kind) parts.push(`사람 확인: ${ASK_TEXT[String(payload.kind)] ?? String(payload.kind)}`)
  if (list(payload.failed_branches).length) parts.push(`못 한 검토: ${list(payload.failed_branches).map((id) => REVIEWER_LABEL[id] ?? id).join(', ')}`)
  if (Array.isArray(payload.rejected_findings) && payload.rejected_findings.length) parts.push(`근거가 없어 뺀 의견 ${payload.rejected_findings.length}건`)
  if (payload.router_decision) parts.push('다시 설계할지 판단함')
  if (payload.hitl_reason) parts.push(`멈춘 이유: ${HITL_TEXT[String(payload.hitl_reason)] ?? String(payload.hitl_reason)}`)
  if (payload.info === 'skipped_sheets') parts.push(`건너뛴 시트: ${list(payload.sheets).join(', ')}`)
  if (payload.warning === 'excluded_related') parts.push(`제외 경고: ${String(payload.source_id)}`)
  if (Array.isArray(payload.confirmed_block_ids)) parts.push(`확인한 원문 ${payload.confirmed_block_ids.length}줄`)
  if (payload.code) parts.push(`문제: ${CODE_TEXT[String(payload.code)] ?? String(payload.code)}${payload.retryable ? ' (다시 해 볼 수 있음)' : ''}`)
  if (payload.detail) parts.push(String(payload.detail))
  return parts.length ? parts.join(' · ') : null
}

function counted(values: readonly string[]): string {
  const counts = new Map<string, number>()
  for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1)
  return [...counts].map(([k, n]) => `${k} ${n}`).join(' · ')
}

function artifactRows(kind: string, artifacts: readonly ArtifactRef[]): StepRow[] {
  const mine = artifacts.filter((a) => a.kind === kind)
  const files = mine.map((a) => `${a.file_format.toUpperCase()} ${a.approved ? '승인본' : '초안'}`).join(', ')
  const rows = [{ label: '파일', value: files || '아직 없음' }]
  if (kind === 'ddl') {
    const sql = mine.find((a) => a.file_format === 'sql') as (ArtifactRef & { validation?: { status: string; validated_at?: string | null } }) | undefined
    rows.push({ label: 'SQL 테스트', value: sql ? SQL_TEST_TEXT[sql.validation?.status ?? 'unverified'] ?? sql.validation?.status ?? '검증 미완료' : '없음' })
    if (sql?.validation?.validated_at) rows.push({ label: '테스트 시각', value: new Date(sql.validation.validated_at).toLocaleString('ko-KR') })
  }
  return rows
}

function findingRows(findings: readonly Finding[]): StepRow[] {
  if (findings.length === 0) return [{ label: '지적', value: '0건' }]
  return [{ label: '지적', value: `${findings.length}건 (${counted(findings.map((f) => SEVERITY_LABEL[f.severity]))})` }]
}

const NORMALIZATION_KINDS = new Set(['input_trace', 'invalid_fk_binding', 'no_primary_key', 'domain_type_mismatch', 'parent_without_key', 'optional_identifying_conflict', 'identifying_cycle', 'required_self_reference', 'unsupported_relationship', 'fk_column_conflict', 'unresolved_name', 'naming_rule_missing', 'name_too_long', 'reserved_word', 'duplicate_name'])

/** 단계별 중간 결과 요약. 보여 줄 값이 없는 단계(사람 확인 등)는 빈 목록 */
export function stepResult(id: PipelineNodeId, d: StepData): StepRow[] {
  const by = <T extends DesignItem['type']>(type: T) => d.design.filter((x): x is Extract<DesignItem, { type: T }> => x.type === type)
  switch (id) {
    case 'parse': {
      const n = (s: ExtractionBlock['extraction_status']) => d.blocks.filter((b) => b.extraction_status === s).length
      return [{ label: '블록', value: `${d.blocks.length}개 (정상 ${n('pass')} · 확인 필요 ${n('review')} · 실패 ${n('fail')})` }]
    }
    case 'extraction_check': {
      const checked = d.blocks.filter((b) => b.extraction_status !== 'pass')
      const n = (v: ExtractionBlock['user_decision']) => checked.filter((b) => b.user_decision === v).length
      return [{ label: '결정', value: `확인 ${n('confirmed')} · 제외 ${n('excluded')} · 결정 전 ${n(null)}` }]
    }
    case 'a01': {
      const fr = d.requirements.filter((r) => r.type === 'FR').length
      const issues = d.requirements.flatMap((r) => r.quality_issues.map((q) => q.kind))
      return [
        { label: '요구사항', value: `${d.requirements.length}개 (기능 ${fr} · 비기능 ${d.requirements.length - fr})` },
        { label: '분할', value: `${d.requirements.filter((r) => r.parent_id !== null).length}개` },
        { label: '품질 경고', value: issues.length ? counted(issues) : '없음' },
      ]
    }
    case 'a02': {
      const fns = by('function')
      return [{ label: '기능', value: `${fns.length}개 (엔티티 조작 연결 ${fns.reduce((n, f) => n + f.entity_ops.length, 0)})` }, ...fns.map((f) => ({ label: f.id, value: `${f.name} · ${f.entity_ops.map((op) => `${op.entity_id} ${op.operations.join('/')}`).join(', ')}` }))]
    }
    case 'a03': {
      const ents = by('entity')
      return [{ label: '엔티티', value: `${ents.length}개 (속성 ${ents.reduce((n, e) => n + e.attributes.length, 0)})` }, ...ents.map((e) => ({ label: e.id, value: `${e.name} · ${e.attributes.map((a) => a.name).join(', ')}` }))]
    }
    case 'a04': {
      const rels = by('relationship')
      const n = (pred: (r: (typeof rels)[number]) => boolean) => rels.filter(pred).length
      return [{ label: '관계', value: `${rels.length}개 (N:M ${n((r) => r.cardinality === 'N:M')} · 선택 ${n((r) => r.optional)} · 식별 ${n((r) => r.identifying)})` }, ...rels.map((r) => ({ label: r.id, value: `${r.parent} → ${r.child} · ${r.cardinality}` }))]
    }
    case 'normalize': {
      const summary = d.normalization
      return [
        ...(summary ? [{ label: '정리 결과', value: `테이블 ${summary.tables} · 컬럼 ${summary.columns} · FK ${summary.foreign_keys}` }, { label: '팩 버전', value: `${summary.pack_id} ${summary.pack_version} · common ${summary.common_version ?? '기록 없음'}` }] : []),
        { label: '정리 지적', value: `${d.findings.filter((f) => f.source === 'rule' && NORMALIZATION_KINDS.has(f.kind.split(':')[0])).length}건` },
      ]
    }
    case 'ddl':
    case 'erd':
    case 'rtm':
      return artifactRows(id, d.artifacts)
    case 'rules': {
      const codes = d.findings.filter((f) => f.source === 'rule').map((f) => (f.rule_code ?? '').split('-')[0] || '기타')
      return [{ label: '지적', value: codes.length ? counted(codes) : '0건' }]
    }
    case 'A05':
    case 'A06':
    case 'A07':
    case 'A08':
      return findingRows(d.findings.filter((f) => f.source === 'llm' && f.reviewer_id === id))
    case 'a09':
      return [{ label: '재작업', value: `${d.revision}회` }]
    case 'final_review':
    case 'export':
      return [{ label: '승인본', value: `${d.artifacts.filter((a) => a.approved).length} / ${d.artifacts.length}개` }]
    default:
      return []
  }
}
