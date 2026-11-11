import { describe, expect, it } from 'vitest'
import type { ArtifactRef } from '../../api/viewItems.ts'
import { reviewChecklist } from './checklist.ts'

const art = (kind: ArtifactRef['kind'], file_format: ArtifactRef['file_format'], revision = 1): ArtifactRef => ({
  kind, file_format, revision, hash: 'h', approved: false,
})

describe('최종 검토 산출물 확인 목록', () => {
  it('없는 산출물을 ✓로 보이지 않고, DDL은 SQL 검증 결과를 그대로 적는다', () => {
    const rows = reviewChecklist([], [art('erd', 'mmd', 0)], 1, { status: 'failed', validatedAt: null })
    expect(rows.map((r) => [r.key, r.ok])).toEqual([
      ['functions', false],
      ['erd', false],
      ['ddl', false],
      ['rtm', false],
    ])
    expect(rows[2].detail).toBe('SQL 검증 실패')
  })

  it('현재 revision의 산출물과 검증 통과면 ✓', () => {
    const rows = reviewChecklist([], [art('erd', 'mmd'), art('rtm', 'xlsx')], 1, { status: 'passed', validatedAt: null })
    expect(rows.filter((r) => r.ok).map((r) => r.key)).toEqual(['erd', 'ddl', 'rtm'])
  })
})

it('산출물 존재와 SQL 검사 사실을 사람이 확인한 것으로 표시하지 않는다', () => {
  const rows=reviewChecklist([], [art('erd','mmd'),art('rtm','csv')],1,{status:'unverified',validatedAt:null})
  expect(rows.map(r=>r.state)).toEqual(['없음','있음','미검증','있음'])
  expect(rows.some(r=>r.state.includes('확인'))).toBe(false)
})
