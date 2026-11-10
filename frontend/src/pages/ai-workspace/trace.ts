// AI Workspace 「문서 추적」 규칙 (#281). 화면 코드와 분리해 시험한다.
//
// 원문 블록 → 요구사항 → 기능 → 엔티티 → 관계 → 지적을 한 줄로 잇는다. 연결은 서버가 준 값으로만 만들고
// (원문 위치, parent_id, req_ids, entity_ops, 관계의 parent·child, 지적의 targets) 추정해서 메우지 않는다.
// RTM 파일은 받지 않고 같은 규칙으로 미연결을 계산한다 (TC-F12).
import type {
  AnalysedRequirement,
  DesignEntity,
  DesignFunction,
  DesignItem,
  DesignRelationship,
  ExtractionBlock,
  Finding,
  SourceRef,
} from '../../api/viewItems.ts'

export type TraceColumn = 'block' | 'requirement' | 'function' | 'entity' | 'relationship' | 'finding'

export const COLUMN_TITLE: Record<TraceColumn, string> = {
  block: '원문',
  requirement: '요구사항',
  function: '기능',
  entity: '엔티티',
  relationship: '관계',
  finding: '지적',
}

export const COLUMNS: readonly TraceColumn[] = ['block', 'requirement', 'function', 'entity', 'relationship', 'finding']

/** 연결 상태. 제외·확인(원문 없음)은 미연결로 세지 않는다 (docs/10) */
export type TraceMark = 'unlinked' | 'excluded' | 'no-source' | null

export const MARK_LABEL: Record<Exclude<TraceMark, null>, string> = {
  unlinked: '미연결',
  excluded: '제외',
  'no-source': '확인(원문 없음)',
}

export type TraceNode = {
  /** 화면 안에서 쓰는 ID: `<column>:<원래 ID>` */
  key: string
  column: TraceColumn
  id: string
  title: string
  detail: string | null
  mark: TraceMark
  /** 원문 위치와 원문 문장 (원문·요구사항). 원문은 화면에서 고치지 않는다 (ADR-0015) */
  sourceRef: SourceRef | null
  sourceText: string | null
}

export type TraceEdge = { from: string; to: string }

export type TraceGraph = { nodes: TraceNode[]; edges: TraceEdge[] }

export type TraceInput = {
  blocks: readonly ExtractionBlock[]
  requirements: readonly AnalysedRequirement[]
  design: readonly DesignItem[]
  findings: readonly Finding[]
}

const key = (column: TraceColumn, id: string) => `${column}:${id}`

/** 원문 위치를 비교할 열쇠. 위치 칸이 모두 같아야 같은 원문이다 */
export function refKey(ref: SourceRef | null | undefined): string | null {
  if (!ref) return null
  return [ref.file_format, ref.sheet, ref.row, ref.page, ref.block, ref.section, ref.paragraph, ref.table]
    .map((v) => (v === undefined || v === null ? '' : String(v)))
    .join('|')
}

/** 원문 위치를 사람이 읽는 글로 (예: 「요구사항 시트 5행」) */
export function refText(ref: SourceRef | null | undefined): string {
  if (!ref) return '위치 없음'
  const parts = [
    ref.sheet ? `${ref.sheet} 시트` : null,
    ref.row != null ? `${ref.row}행` : null,
    ref.page != null ? `${ref.page}쪽` : null,
    ref.table != null ? `표 ${ref.table}` : null,
    ref.paragraph != null ? `문단 ${ref.paragraph}` : null,
  ].filter(Boolean)
  return parts.length ? parts.join(' ') : ref.file_format
}

