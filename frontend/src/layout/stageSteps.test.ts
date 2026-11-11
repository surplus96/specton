import { describe, expect, it } from 'vitest'
import { STEPS, mergedState } from './stageSteps.ts'

describe('화면 단계 표시줄', () => {
  it('결과 보기와 최종 승인을 한 칸으로 묶어 6칸이다', () => {
    expect(STEPS.map((s) => s.title)).toEqual(['파일 올리기', '원문 확인', '요구사항 확인', '설계 중', '결과 보기 및 최종 승인', '내려받기'])
  })

  it('묶은 칸 상태: 어느 화면이든 지금이면 지금, 최종 승인이 끝났으면 완료, 결과만 있으면 결과 있음', () => {
    expect(mergedState(['available', 'now'])).toBe('now')
    expect(mergedState(['now', 'todo'])).toBe('now')
    expect(mergedState(['available', 'done'])).toBe('done')
    expect(mergedState(['available', 'todo'])).toBe('available')
    expect(mergedState(['todo', 'todo'])).toBe('todo')
    expect(mergedState(['skipped'])).toBe('skipped')
  })
})
