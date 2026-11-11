import { afterEach, describe, expect, it, vi } from 'vitest'
import { rememberRunName, runFileName } from './runNames.ts'
let saved: string | null
function storage(value: string | null) {
  saved = value
  vi.stubGlobal('window', { localStorage: { getItem: () => saved, setItem: (_: string, next: string) => { saved = next } } })
}
afterEach(() => vi.unstubAllGlobals())
describe('브라우저 실행 이름 복구', () => {
  it('손상된 값과 배열을 파일 이름으로 렌더링하지 않는다', () => {
    storage('{"run":{"name":"bad"},"valid":"입고.xlsx"}')
    expect(runFileName('run')).toBeNull()
    expect(runFileName('valid')).toBe('입고.xlsx')
    storage('["입고.xlsx"]')
    expect(runFileName('0')).toBeNull()
    storage('bad json')
    expect(runFileName('run')).toBeNull()
  })
  it('손상 항목을 버리고 새 실행 이름을 저장한다', () => {
    storage('{"broken":5,"old":"재고.csv"}')
    rememberRunName('new', '입고.xlsx')
    expect(JSON.parse(saved!)).toEqual({old: '재고.csv', new: '입고.xlsx'})
  })
})
