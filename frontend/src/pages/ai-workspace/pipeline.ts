// AI Workspace 왼쪽 「실행 단계 그래프」의 규칙 (#281). 화면 코드와 분리해 시험한다.
//
// 데이터는 상태 조회(GET /runs/{id})와 이벤트(SSE)뿐이다. 서버 이벤트는 단계(stage) 단위라
// 「설계」 안의 A02~정리, 병렬 생성·검토 가지별 진행은 바로 알 수 없다. 그래서
// - 생성 가지(DDL·ERD·RTM)는 그 revision의 산출물이 있으면 완료로 본다
// - 검토 가지(A05~A08)는 그 리뷰어의 지적이 있으면 완료, 최종 검토의 failed_branches면 실패로 본다
// - 설계 묶음(A02·A03·A04·정리)은 함께 진행 중으로 보인다 (노드 단위 이벤트는 백엔드 요청)
import type { RunStatus, SseEvent } from '../../api/types.ts'
import type { ArtifactRef, Finding } from '../../api/viewItems.ts'
import { reviewNotices } from '../review/rules.ts'
import { displayStage, requirementsCheckSkipped } from '../run/screens.ts'

export type NodeState = 'waiting' | 'running' | 'awaiting' | 'done' | 'failed' | 'skipped' | 'cancelled'

/** 상태 글자와 아이콘. 색만으로 구분하지 않는다 (docs/09 표현 기준). */
export const STATE_LABEL: Record<NodeState, { icon: string; text: string }> = {
  waiting: { icon: '○', text: '대기' },
  running: { icon: '◐', text: '진행 중' },
  awaiting: { icon: '⏸', text: '확인 대기' },
  done: { icon: '✓', text: '완료' },
  failed: { icon: '✕', text: '실패' },
  skipped: { icon: '↷', text: '건너뜀' },
  cancelled: { icon: '■', text: '취소' },
}

/** 노드를 누가 처리하는가. 「LLM은 판단만, ID·SQL·도면·RTM은 코드가 만든다」를 보이려고 쓴다 */
export type NodeKind = 'code' | 'ai' | 'human'

export const KIND_LABEL: Record<NodeKind, string> = { code: '코드 생성', ai: 'AI 판단', human: '사람 확인' }

export type PipelineNodeId =
  | 'parse'
  | 'extraction_check'
  | 'a01'
  | 'requirements_check'
  | 'a02'
  | 'a03'
  | 'a04'
  | 'normalize'
  | 'ddl'
  | 'erd'
  | 'rtm'
  | 'rules'
  | 'A05'
  | 'A06'
  | 'A07'
  | 'A08'
  | 'a09'
  | 'final_review'
  | 'export'

type Def = { id: PipelineNodeId; title: string; kind: NodeKind; step: number; lane?: number }

/** 노드 정의. step은 위→아래 순서, 같은 step의 노드는 병렬 가지(lane 0~3) */
export const PIPELINE: readonly Def[] = [
  { id: 'parse', title: '문서 읽기', kind: 'code', step: 0 },
  { id: 'extraction_check', title: '추출 확인', kind: 'human', step: 1 },
  { id: 'a01', title: 'A01 요구사항 분석', kind: 'ai', step: 2 },
  { id: 'requirements_check', title: '분석 확인', kind: 'human', step: 3 },
  { id: 'a02', title: 'A02 기능', kind: 'ai', step: 4 },
  { id: 'a03', title: 'A03 엔티티', kind: 'ai', step: 5 },
  { id: 'a04', title: 'A04 관계', kind: 'ai', step: 6 },
  { id: 'normalize', title: '모델 정리', kind: 'code', step: 7 },
  { id: 'ddl', title: 'DDL', kind: 'code', step: 8, lane: 0 },
  { id: 'erd', title: 'ERD', kind: 'code', step: 8, lane: 1 },
  { id: 'rtm', title: 'RTM', kind: 'code', step: 8, lane: 2 },
  { id: 'rules', title: '규칙 검사', kind: 'code', step: 9 },
  { id: 'A05', title: 'A05 관계 모순', kind: 'ai', step: 10, lane: 0 },
  { id: 'A06', title: 'A06 데이터 누락', kind: 'ai', step: 10, lane: 1 },
  { id: 'A07', title: 'A07 비기능', kind: 'ai', step: 10, lane: 2 },
  { id: 'A08', title: 'A08 업무 흐름', kind: 'ai', step: 10, lane: 3 },
  { id: 'a09', title: 'A09 재작업 판단', kind: 'ai', step: 11 },
  { id: 'final_review', title: '최종 검토', kind: 'human', step: 12 },
  { id: 'export', title: '내보내기', kind: 'code', step: 13 },
]

