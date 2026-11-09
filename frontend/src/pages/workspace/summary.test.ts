import { describe, expect, it } from 'vitest'
import type { DesignItem, Finding } from '../../api/viewItems.ts'
import { resultCounts } from './summary.ts'

const fn = (id: string, req_ids: string[]) =>
  ({ type: 'function', id, name: id, description: '', priority: null, priority_source: 'unspecified', priority_rationale: null, req_ids, entity_ops: [] }) as DesignItem
const ent = (id: string) => ({ type: 'entity', id }) as unknown as DesignItem
const rel = (id: string) => ({ type: 'relationship', id }) as unknown as DesignItem
const finding = (severity: Finding['severity']) => ({ severity }) as Finding

describe('결과 한눈에 보기 숫자', () => {
  it('종류별로 세고 요구사항은 기능이 이어 받은 ID를 중복 없이 센다', () => {
    const design = [fn('FN-01', ['REQ-01', 'REQ-02']), fn('FN-02', ['REQ-02']), ent('ENT-01'), ent('ENT-02'), rel('REL-01')]
    expect(resultCounts(design, [finding('critical'), finding('major'), finding('minor')])).toEqual({
      requirements: 2,
      functions: 2,
      entities: 2,
      relationships: 1,
      findings: 3,
      blocking: 1,
    })
  })

  it('비어 있으면 모두 0', () => {
    expect(resultCounts([], [])).toEqual({ requirements: 0, functions: 0, entities: 0, relationships: 0, findings: 0, blocking: 0 })
  })
})
