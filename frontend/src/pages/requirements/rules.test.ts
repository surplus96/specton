// UI-03 분석 확인 규칙 테스트. 화면 규칙이 서버(mock) 422 조건과 맞는지까지 본다.
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createRun, getRun, getView, resumeRun, setApiBaseUrl } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import type { RequirementsResponse, RunStatus } from '../../api/types.ts'
import type { AnalysedRequirement, ExtractionBlock } from '../../api/viewItems.ts'
import { createMockBackend } from '../../mocks/backend.ts'
import { buildResponse as extractionResponse, initialDecisions } from '../extraction/rules.ts'
import {
  buildResponse,
  changedCount,
  initialAnswers,
  problems,
  sortRequirements,
  splitFromSameSource,
  switchAction,
  typeText,
  type Answers,
} from './rules.ts'

const req = (id: string, extra: Partial<AnalysedRequirement> = {}): AnalysedRequirement => ({
  id,
  source_id: `SFR-${id.slice(4)}`,
  source_ref: { file_format: 'csv', row: 2 },
  parent_id: null,
  text: `${id} 문장`,
  draft_text: `${id} 문장`,
  source_text: `${id} 문장`,
  source_acceptance_level: null,
  type: 'FR',
  nfr_category: null,
  quality_issues: [],
  analysis_version: 1,
  ...extra,
})

const issue = { kind: 'ambiguous', message: '모호합니다', question: '단위는?' }

describe('표시', () => {
  it('같은 원문에서 2건 이상 나온 요구사항을 찾는다', () => {
    const reqs = [req('REQ-01'), req('REQ-02', { source_id: 'SFR-09' }), req('REQ-03', { source_id: 'SFR-09' })]
    expect([...splitFromSameSource(reqs)]).toEqual(['REQ-02', 'REQ-03'])
  })

  it('품질 경고·나뉜 요구사항을 먼저, 나머지는 받은 순서', () => {
    const reqs = [
      req('REQ-01'),
      req('REQ-02', { quality_issues: [issue] }),
      req('REQ-03'),
      req('REQ-04', { source_id: 'SFR-01' }), // REQ-01과 같은 원문
    ]
    expect(sortRequirements(reqs).map((r) => r.id)).toEqual(['REQ-01', 'REQ-02', 'REQ-04', 'REQ-03'])
  })

  it('유형 표시', () => {
    expect(typeText({ type: 'FR', nfr_category: null })).toBe('기능')
    expect(typeText({ type: 'NFR', nfr_category: 'retention' })).toBe('품질 · 보관')
  })
})

describe('답과 보내기', () => {
  const reqs = [req('REQ-01'), req('REQ-02')]

  it('처음에는 모두 유지이고, 유지는 보내지 않는다', () => {
    const answers = initialAnswers(reqs)
    expect(problems(answers)).toEqual([])
    expect(buildResponse(answers)).toEqual({ kind: 'requirements', answers: [] })
    expect(changedCount(answers)).toBe(0)
  })

  it('수정은 지금 문장 1개, 분할은 지금 문장과 빈 칸으로 시작한다', () => {
    expect(switchAction(reqs[0], 'edit')).toEqual({ action: 'edit', texts: ['REQ-01 문장'] })
    expect(switchAction(reqs[0], 'split')).toEqual({ action: 'split', texts: ['REQ-01 문장', ''] })
    expect(switchAction(reqs[0], 'keep')).toEqual({ action: 'keep', texts: [] })
  })

  it('빈 문장(공백만 포함)과 1조각 분할은 막는다', () => {
    const answers: Answers = {
      'REQ-01': { action: 'edit', texts: ['  '] },
      'REQ-02': { action: 'split', texts: ['하나'] },
    }
    expect(problems(answers)).toEqual(['REQ-01: 빈 문장이 있습니다', 'REQ-02: 분할은 문장이 2개 이상이어야 합니다'])
  })

  it('바꾼 것만 공백을 지워 보낸다', () => {
    const answers: Answers = {
      'REQ-01': { action: 'keep', texts: [] },
      'REQ-02': { action: 'split', texts: [' 입고를 등록한다. ', '입고를 취소한다.'] },
    }
    expect(buildResponse(answers)).toEqual({
      kind: 'requirements',
      answers: [{ req_id: 'REQ-02', action: 'split', texts: ['입고를 등록한다.', '입고를 취소한다.'] }],
    })
    expect(changedCount(answers)).toBe(1)
  })
})