const GENERATORS = ['ddl', 'erd', 'rtm'] as const
const REVIEWERS = ['A05', 'A06', 'A07', 'A08'] as const
const DESIGN = ['a02', 'a03', 'a04', 'normalize'] as const

/** 연결선 (위 → 아래). 병렬 가지는 앞 노드에서 갈라지고 다음 노드에서 모인다. 재작업은 따로 표시한다 */
export type PipelineEdge = { from: PipelineNodeId; to: PipelineNodeId; rework?: boolean }

export function pipelineEdges(): PipelineEdge[] {
  const edges: PipelineEdge[] = []
  const steps = [...new Set(PIPELINE.map((d) => d.step))].sort((a, b) => a - b)
  for (let i = 0; i < steps.length - 1; i++) {
    const here = PIPELINE.filter((d) => d.step === steps[i])
    const next = PIPELINE.filter((d) => d.step === steps[i + 1])
    for (const a of here) for (const b of next) edges.push({ from: a.id, to: b.id })
  }
  edges.push({ from: 'a09', to: 'a02', rework: true }) // 지적 → 해당 단계로 되돌아감 (재작업)
  return edges
}

/** 진행 단계(stage) → 그 단계에서 일하는 노드 */
const NODES_OF_STAGE: Record<string, readonly PipelineNodeId[]> = {
  parsing: ['parse'],
  awaiting_input: ['extraction_check'],
  analysing: ['a01'],
  awaiting_requirements: ['requirements_check'],
  designing: DESIGN,
  generating: GENERATORS,
  reviewing: ['rules', ...REVIEWERS],
  awaiting_review: ['final_review'],
  review: ['final_review'],
  exporting: ['export'],
}

/** 이 노드가 속한 서버 단계(`stage`) 목록. 단계 상세에서 그 단계의 SSE 이벤트를 고를 때 쓴다 (#289) */
export function stagesOf(id: PipelineNodeId): string[] {
  return Object.entries(NODES_OF_STAGE)
    .filter(([, nodes]) => nodes.includes(id))
    .map(([stage]) => stage)
}

function stepOf(id: PipelineNodeId): number {
  return PIPELINE.find((d) => d.id === id)!.step
}

/** 지금 일하는 노드와 그 노드들의 단계(step) 범위. 모르면 빈 범위(-1) */
function activeNodes(stage: string | null): { ids: ReadonlySet<PipelineNodeId>; first: number; last: number } {
  const nodes = stage ? NODES_OF_STAGE[stage] : undefined
  if (!nodes) return { ids: new Set(), first: -1, last: -1 }
  const steps = nodes.map(stepOf)
  return { ids: new Set(nodes), first: Math.min(...steps), last: Math.max(...steps) }
}

export type PipelineInput = {
  run: Pick<RunStatus, 'status' | 'stage' | 'revision' | 'interrupt'>
  events: readonly SseEvent[]
  /** 지금 revision의 산출물 (view design의 artifacts) */
  artifacts: readonly ArtifactRef[]
  /** 지금 revision의 지적 (view review) */
  findings: readonly Finding[]
}

export type PipelineNode = Def & { state: NodeState; note: string | null }

