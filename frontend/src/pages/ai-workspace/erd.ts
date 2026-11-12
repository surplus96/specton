// AI Workspace 「ERD 캔버스」 규칙 (#281). 화면 코드와 분리해 시험한다.
//
// 최종 Mermaid 산출물이 있으면 전체 테이블·관계를 사용하고, 없으면 설계 단계 모델을 사용한다.
// 배치는 ELK(layered)로, 서버 PDF ERD 개요(#273)와 같이 위→아래 방향이다. 이 파일은 ELK 입력·출력만 바꾸고
// elkjs는 부르지 않는다(화면에서 필요할 때 불러온다).
import type { DesignAttribute, DesignEntity, DesignItem, DesignRelationship, Finding } from '../../api/viewItems.ts'

export type AttributeRow = {
  id: string
  name: string
  type: string
  /** 키 글자: PK · FK · UK (여러 개면 쉼표) */
  keys: string
  /** 최종 ERD 설명 칸: 물리명 · 원래 표기. 최종 ERD가 아직 없으면 빈 글자 */
  note: string
}

/** 최종 ERD 한 테이블의 속성 줄 (specton/codegen/erd.py `타입 이름 키 "설명"`) */
export type FinalRow = Pick<AttributeRow, 'name' | 'type' | 'keys' | 'note'>

export type FinalErd = {
  tables: { id: string; name: string; rows: FinalRow[] }[]
  edges: { source: string; target: string; parent: string; child: string; identifying: boolean; relation: string }[]
}

/** 서버 render_erd의 문법만 받는다. 부분 파싱 결과를 최종 모델로 표시하지 않는다. */
export function parseFinalErd(text: string): FinalErd {
  const result: FinalErd = { tables: [], edges: [] }
  let rows: FinalRow[] | null = null
  if (text.trim().split('\n')[0].trim() !== 'erDiagram') throw new Error('ERD 머리글이 올바르지 않습니다')
  for (const raw of text.trim().split('\n').slice(1)) {
    const line = raw.trim()
    if (!line || line.startsWith('%%') || /^direction (TB|BT|LR|RL)$/.test(line)) continue
    if (rows) {
      if (line === '}') { rows = null; continue }
      const attr = /^(\S+)\s+(\S+)(?:\s+((?:PK|FK|UK)(?:,(?:PK|FK|UK))*))?\s+"(.*)"$/.exec(line)
      if (!attr) throw new Error('ERD 속성을 읽을 수 없습니다')
      rows.push({ type: attr[1], name: attr[2], keys: attr[3] ?? '', note: attr[4] })
      continue
    }
    const head = /^(\w+)\["(.*)"\]\s*\{$/.exec(line)
    if (head) {
      if (result.tables.some((t) => t.id === head[1])) throw new Error('ERD 테이블 식별자가 중복됩니다')
      rows = []
      result.tables.push({ id: head[1], name: head[2], rows })
      continue
    }
    const edge = /^(\w+)\s+(\|\||\|o)(--|\.\.)(o\{|o\|)\s+(\w+)\s*:\s*"(.*)"$/.exec(line)
    if (!edge) throw new Error('ERD 관계를 읽을 수 없습니다')
    result.edges.push({ source: edge[1], parent: edge[2], identifying: edge[3] === '--', child: edge[4], target: edge[5], relation: edge[6] })
  }
  if (rows) throw new Error('ERD 테이블이 닫히지 않았습니다')
  const ids = new Set(result.tables.map((t) => t.id))
  if (result.edges.some((e) => !ids.has(e.source) || !ids.has(e.target))) throw new Error('ERD 관계 대상이 없습니다')
  return result
}

export type EntityCard = {
  id: string
  name: string
  description: string
  attributes: AttributeRow[]
  reqIds: string[]
  findingCount: number
  width: number
  height: number
}

export type RelationshipLine = {
  id: string
  source: string
  target: string
  /** 선 위 글자: 카디널리티 · 선택 · 식별 */
  label: string
  /** 식별 관계는 실선, 비식별은 점선 (ERD 관례) */
  identifying: boolean
  optional: boolean
}

/** 타입 글자: varchar(20), numeric(12,3), date */
export function typeText(a: Pick<DesignAttribute, 'data_type' | 'length' | 'precision' | 'scale'>): string {
  if (a.length != null) return `${a.data_type}(${a.length})`
  if (a.precision != null) return a.scale != null ? `${a.data_type}(${a.precision},${a.scale})` : `${a.data_type}(${a.precision})`
  return a.data_type
}

export function relationshipLabel(r: Pick<DesignRelationship, 'id' | 'cardinality' | 'optional' | 'identifying'>): string {
  return [r.cardinality, r.optional ? '없어도 됨' : '꼭 있음', r.identifying ? '부모 키 포함' : null].filter(Boolean).join(' · ')
}

// 카드 크기 추정 (ELK가 겹치지 않게 배치하려면 크기를 먼저 알아야 한다). 화면 카드 CSS와 맞춘다
const ROW_HEIGHT = 22
const HEAD_HEIGHT = 40
const CHAR_WIDTH = 8.5
const MIN_WIDTH = 200
const MAX_WIDTH = 440

function cardSize(name: string, rows: readonly AttributeRow[]): { width: number; height: number } {
  const longest = Math.max(name.length * 1.6, ...rows.map((r) => r.name.length * 1.6 + r.type.length + r.keys.length + r.note.length * 1.3 + 6))
  const width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(longest * CHAR_WIDTH + 32)))
  return { width, height: HEAD_HEIGHT + Math.max(1, rows.length) * ROW_HEIGHT + 8 }
}

