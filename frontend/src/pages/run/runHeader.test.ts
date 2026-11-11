import { expect, it } from 'vitest'
import { runEyebrow } from './runHeader.ts'
it('공통 머리글은 실제 실행 ID·현재 revision을 보인다', () => {
  expect(runEyebrow('추출 확인','재고.csv','0ff2f56e-d8e3-4ad3-b5f9-2f64d17e2583',0)).toBe('추출 확인 · 재고.csv · 실행 0ff2f56e · revision 0')
})
