import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import SqlValidationPanel from './SqlValidationPanel.tsx'
import { sqlReview } from './sqlValidation.ts'

const at = '2026-11-10T00:00:00Z'
const artifact = (status: unknown, revision = 2) => ({
  kind: 'ddl', file_format: 'sql', revision, validation: { status, validated_at: at },
})

describe('최종 HITL SQL 검증 요약', () => {
  it.each(['passed', 'failed', 'error', 'unverified'] as const)('서버가 반환한 %s를 구분한다', (status) => {
    expect(sqlReview([artifact(status)], 2)).toEqual({ status, validatedAt: at })
  })

  it('다른 revision의 성공·SQL 없음·검증 정보 없음·알 수 없는 값을 성공으로 보이지 않는다', () => {
    expect(sqlReview([artifact('passed', 1)], 2).status).toBe('missing')
    expect(sqlReview(undefined, 2).status).toBe('missing')
    expect(sqlReview([null, { kind: 'ddl', file_format: 'sql', revision: 2 }], 2).status).toBe('unverified')
    expect(sqlReview([artifact('ok')], 2).status).toBe('unverified')
    expect(sqlReview([artifact(true)], 2).status).toBe('unverified')
    expect(sqlReview([artifact('passed'), artifact('failed')], 2).status).toBe('unverified')
  })

  it('시각 누락·오류가 있을 때 잘못된 날짜를 표시하지 않는다', () => {
    const row = artifact('passed')
    expect(sqlReview([{ ...row, validation: { status: 'passed', validated_at: 'bad date' } }], 2))
      .toEqual({ status: 'passed', validatedAt: null })
  })

  it.each([
    ['passed', 'SQL 검증 통과'], ['failed', 'SQL 검증 실패'], ['error', 'SQL 검증 실행 오류'],
    ['unverified', 'SQL 미검증'], ['missing', 'SQL 산출물 없음'],
  ] as const)('화면에 %s 상태와 승인 안내를 출력한다', (status, title) => {
    const html = renderToStaticMarkup(createElement(SqlValidationPanel, { result: { status, validatedAt: at } }))
    expect(html).toContain(title)
    expect(html).toContain('검증 시각:')
    expect(html).toContain(status === 'passed' ? '서버가 최신 결과를 다시 확인' : '필수 검증 조건을 충족하지 못하면 승인할 수 없습니다')
  })
})
