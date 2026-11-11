import { describe, expect, it } from 'vitest'
import type { SseEvent } from '../../api/types.ts'
import { activityItems, clockTime, formatElapsed, stageTitle } from './activity.ts'

const ev = (id: number, event: SseEvent['event'], message: string, stage?: string): SseEvent => ({
  id,
  event,
  data: { run_id: 'r', revision: 1, stage: stage ?? null, message },
})

describe('서버 작업 패널 기록', () => {
  it('최신 기록이 맨 위다', () => {
    const items = activityItems([ev(1, 'status', '접수', 'queued'), ev(2, 'status', '문서를 읽습니다', 'parsing')])
    expect(items.map((i) => i.message)).toEqual(['문서를 읽습니다', '접수'])
  })

  it('종류·단계·문장이 같은 기록이 이어지면 한 줄로 합치고 횟수를 센다', () => {
    const items = activityItems([
      ev(1, 'status', '설계 중', 'designing'),
      ev(2, 'status', '설계 중', 'designing'),
      ev(3, 'artifact', '설계 중', 'designing'),
      ev(4, 'status', '설계 중', 'designing'),
    ])
    expect(items.map((i) => [i.id, i.event, i.count])).toEqual([
      [4, 'status', 1],
      [3, 'artifact', 1],
      [1, 'status', 2],
    ])
  })

  it('이벤트 종류는 글과 색으로 함께 보인다', () => {
    const [error] = activityItems([ev(1, 'error', '실패했습니다')])
    expect(error).toMatchObject({ label: '문제', tone: 'danger' })
    const [ask] = activityItems([ev(1, 'interrupt', '확인해 주세요', 'awaiting_input')])
    expect(ask).toMatchObject({ label: '확인 필요', tone: 'warning', stage: '원문 확인' })
  })

  it('단계 이름은 화면 이름으로 바꾸고 모르는 값은 그대로 둔다', () => {
    expect(stageTitle('parsing')).toBe('문서 읽기')
    expect(stageTitle('failed')).toBe('실패') // 서버는 실행 상태 이름도 stage로 보낸다
    expect(stageTitle('review')).toBe('최종 승인')
    expect(stageTitle('new_stage')).toBe('new_stage')
    expect(stageTitle(null)).toBeNull()
  })

  it('받은 시각을 붙이고, 합친 줄은 마지막으로 받은 시각을 쓴다', () => {
    const items = activityItems([ev(1, 'status', 'a'), ev(2, 'status', 'a'), ev(3, 'status', 'b')], { 1: 100, 2: 200 })
    expect(items.map((i) => [i.message, i.at])).toEqual([
      ['b', null],
      ['a', 200],
    ])
  })

  it('경과 시간과 받은 시각 글자', () => {
    expect(formatElapsed(45_000)).toBe('45초')
    expect(formatElapsed(125_000)).toBe('2분 05초')
    expect(formatElapsed(3_780_000)).toBe('1시간 03분')
    expect(formatElapsed(-5)).toBe('0초')
    expect(clockTime(new Date(2026, 10, 9, 14, 3, 7).getTime())).toBe('14:03:07')
  })

  it('기록이 없으면 빈 목록', () => {
    expect(activityItems([])).toEqual([])
  })
})