/**
 * 지적이 가리키는 엔티티: 엔티티 자신, 속성이면 그 엔티티, 관계면 부모·자식 (targets 순서, 중복 없음).
 * 카드 배지·상세 패널 목록·지적에서 ERD로 이동이 모두 이 규칙 하나를 쓴다. 없는 엔티티는 넣지 않는다.
 */
export function findingEntities(design: readonly DesignItem[]): (f: Finding) => string[] {
  const entities = design.filter((d): d is DesignEntity => d.type === 'entity')
  const ids = new Set(entities.map((e) => e.id))
  const owner = new Map(entities.flatMap((e) => e.attributes.map((a) => [a.id, e.id] as const)))
  const relEnds = new Map(
    design.filter((d): d is DesignRelationship => d.type === 'relationship').map((r) => [r.id, [r.parent, r.child]] as const),
  )
  return (f) => {
    const hit = new Set<string>()
    for (const t of f.targets) {
      if (t.kind === 'entity') hit.add(t.id)
      else if (t.kind === 'attribute' && owner.has(t.id)) hit.add(owner.get(t.id)!)
      else if (t.kind === 'relationship') relEnds.get(t.id)?.forEach((e) => hit.add(e))
    }
    return [...hit].filter((e) => ids.has(e))
  }
}

/**
 * 카드와 선. `final`이 있으면 최종 산출물의 전체 테이블과 관계를 사용한다.
 * 최종 ERD가 아직 없으면 설계 결과의 속성으로 같은 칸을 채운다.
 */