export function buildTrace({ blocks, requirements, design, findings }: TraceInput): TraceGraph {
  const functions = design.filter((d): d is DesignFunction => d.type === 'function')
  const entities = design.filter((d): d is DesignEntity => d.type === 'entity')
  const relationships = design.filter((d): d is DesignRelationship => d.type === 'relationship')
  const edges: TraceEdge[] = []
  const add = (from: string, to: string) => edges.push({ from, to })

  // 원문 → 요구사항: 같은 원문 위치. 분할 요구사항은 원래 요구사항에서 이어진다
  const blockByRef = new Map(blocks.map((b) => [refKey(b.source_ref), b]))
  for (const r of requirements) {
    if (r.parent_id && requirements.some((p) => p.id === r.parent_id)) {
      add(key('requirement', r.parent_id), key('requirement', r.id))
      continue
    }
    const block = blockByRef.get(refKey(r.source_ref))
    if (block) add(key('block', block.block_id), key('requirement', r.id))
  }
  // 요구사항 → 기능 (req_ids)
  const reqIds = new Set(requirements.map((r) => r.id))
  for (const f of functions) for (const r of f.req_ids) if (reqIds.has(r)) add(key('requirement', r), key('function', f.id))
  // 기능 → 엔티티 (entity_ops)
  const entityIds = new Set(entities.map((e) => e.id))
  for (const f of functions)
    for (const op of f.entity_ops) if (entityIds.has(op.entity_id)) add(key('function', f.id), key('entity', op.entity_id))
  // 엔티티 → 관계 (부모·자식 모두)
  for (const rel of relationships)
    for (const end of new Set([rel.parent, rel.child])) if (entityIds.has(end)) add(key('entity', end), key('relationship', rel.id))
  // 대상 → 지적 (속성은 그 엔티티로). 화면에 있는 대상만 잇는다 (없는 대상을 메우지 않음, TC-F12)
  const attrOwner = new Map(entities.flatMap((e) => e.attributes.map((a) => [a.id, e.id] as const)))
  const present = new Set([
    ...requirements.map((r) => key('requirement', r.id)),
    ...functions.map((f) => key('function', f.id)),
    ...entities.map((e) => key('entity', e.id)),
    ...relationships.map((r) => key('relationship', r.id)),
  ])
  for (const f of findings) {
    for (const t of f.targets) {
      const target =
        t.kind === 'attribute'
          ? attrOwner.has(t.id)
            ? key('entity', attrOwner.get(t.id)!)
            : null
          : key(t.kind === 'requirement' ? 'requirement' : t.kind, t.id)
      if (target && present.has(target)) add(target, key('finding', f.id))
    }
  }

  const unique = [...new Map(edges.map((e) => [`${e.from}>${e.to}`, e])).values()]
  const hasOut = new Set(unique.map((e) => e.from))
  const hasIn = new Set(unique.map((e) => e.to))

  const nodes: TraceNode[] = [
    ...blocks.map((b): TraceNode => {
      const excluded = b.user_decision === 'excluded'
      const noSource = !excluded && b.source_text === null && b.user_decision === 'confirmed'
      const k = key('block', b.block_id)
      return {
        key: k,
        column: 'block',
        id: b.block_id,
        title: b.source_id ?? '(원문 ID 없음)',
        detail: b.source_text,
        mark: excluded ? 'excluded' : noSource ? 'no-source' : hasOut.has(k) ? null : 'unlinked',
        sourceRef: b.source_ref,
        sourceText: b.source_text,
      }
    }),
    ...requirements.map((r): TraceNode => {
      const k = key('requirement', r.id)
      // RTM 기준: 기능에 이어지지 않은 요구사항(분할로 갈라진 원래 요구사항은 조각이 이어 감)은 미연결
      const linked = unique.some((e) => e.from === k && (e.to.startsWith('function:') || e.to.startsWith('requirement:')))
      return {
        key: k,
        column: 'requirement',
        id: r.id,
        title: r.id,
        detail: r.text,
        mark: linked ? null : 'unlinked',
        sourceRef: r.source_ref,
        sourceText: r.source_text,
      }
    }),
    ...functions.map((f): TraceNode => node('function', f.id, `${f.id} ${f.name}`, f.description, hasIn)),
    ...entities.map((e): TraceNode => node('entity', e.id, e.name, e.description, hasIn)),
    ...relationships.map(
      (rel): TraceNode => node('relationship', rel.id, rel.id, `${relationText(rel, entities)}`, hasIn),
    ),
    ...findings.map((f): TraceNode => ({ ...node('finding', f.id, f.id, f.suggestion, hasIn), mark: null })),
  ]
  return { nodes, edges: unique }
}

function node(column: TraceColumn, id: string, title: string, detail: string | null, hasIn: Set<string>): TraceNode {
  const k = key(column, id)
  return { key: k, column, id, title, detail, mark: hasIn.has(k) ? null : 'unlinked', sourceRef: null, sourceText: null }
}

function relationText(rel: DesignRelationship, entities: readonly DesignEntity[]): string {
  const name = (id: string) => entities.find((e) => e.id === id)?.name ?? id
  return `${name(rel.parent)} → ${name(rel.child)} (${rel.cardinality})`
}

/**
 * 고른 항목과 연결된 앞뒤 항목. 앞쪽(원문 방향)으로만 거슬러 오르고, 뒤쪽(지적 방향)으로만 따라 내려간다.
 * 옆 갈래(같은 엔티티를 쓰는 다른 기능 등)는 포함하지 않아 한 줄로 따라가게 한다.
 */
export function connected(graph: TraceGraph, selected: string): Set<string> {
  const result = new Set([selected])
  const walk = (start: string, next: (k: string) => string[]) => {
    const stack = [start]
    while (stack.length) {
      for (const n of next(stack.pop()!)) {
        if (result.has(n)) continue
        result.add(n)
        stack.push(n)
      }
    }
  }
  walk(selected, (k) => graph.edges.filter((e) => e.to === k).map((e) => e.from))
  walk(selected, (k) => graph.edges.filter((e) => e.from === k).map((e) => e.to))
  return result
}

/** 화면 위쪽에 보일 연결 요약 */
export function traceSummary(graph: TraceGraph): {
  requirements: number
  unlinkedRequirements: number
  excludedBlocks: number
  noSourceBlocks: number
} {
  const reqs = graph.nodes.filter((n) => n.column === 'requirement')
  const blocks = graph.nodes.filter((n) => n.column === 'block')
  return {
    requirements: reqs.length,
    unlinkedRequirements: reqs.filter((n) => n.mark === 'unlinked').length,
    excludedBlocks: blocks.filter((n) => n.mark === 'excluded').length,
    noSourceBlocks: blocks.filter((n) => n.mark === 'no-source').length,
  }
}
