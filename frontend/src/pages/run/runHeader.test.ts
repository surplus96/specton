import { expect, it } from 'vitest'
import { runEyebrow } from './runHeader.ts'
it('공통 머리글은 화면·파일명·사람이 읽는 현재 설계안 차수를 보인다', () => {
  expect(runEyebrow('추출 확인','재고.csv',0)).toBe('추출 확인 · 재고.csv · 1차 설계안')
  expect(runEyebrow('최종 검토','재고.csv',1)).toBe('최종 검토 · 재고.csv · 2차 설계안')
})
