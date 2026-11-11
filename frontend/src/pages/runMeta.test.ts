import { describe, expect, it } from 'vitest'
import { fourStepStates, matchesQuery, revisionBadge, revisionText, runAction, runBadge, runMessage, untitledRunName } from './runMeta.ts'

describe('실행 카드 상태 칩', () => {
  it('사람 확인을 기다리면 라임 점이 있는 「확인 필요」', () => {
    for (const s of ['awaiting_input', 'awaiting_requirements', 'awaiting_review'] as const) {
      expect(runBadge(s)).toMatchObject({ text: '확인 필요', dot: true })
    }
  })

  it('완료·실패·취소·대기는 각각 글자로 구분한다', () => {
    expect(runBadge('completed').text).toBe('승인 완료')
    expect(runBadge('failed')).toMatchObject({ text: '실패', tone: 'danger' })
    expect(runBadge('cancelled').text).toBe('취소됨')
    expect(runBadge('queued').text).toBe('대기 중')
    expect(runBadge('designing').text).toBe('진행 중')
  })
})

describe('네 단계 진행 막대', () => {
  it('최종 검토 대기는 앞 세 단계 완료, 마지막 단계가 확인 필요', () => {
    expect(fourStepStates('awaiting_review')).toEqual(['done', 'done', 'done', 'wait'])
  })

  it('설계 중은 세 번째 단계가 진행 중', () => {
    expect(fourStepStates('generating')).toEqual(['done', 'done', 'now', 'todo'])
  })

  it('완료는 모두 완료', () => {
    expect(fourStepStates('completed')).toEqual(['done', 'done', 'done', 'done'])
  })

  it('실패는 멈춘 단계를 표시하고, 단계를 모르면 지어내지 않는다', () => {
    expect(fourStepStates('failed', 'analysing')).toEqual(['done', 'fail', 'todo', 'todo'])
    expect(fourStepStates('failed', null)).toEqual(['todo', 'todo', 'todo', 'todo'])
  })
})

describe('카드 안내와 행동', () => {
  it('확인 요청 문장이 있으면 그대로 쓴다', () => {
    expect(runMessage('awaiting_review', '서버 문장')).toBe('서버 문장')
  })

  it('진행 중 기본 문장이 어색하게 겹치지 않는다', () => {
    expect(runMessage('parsing')).toBe('지금 문서 읽는 중이에요. 확인이 필요한 곳이 생기면 멈추고 알려 드려요.')
  })

  it('최종 검토 대기는 「초안 검토하기」', () => {
    expect(runAction('awaiting_review')).toBe('초안 검토하기')
    expect(runAction('completed')).toBe('결과 보기')
  })
})

describe('작업 검색', () => {
  const run = { run_id: 'abc-123', status: 'completed' as const, created_at: '2026-05-12T05:03:00Z' }

  it('파일 이름·상태·ID의 낱말을 모두 포함해야 남긴다', () => {
    expect(matchesQuery(run, '재고_요구사항.xlsx', '재고 완료')).toBe(true)
    expect(matchesQuery(run, '재고_요구사항.xlsx', '재고 실패')).toBe(false)
    expect(matchesQuery(run, null, 'ABC')).toBe(true)
    expect(matchesQuery(run, null, '   ')).toBe(true)
  })
})

describe('사람에게 보이는 실행 이름·설계안 차수', () => {
  it('revision은 1차부터 센다', () => {
    expect(revisionText(0)).toBe('1차 설계안')
    expect(revisionText(2)).toBe('3차 설계안')
    expect(revisionBadge(1)).toBe('2차')
  })

  it('잘못된 revision 값은 1차로 보인다', () => {
    expect(revisionText(-1)).toBe('1차 설계안')
    expect(revisionBadge(Number.NaN)).toBe('1차')
  })

  it('파일 이름을 모르는 실행은 실행 ID 대신 시작 시각으로 부른다', () => {
    expect(untitledRunName('2026-11-12T14:03:00')).toBe('이름 없는 작업 · 2026.11.12 14:03')
    expect(untitledRunName(null)).toBe('이름 없는 작업')
    expect(untitledRunName('not-a-date')).toBe('이름 없는 작업')
  })
})