/** 노드마다 상태와 짧은 설명. 상태 조회가 기준이고 이벤트·산출물·지적은 보조로 쓴다. */
export function pipelineNodes({ run, events, artifacts, findings }: PipelineInput): PipelineNode[] {
  const status = run.status
  const finished = status === 'completed'
  const stopped = status === 'failed' || status === 'cancelled' || status === 'cancel_requested'
  const stage = stopped ? displayStage(run.stage, events) : (run.stage ?? status)
  // 확인 대기는 interrupt.kind로 고른다 (screens.ts와 같은 기준)
  const hitl = run.interrupt?.kind
  const active = finished
    ? { ids: new Set<PipelineNodeId>(), first: Number.POSITIVE_INFINITY, last: Number.POSITIVE_INFINITY }
    : activeNodes(
        hitl
          ? hitl === 'extraction'
            ? 'awaiting_input'
            : hitl === 'requirements'
              ? 'awaiting_requirements'
              : 'awaiting_review'
          : stage === 'queued'
            ? null
            : stage,
      )
  const current = active.first

  const askedExtraction = events.some((e) => e.event === 'interrupt' && e.data.payload?.kind === 'extraction')
  const skippedRequirements = requirementsCheckSkipped(events)
  const made = new Set(artifacts.filter((a) => a.revision === run.revision).map((a) => a.kind))
  const reviewed = new Set(findings.filter((f) => f.source === 'llm' && f.reviewer_id).map((f) => f.reviewer_id!))
  const ruleFindings = findings.some((f) => f.source === 'rule')
  const { failedBranches } = reviewNotices(events, run.interrupt?.interrupt_id)

  return PIPELINE.map((def): PipelineNode => {
    const at = (state: NodeState, note: string | null = null): PipelineNode => ({ ...def, state, note })
    // 사람 확인 노드를 건너뛴 경우 (ADR-0015 조건부 확인)
    if (def.id === 'extraction_check' && !askedExtraction && current > def.step) return at('skipped', '확인할 원문이 없어 생략')
    if (def.id === 'requirements_check' && skippedRequirements) return at('skipped', '확인할 항목이 없어 생략')
    if (def.id === 'a09') {
      if (run.revision > 0) return at('done', `재작업 ${run.revision}회`)
      if (current > def.step) return at('skipped', '재작업 없음')
    }

    if (!active.ids.has(def.id) && (current === Number.POSITIVE_INFINITY || def.step < current)) {
      // 지나간 단계. 검토 가지가 실패했으면 그대로 보인다
      if ((REVIEWERS as readonly string[]).includes(def.id) && failedBranches.includes(def.id)) return at('failed', '이 관점 검토가 빠졌습니다')
      return at('done')
    }
    if (!active.ids.has(def.id)) return at('waiting', stopped ? '도달하지 않음' : null)

    // 지금 단계
    if (def.kind === 'human' && hitl) return at('awaiting', '사람의 확인을 기다립니다')
    if (stopped) {
      const cancelled = status !== 'failed'
      if ((GENERATORS as readonly string[]).includes(def.id) && made.has(def.id as (typeof GENERATORS)[number])) return at('done')
      return at(cancelled ? 'cancelled' : 'failed', cancelled ? '취소로 멈춤' : '이 단계에서 실패')
    }
    if ((GENERATORS as readonly string[]).includes(def.id)) {
      return made.has(def.id as (typeof GENERATORS)[number]) ? at('done', '산출물 있음') : at('running', '만드는 중')
    }
    if ((REVIEWERS as readonly string[]).includes(def.id)) {
      return reviewed.has(def.id) ? at('done', '지적 있음') : at('running', '검토 중 (지적 없으면 끝나도 그대로)')
    }
    if (def.id === 'rules') return ruleFindings ? at('done', '규칙 지적 있음') : at('running')
    if ((DESIGN as readonly string[]).includes(def.id)) return at('running', '설계 묶음 진행 중 (세부 단계는 서버가 알리지 않음)')
    return at('running')
  })
}

/** 전체 진행 요약: 완료·전체 노드 수 */
export function pipelineProgress(nodes: readonly PipelineNode[]): { done: number; total: number } {
  const counted = nodes.filter((n) => n.state !== 'skipped')
  return { done: counted.filter((n) => n.state === 'done').length, total: counted.length }
}
