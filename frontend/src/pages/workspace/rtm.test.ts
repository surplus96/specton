import { describe, expect, it } from 'vitest'
import type { DesignItem } from '../../api/viewItems.ts'
import { rtmRows } from './rtm.ts'

const design: DesignItem[] = [
  {
    type: 'function', id: 'FN-001', name: '입고', description: '', priority: null, priority_source: 'unspecified',
    priority_rationale: null, req_ids: ['REQ-001'], entity_ops: [{ entity_id: 'ENT-001', operations: ['C'] }, { entity_id: 'ENT-002', operations: ['U'] }],
  },
  {
    type: 'entity', id: 'ENT-003', pack: 'inventory', name: '이력', description: '', attributes: [], req_ids: ['REQ-009'], crud_exemptions: [],
  },
]

describe('RTM 화면 미리보기', () => {
  it('요구사항 → 기능 → 엔티티를 설계 값으로만 잇는다', () => {
    expect(rtmRows(design, ['REQ-001', 'REQ-002'])).toEqual([
      { reqId: 'REQ-001', functions: ['FN-001'], entities: ['ENT-001', 'ENT-002'], linked: true },
      { reqId: 'REQ-002', functions: [], entities: [], linked: false },
      { reqId: 'REQ-009', functions: [], entities: ['ENT-003'], linked: false },
    ])
  })

  it('요구사항 목록이 없으면 설계에 나온 요구사항만 보인다', () => {
    expect(rtmRows(design).map((r) => r.reqId)).toEqual(['REQ-001', 'REQ-009'])
  })
})
