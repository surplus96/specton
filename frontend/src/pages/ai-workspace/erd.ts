// AI Workspace 「ERD 캔버스」 규칙 (#281). 화면 코드와 분리해 시험한다.
//
// Mermaid 그림이 아니라 view design의 entity·relationship으로 카드와 선을 직접 만든다.
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

/**
 * 서버가 만든 ERD 원문(.mmd)에서 테이블별 속성 줄을 읽는다. 키는 테이블 표시 이름.
 * 원문 형식은 생성 코드가 정한다. 읽지 못한 줄은 건너뛴다.
 */
export function parseFinalErd(text: string): Map<string, FinalRow[]> {
  const tables = new Map<string, FinalRow[]>()
  let rows: FinalRow[] | null = null
  for (const line of text.split('\n')) {
    const head = /^\s*[^\s"]+\["(.*)"\]\s*\{\s*$/.exec(line)
    if (head) {
      rows = []
      tables.set(head[1], rows)
      continue
    }
    if (/^\s*\}\s*$/.test(line)) {
      rows = null
      continue
    }
    const attr = rows && /^\s*(\S+)\s+(\S+)(?:\s+((?:PK|FK|UK)(?:,(?:PK|FK|UK))*))?\s+"(.*)"\s*$/.exec(line)
    if (rows && attr) rows.push({ type: attr[1], name: attr[2], keys: attr[3] ?? '', note: attr[4] })
  }
  return tables
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
 * 카드와 선. `final`(최종 ERD 원문을 읽은 것)에 같은 이름의 테이블이 있으면 그 속성 줄을 그대로 쓴다.
 * 최종 ERD가 아직 없으면 설계 결과의 속성으로 같은 칸을 채운다.
 */
export function erdModel(
  design: readonly DesignItem[],
  findings: readonly Finding[],
  final?: ReadonlyMap<string, readonly FinalRow[]>,
): { cards: EntityCard[]; lines: RelationshipLine[] } {
  const entities = design.filter((d): d is DesignEntity => d.type === 'entity')
  const rels = design.filter((d): d is DesignRelationship => d.type === 'relationship')
  const ids = new Set(entities.map((e) => e.id))
  const of = findingEntities(design)
  const counts = new Map<string, number>()
  for (const f of findings) for (const e of of(f)) counts.set(e, (counts.get(e) ?? 0) + 1)
  const cards = entities.map((e): EntityCard => {
    const finalRows = final?.get(e.name)
    const attributes = finalRows
      ? finalRows.map((r, i): AttributeRow => ({ id: `${e.id}:${i}`, ...r }))
      : e.attributes.map(
          (a): AttributeRow => ({
            id: a.id,
            name: a.name,
            type: typeText(a),
            keys: [a.is_key && 'PK', a.is_unique && 'UK'].filter(Boolean).join(','),
            note: '',
          }),
        )
    return { id: e.id, name: e.name, description: e.description, attributes, reqIds: e.req_ids, findingCount: counts.get(e.id) ?? 0, ...cardSize(e.name, attributes) }
  })
  // 양 끝 엔티티가 있는 관계만 그린다 (없는 대상을 메우지 않음)
  const lines = rels
    .filter((r) => ids.has(r.parent) && ids.has(r.child))
    .map((r): RelationshipLine => ({ id: r.id, source: r.parent, target: r.child, label: relationshipLabel(r), identifying: r.identifying, optional: r.optional }))
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
