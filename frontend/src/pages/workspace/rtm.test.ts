import { describe, expect, it } from 'vitest'
import { parseRtmCsv, RTM_COLUMNS } from './rtm.ts'
const header = RTM_COLUMNS.join(',') + '\r\n'
describe('정식 서버 RTM 미리보기', () => {
  it('관계와 제외 행을 포함해 서버가 기록한 칸을 그대로 보인다', () => {
    const rows = parseRtmCsv('\uFEFF' + header + 'S1,표1,R1,,입고,FR,F1,,REL1,연결,\r\nS2,표2,,,작업 지시,,,,,제외,사용자 제외\r\n')
    expect(rows[0]['엔티티']).toBe('')
    expect(rows[0]['관계']).toBe('REL1')
    expect(rows[1]['상태']).toBe('제외')
    expect(rows[1]['비고']).toBe('사용자 제외')
  })
  it('인용된 쉼표·개행·따옴표를 보존한다', () => {
    expect(parseRtmCsv(header + 'S1,,R1,,"입고,\n""검사""",FR,,,,미연결,')[0]['요구사항']).toBe('입고,\n"검사"')
  })
  it('열이 다르거나 잘린 CSV는 오류로 표시한다', () => {
    expect(() => parseRtmCsv('id,name\n1,2')).toThrow()
    expect(() => parseRtmCsv(header + 'S1,,"끝나지 않음')).toThrow()
    expect(() => parseRtmCsv(header + 'S1,R1')).toThrow()
  })
})