describe('서버(mock)와 같은 결과', () => {
  const server = setupServer()
  beforeAll(() => {
    setApiBaseUrl('http://specton.test')
    server.listen({ onUnhandledRequest: 'error' })
  })
  afterAll(() => server.close())
  beforeEach(() => server.resetHandlers(...createMockBackend({ stepMs: 0 }).handlers))

  const answer = (run: RunStatus, response: RequirementsResponse) =>
    resumeRun(run.run_id, { interrupt_id: run.interrupt!.interrupt_id, expected_revision: run.revision, response })

  /** 업로드 → 추출 확인(실패 블록만 제외) → 분석 확인에서 멈춘 상태 */
  async function atRequirements(name = '요구사항.csv') {
    const created = await createRun(new File(['내용'], name), 'inventory')
    const run = await getRun(created.run_id)
    const blocks = (await getView(run.run_id, 'extraction')).items as ExtractionBlock[]
    const decisions = initialDecisions(blocks)
    for (const b of blocks) if (b.extraction_status === 'fail') decisions[b.block_id].exclude = true
    await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: extractionResponse(blocks, decisions),
    })
    const waiting = await getRun(run.run_id)
    const reqs = (await getView(run.run_id, 'requirements')).items as AnalysedRequirement[]
    return { run: waiting, reqs }
  }

  it('분석 확인에서 멈추고, 질문이 있는 요구사항이 먼저 온다', async () => {
    const { run, reqs } = await atRequirements()
    expect(run.interrupt?.kind).toBe('requirements')
    expect(sortRequirements(reqs)[0].quality_issues.length).toBeGreaterThan(0)
  })

  it('화면 규칙을 통과한 분할·수정은 받아들이고, 나머지 조각에 새 ID가 붙는다', async () => {
    const { run, reqs } = await atRequirements()
    const answers: Answers = {
      ...initialAnswers(reqs),
      'REQ-02': { action: 'edit', texts: ['입고 시 거래처와 입고 수량(개)을 기록한다.'] },
      'REQ-03': { action: 'split', texts: ['입고 내역을 조회한다.', '품목분류로 걸러 본다.'] },
    }
    expect(problems(answers)).toEqual([])
    expect((await answer(run, buildResponse(answers))).status).toBe('designing')
    const after = (await getView(run.run_id, 'requirements')).items as AnalysedRequirement[]
    expect(after.find((r) => r.parent_id === 'REQ-03')?.id).toMatch(/^REQ-\d{2,}$/)
  })

  it('화면이 막는 답(빈 문장)은 서버도 422, 메시지는 같은 요구사항 ID로 시작', async () => {
    const { run } = await atRequirements()
    const bad: Answers = { 'REQ-02': { action: 'edit', texts: ['  '] } }
    expect(problems(bad)).toEqual(['REQ-02: 빈 문장이 있습니다'])
    const err = await answer(run, { kind: 'requirements', answers: [{ req_id: 'REQ-02', action: 'edit', texts: ['  '] }] }).catch(
      (e: unknown) => e,
    )
    expect((err as ApiError).status).toBe(422)
    expect((err as ApiError).message).toMatch(/^REQ-02: /)
  })

  it('no-questions: 추출 확인 뒤 분석 확인을 건너뛰고 설계로 간다', async () => {
    const created = await createRun(new File(['내용'], '재고_no-questions.csv'), 'inventory')
    const run = await getRun(created.run_id)
    expect(run.interrupt?.kind).toBe('extraction')
    const blocks = (await getView(run.run_id, 'extraction')).items as ExtractionBlock[]
    const decisions = initialDecisions(blocks)
    for (const b of blocks) if (b.extraction_status === 'fail') decisions[b.block_id].exclude = true
    await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: extractionResponse(blocks, decisions),
    })
    const next = await getRun(run.run_id)
    expect(next.interrupt?.kind).toBe('review') // stepMs 0이라 바로 최종 검토까지
  })
})


it('동일 원문 ID라도 다른 행이면 분할로 오인하지 않는다', () => {
  const rows = [req('REQ-01', { source_id: 'DUP', source_ref: { file_format: 'csv', row: 2 } }),
    req('REQ-02', { source_id: 'DUP', source_ref: { file_format: 'csv', row: 3 } })]
  expect([...splitFromSameSource(rows)]).toEqual([])
})
it('정상 자동 분할은 유지 상태에서 제출을 막지 않는다', () => {
  const rows = [req('REQ-01', { source_id: 'ONE' }), req('REQ-02', { source_id: 'ONE' })]
  const answers = initialAnswers(rows)
  expect(problems(answers)).toEqual([])
  expect(buildResponse(answers)).toEqual({ kind: 'requirements', answers: [] })
})
