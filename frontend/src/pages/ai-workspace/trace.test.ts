import { describe, expect, it } from 'vitest'
import type { AnalysedRequirement, DesignItem, ExtractionBlock, Finding } from '../../api/viewItems.ts'
import { buildTrace, connected, refKey, refText, traceSummary } from './trace.ts'

const ref = (row: number) => ({ file_format: 'xlsx' as const, sheet: '요구사항', row })
const block = (id: string, row: number, extra: Partial<ExtractionBlock> = {}): ExtractionBlock =>
  ({
    document_id: 'd',
    block_id: id,
    source_id: `SFR-${row}`,
    source_ref: ref(row),
    source_text: `원문 ${row}`,
    extraction_status: 'pass',
    user_decision: null,
    ...extra,
  }) as ExtractionBlock
const req = (id: string, row: number, extra: Partial<AnalysedRequirement> = {}): AnalysedRequirement =>
  ({ id, source_id: null, source_ref: ref(row), parent_id: null, text: `${id} 문장`, source_text: `원문 ${row}`, ...extra }) as AnalysedRequirement
const fn = (id: string, req_ids: string[], ops: string[]): DesignItem =>
  ({ type: 'function', id, name: id, description: '', req_ids, entity_ops: ops.map((e) => ({ entity_id: e, operations: ['R'] })) }) as DesignItem
const ent = (id: string, attrs: string[] = []): DesignItem =>
  ({ type: 'entity', id, name: `엔티티${id}`, description: '', attributes: attrs.map((a) => ({ id: a })), req_ids: [] }) as unknown as DesignItem
const rel = (id: string, parent: string, child: string): DesignItem =>
  ({ type: 'relationship', id, parent, child, cardinality: '1:N' }) as DesignItem
const finding = (id: string, targets: Finding['targets']): Finding => ({ id, targets, suggestion: '고치기' }) as Finding

// B1 → REQ-01 → FN-01 → E1 → REL-01 → (E2) / 지적 F1은 E1의 속성 A1을 가리킴
// B2 → REQ-02 (기능 없음: 미연결) / REQ-03은 REQ-01에서 분할 → FN-02 → E2
// B3 제외, B4 원문 없이 확인
const input = {
  blocks: [
    block('B1', 2),
    block('B2', 3),
    block('B3', 4, { user_decision: 'excluded' }),
    block('B4', 5, { source_text: null, user_decision: 'confirmed' }),
  ],
  requirements: [req('REQ-01', 2), req('REQ-02', 3), req('REQ-03', 2, { parent_id: 'REQ-01' })],
  design: [fn('FN-01', ['REQ-01'], ['E1']), fn('FN-02', ['REQ-03'], ['E2']), ent('E1', ['A1']), ent('E2'), rel('REL-01', 'E1', 'E2')],
  findings: [finding('F1', [{ kind: 'attribute', id: 'A1' }])],
}

describe('문서 추적: 연결 만들기', () => {
  it('원문 위치·분할·req_ids·entity_ops·관계·지적 대상으로만 잇는다', () => {
    const { edges } = buildTrace(input)
    const pairs = edges.map((e) => `${e.from} → ${e.to}`)
    expect(pairs).toEqual(
      expect.arrayContaining([
        'block:B1 → requirement:REQ-01',
        'requirement:REQ-01 → requirement:REQ-03', // 분할
        'requirement:REQ-01 → function:FN-01',
        'requirement:REQ-03 → function:FN-02',
        'function:FN-01 → entity:E1',
        'entity:E1 → relationship:REL-01',
        'entity:E2 → relationship:REL-01',
        'entity:E1 → finding:F1', // 속성 A1의 지적은 엔티티 E1로
      ]),
    )
    // 분할 조각은 원문에서 바로 잇지 않는다 (원래 요구사항을 거침)
    expect(pairs).not.toContain('block:B1 → requirement:REQ-03')
  })

  it('미연결은 그대로 미연결, 제외·확인(원문 없음)은 미연결로 세지 않는다 (TC-F12, docs/10)', () => {
    const graph = buildTrace(input)
    const mark = (k: string) => graph.nodes.find((n) => n.key === k)!.mark
    expect(mark('requirement:REQ-02')).toBe('unlinked') // 기능 없음
    expect(mark('requirement:REQ-01')).toBeNull()
    expect(mark('block:B3')).toBe('excluded')
    expect(mark('block:B4')).toBe('no-source')
    expect(traceSummary(graph)).toEqual({ requirements: 3, unlinkedRequirements: 1, excludedBlocks: 1, noSourceBlocks: 1 })
  })

  it('없는 대상을 가리키면 잇지 않는다 (메우지 않음)', () => {
    const graph = buildTrace({ ...input, design: [fn('FN-09', ['REQ-99'], ['E9'])], findings: [finding('F9', [{ kind: 'entity', id: 'E9' }])] })
    expect(graph.edges.some((e) => e.from.includes('REQ-99') || e.to.includes('E9'))).toBe(false)
  })
})

describe('문서 추적: 고른 항목의 앞뒤', () => {
  it('앞쪽으로 거슬러 오르고 뒤쪽으로 따라 내려가되 옆 갈래는 넣지 않는다', () => {
    const graph = buildTrace(input)
    const lit = connected(graph, 'function:FN-01')
    expect([...lit].sort()).toEqual(
      ['block:B1', 'entity:E1', 'finding:F1', 'function:FN-01', 'relationship:REL-01', 'requirement:REQ-01'].sort(),
    )
    expect(lit.has('function:FN-02')).toBe(false) // 같은 요구사항에서 갈라진 다른 기능
    expect(lit.has('entity:E2')).toBe(false) // 관계 반대편은 앞쪽이 아님
  })

  it('지적을 고르면 그 지적까지 오는 길이 모두 밝아진다', () => {
    const lit = connected(buildTrace(input), 'finding:F1')
    expect(lit.has('block:B1') && lit.has('requirement:REQ-01') && lit.has('function:FN-01')).toBe(true)
  })
})

describe('원문 위치', () => {
  it('위치 칸이 모두 같아야 같은 원문, 사람이 읽는 글로 보인다', () => {
    expect(refKey(ref(2))).toBe(refKey({ ...ref(2) }))
    expect(refKey(ref(2))).not.toBe(refKey(ref(3)))
    expect(refText(ref(5))).toBe('요구사항 시트 5행')
    expect(refText(null)).toBe('위치 없음')
  })
})
