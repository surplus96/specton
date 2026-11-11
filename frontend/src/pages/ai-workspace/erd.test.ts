import ELK from 'elkjs/lib/elk.bundled.js'
import { describe, expect, it } from 'vitest'
import type { DesignItem, Finding } from '../../api/viewItems.ts'
import { ELK_OPTIONS, erdModel, findingEntities, positionsFrom, relationshipLabel, toElk, typeText } from './erd.ts'

const attr = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  description: null,
  data_type: 'varchar',
  length: 20,
  precision: null,
  scale: null,
  is_key: false,
  is_unique: false,
  nullable: true,
  req_ids: [],
  ...extra,
})
const entity = (id: string, attrs = [attr(`${id}-K`, '코드', { is_key: true, nullable: false })]): DesignItem =>
  ({ type: 'entity', id, pack: 'inventory', name: `엔티티${id}`, description: '설명', attributes: attrs, req_ids: ['REQ-01'], crud_exemptions: [] }) as DesignItem
const rel = (id: string, parent: string, child: string, extra: Record<string, unknown> = {}): DesignItem =>
  ({ type: 'relationship', id, parent, child, cardinality: '1:N', optional: false, identifying: false, rationale: '', req_ids: [], ...extra }) as DesignItem

describe('ERD 캔버스: 카드와 선', () => {
  it('속성 줄에 PK·UQ·NULL·타입, 선에 카디널리티·선택·식별을 넣는다', () => {
    const design = [
      entity('E1', [attr('A1', '창고코드', { is_key: true, nullable: false }), attr('A2', '단가', { data_type: 'numeric', length: null, precision: 12, scale: 3, is_unique: true })]),
      entity('E2'),
      rel('REL-01', 'E1', 'E2', { optional: true, identifying: true }),
    ]
    const { cards, lines } = erdModel(design, [])
    expect(cards[0].attributes).toEqual([
      { id: 'A1', name: '창고코드', type: 'varchar(20)', pk: true, uq: false, nullable: false },
      { id: 'A2', name: '단가', type: 'numeric(12,3)', pk: false, uq: true, nullable: true },
    ])
    expect(lines).toEqual([{ id: 'REL-01', source: 'E1', target: 'E2', label: '1:N · 없어도 됨 · 부모 키 포함', identifying: true, optional: true }])
  })

  it('없는 엔티티를 가리키는 관계는 그리지 않는다', () => {
    expect(erdModel([entity('E1'), rel('REL-09', 'E1', 'E9')], []).lines).toEqual([])
  })

  it('엔티티별 지적 수: 엔티티·속성·관계 끝', () => {
    const findings = [
      { targets: [{ kind: 'attribute', id: 'E1-K' }] },
      { targets: [{ kind: 'relationship', id: 'REL-01' }] },
      { targets: [{ kind: 'entity', id: 'E2' }, { kind: 'attribute', id: 'E2-K' }] }, // 같은 지적은 한 번
    ] as Finding[]
    const { cards } = erdModel([entity('E1'), entity('E2'), rel('REL-01', 'E1', 'E2')], findings)
    expect(cards.map((c) => c.findingCount)).toEqual([2, 2])
  })

  it('지적이 가리키는 엔티티: 카드 배지·상세 목록·이동이 쓰는 한 가지 규칙, 없는 엔티티는 빼기', () => {
    const of = findingEntities([entity('E1'), entity('E2'), rel('REL-01', 'E1', 'E2'), rel('REL-09', 'E1', 'E9')])
    const f = (targets: Finding['targets']) => ({ targets }) as Finding
    expect(of(f([{ kind: 'relationship', id: 'REL-01' }]))).toEqual(['E1', 'E2']) // 부모 먼저
    expect(of(f([{ kind: 'attribute', id: 'E2-K' }, { kind: 'entity', id: 'E2' }]))).toEqual(['E2'])
    expect(of(f([{ kind: 'entity', id: 'E9' }, { kind: 'relationship', id: 'REL-09' }]))).toEqual(['E1'])
    expect(of(f([{ kind: 'requirement', id: 'REQ-01' }]))).toEqual([])
  })

  it('타입·선 글자', () => {
    expect(typeText({ data_type: 'date', length: null, precision: null, scale: null })).toBe('date')
    expect(relationshipLabel({ id: 'R', cardinality: 'N:M', optional: false, identifying: false })).toBe('N:M · 꼭 있음')
  })
})

describe('ERD 캔버스: ELK 배치', () => {
  it('서버 개요와 같은 layered · 위→아래, 자기참조는 배치 입력에서 뺀다', () => {
    const { cards, lines } = erdModel([entity('E1'), entity('E2'), rel('R1', 'E1', 'E2'), rel('R2', 'E1', 'E1')], [])
    const input = toElk(cards, lines)
    expect(input.layoutOptions['elk.algorithm']).toBe('layered')
    expect(input.layoutOptions['elk.direction']).toBe('DOWN')
    expect(input.edges.map((e) => e.id)).toEqual(['R1'])
  })

  it('엔티티 50개·관계 60개를 실제 elkjs로 배치: 겹치지 않고 부모가 자식보다 위, 2초 안', async () => {
    const design: DesignItem[] = Array.from({ length: 50 }, (_, i) =>
      entity(`E${i}`, Array.from({ length: 1 + (i % 6) }, (__, j) => attr(`E${i}-${j}`, `속성${j}`))),
    )
    // 60개 모두 다른 부모·자식 쌍 (부모 25개가 자식 2~3개씩, 자식도 부모 2~3개씩 받는다)
    for (let i = 0; i < 60; i++) design.push(rel(`R${i}`, `E${i % 25}`, `E${25 + (((i % 25) + 7 * Math.floor(i / 25) + 3) % 25)}`))
    const { cards, lines } = erdModel(design, [])
    expect(new Set(lines.map((l) => `${l.source}>${l.target}`)).size).toBe(60)
    const started = performance.now()
    const laidOut = await new ELK().layout(toElk(cards, lines))
    const elapsed = performance.now() - started
    const pos = positionsFrom(cards, laidOut)
    expect(elapsed).toBeLessThan(2000)
    const boxes = cards.map((c) => ({ ...pos[c.id], w: c.width, h: c.height }))
    const overlap = boxes.some((a, i) => boxes.some((b, j) => i < j && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h))
    expect(overlap).toBe(false)
    expect(lines.every((l) => pos[l.source].y < pos[l.target].y)).toBe(true)
    expect(ELK_OPTIONS['elk.direction']).toBe('DOWN')
  })

  it('ELK 결과에 없는 카드도 자리를 받는다', () => {
    const { cards } = erdModel([entity('E1'), entity('E2')], [])
    expect(Object.keys(positionsFrom(cards, { children: [{ id: 'E1', x: 5, y: 6 }] }))).toEqual(['E1', 'E2'])
  })
})