export function erdModel(
  design: readonly DesignItem[],
  findings: readonly Finding[],
  final?: FinalErd,
): { cards: EntityCard[]; lines: RelationshipLine[] } {
  const entities = design.filter((d): d is DesignEntity => d.type === 'entity')
  const rels = design.filter((d): d is DesignRelationship => d.type === 'relationship')
  const ids = new Set(entities.map((e) => e.id))
  const of = findingEntities(design)
  const counts = new Map<string, number>()
  for (const f of findings) for (const e of of(f)) counts.set(e, (counts.get(e) ?? 0) + 1)
  if (final) return finalModel(final, entities, counts)
  const cards = entities.map((e): EntityCard => {
    const attributes = e.attributes.map((a): AttributeRow => ({
      id: a.id, name: a.name, type: typeText(a),
      keys: [a.is_key && 'PK', a.is_unique && 'UK'].filter(Boolean).join(','), note: '',
    }))
    return { id: e.id, name: e.name, description: e.description, attributes, reqIds: e.req_ids, findingCount: counts.get(e.id) ?? 0, ...cardSize(e.name, attributes) }
  })
  // 양 끝 엔티티가 있는 관계만 그린다 (없는 대상을 메우지 않음)
  const lines = rels
    .filter((r) => ids.has(r.parent) && ids.has(r.child))
    .map((r): RelationshipLine => ({ id: r.id, source: r.parent, target: r.child, label: relationshipLabel(r), identifying: r.identifying, optional: r.optional }))
  return { cards, lines }
}

// 이름 대응은 추적 메타데이터에만 사용한다. 카드·관계의 구성은 최종 ERD가 결정한다.
function finalModel(final: FinalErd, entities: DesignEntity[], counts: Map<string, number>) {
  const alias = (name: string) => name.replace(/[\p{C}\p{Zl}\p{Zp}]/gu, ' ').replace(/%{2,}/g, '%').replace(/"/g, "'")
  const cards = final.tables.map((t): EntityCard => {
    const matches = entities.filter((e) => alias(e.name) === t.name)
    const entity = matches.length === 1 && final.tables.filter((other) => other.name === t.name).length === 1 ? matches[0] : undefined
    const id = entity?.id ?? `final:${t.id}`
    const attributes = t.rows.map((row, i) => ({ ...row, id: `${id}:${i}` }))
    return { id, name: t.name, description: entity?.description ?? '최종 ERD에서 생성된 테이블',
      attributes, reqIds: entity?.req_ids ?? [], findingCount: counts.get(id) ?? 0, ...cardSize(t.name, attributes) }
  })
  const ids = new Map(final.tables.map((t, i) => [t.id, cards[i].id]))
  const lines: RelationshipLine[] = final.edges.map((e, i) => ({
    id: `final-edge:${i}`, source: ids.get(e.source)!, target: ids.get(e.target)!,
    label: `${e.relation} · ${e.parent}${e.identifying ? '--' : '..'}${e.child}`,
    identifying: e.identifying, optional: e.parent === '|o',
  }))
  return { cards, lines }
}

/** ELK 입력 (elkjs의 ElkNode 모양). 서버 개요와 같은 layered · 위→아래 */
export type ElkInput = {
  id: string
  layoutOptions: Record<string, string>
  children: { id: string; width: number; height: number }[]
  edges: { id: string; sources: string[]; targets: string[] }[]
}

export const ELK_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'DOWN',
  'elk.spacing.nodeNode': '48',
  'elk.layered.spacing.nodeNodeBetweenLayers': '72',
  'elk.edgeRouting': 'POLYLINE',
  'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
}

export function toElk(cards: readonly EntityCard[], lines: readonly RelationshipLine[]): ElkInput {
  return {
    id: 'erd',
    layoutOptions: ELK_OPTIONS,
    children: cards.map((c) => ({ id: c.id, width: c.width, height: c.height })),
    // 자기참조는 배치에서 빼도 같다(같은 카드). 화면에서는 그린다
    edges: lines.filter((l) => l.source !== l.target).map((l) => ({ id: l.id, sources: [l.source], targets: [l.target] })),
  }
}

/** ELK 결과에서 카드 위치만 꺼낸다. 결과에 없는 카드는 왼쪽 위 격자에 둔다 */
export function positionsFrom(
  cards: readonly EntityCard[],
  laidOut: { children?: { id: string; x?: number; y?: number }[] },
): Record<string, { x: number; y: number }> {
  const placed = new Map((laidOut.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]))
  return Object.fromEntries(
    cards.map((c, i) => [c.id, placed.get(c.id) ?? { x: (i % 5) * (MAX_WIDTH + 40), y: Math.floor(i / 5) * 260 }]),
  )
}
