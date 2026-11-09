// UI-02 추출 확인 규칙 테스트. 화면 규칙이 서버(mock) 422 조건과 맞는지까지 본다.
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createRun, getRun, getView, resumeRun, setApiBaseUrl } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import type { ExtractionResponse } from '../../api/types.ts'
import type { ExtractionBlock } from '../../api/viewItems.ts'
import { createMockBackend } from '../../mocks/backend.ts'
import {
  STOP_RESPONSE,
  buildResponse,
  initialDecisions,
  locationText,
  problems,
  relatedWarnings,
  skippedSheets,
  sortBlocks,
  type Decisions,
} from './rules.ts'

const block = (block_id: string, status: ExtractionBlock['extraction_status'], extra: Partial<ExtractionBlock> = {}): ExtractionBlock => ({
  document_id: 'doc-1',
  block_id,
  source_id: null,
  source_ref: { file_format: 'csv', row: 2 },
  source_text: '문장',
  source_acceptance_level: null,
  source_related_requirements: null,
  source_extra: {},
  extraction_status: status,
  notice: null,
  user_decision: null,
  excluded_reason: null,
  ...extra,
})

const blocks = [block('B1', 'pass'), block('B2', 'review'), block('B3', 'fail'), block('B4', 'pass'), block('B5', 'review')]

describe('표시', () => {
  it('fail → review → pass, 같은 판정 안에서는 원문 순서', () => {
    expect(sortBlocks(blocks).map((b) => b.block_id)).toEqual(['B3', 'B2', 'B5', 'B1', 'B4'])
  })

  it.each([
    [{ file_format: 'xlsx', sheet: '요구사항', row: 4 }, '요구사항 시트 4행'],
    [{ file_format: 'csv', row: 7 }, '7행'],
    [{ file_format: 'hwpx', section: 0, paragraph: 12, table: 1 }, '0구역 12문단 · 표 1'],
    [{ file_format: 'hwp', section: 1, paragraph: 3 }, '1구역 3문단'],
    [{ file_format: 'pdf', page: 3, block: 2 }, '3쪽 2번째 블록'],
  ] as const)('원문 위치 %o → %s', (ref, text) => {
    expect(locationText(ref)).toBe(text)
  })

  it('건너뛴 시트는 이벤트 payload에서 모은다', () => {
    const payloads = [undefined, { info: 'skipped_sheets', sheets: ['표지', '개정이력'] }, { warning: 'excluded_related' }]
    expect(skippedSheets(payloads)).toEqual(['표지', '개정이력'])
  })
})

describe('결정과 보내기', () => {
  it('처음에는 review·fail만 결정을 두고, 모두 「확인」', () => {
    expect(initialDecisions(blocks)).toEqual({
      B2: { exclude: false, reason: '' },
      B3: { exclude: false, reason: '' },
      B5: { exclude: false, reason: '' },
    })
  })

  it('제외하지 않은 fail이 남으면 보낼 수 없다', () => {
    expect(problems(blocks, initialDecisions(blocks))).toEqual(['B3: 추출에 실패한 블록은 제외해야 합니다'])
  })

  it('review를 제외하려면 사유가 필요하다 (공백만은 안 됨). fail은 사유 없이 제외', () => {
    const d: Decisions = { ...initialDecisions(blocks), B2: { exclude: true, reason: '   ' }, B3: { exclude: true, reason: '' } }
    expect(problems(blocks, d)).toEqual(['B2: 제외 사유를 적어 주세요'])
    d.B2 = { exclude: true, reason: ' 중복 ' }
    expect(problems(blocks, d)).toEqual([])
    expect(buildResponse(blocks, d)).toEqual({
      kind: 'extraction',
      confirmed: true,
      excluded_blocks: [
        { block_id: 'B2', reason: '중복' },
        { block_id: 'B3', reason: null },
      ],
    })
  })

  it('전체 중단은 제외 목록 없이 confirmed: false', () => {
    expect(STOP_RESPONSE).toEqual({ kind: 'extraction', confirmed: false, excluded_blocks: [] })
  })
})

describe('관련 요구사항 경고', () => {
  const withIds = [
    block('B1', 'review', { source_id: 'SFR-003' }),
    block('B2', 'pass', { source_id: 'SFR-004', source_related_requirements: 'SFR-003, SFR-001' }),
    block('B3', 'pass', { source_id: 'SFR-005', source_related_requirements: 'SFR-0031' }), // 다른 ID
    block('B4', 'review', { source_id: 'SFR-006', source_related_requirements: 'SFR-003' }),
  ]

  it('제외한 원문의 ID를 관련 요구사항으로 적은 남은 원문을 찾는다', () => {
    const d: Decisions = { ...initialDecisions(withIds), B1: { exclude: true, reason: '중복' } }
    expect(relatedWarnings(withIds, d)).toEqual([{ block_id: 'B1', source_id: 'SFR-003', related_block_ids: ['B2', 'B4'] }])
  })

  it('함께 제외한 원문은 남지 않으므로 세지 않는다', () => {
    const d: Decisions = { ...initialDecisions(withIds), B1: { exclude: true, reason: 'a' }, B4: { exclude: true, reason: 'b' } }
    expect(relatedWarnings(withIds, d)).toEqual([{ block_id: 'B1', source_id: 'SFR-003', related_block_ids: ['B2'] }])
  })

  it('제외하지 않으면 경고 없음', () => {
    expect(relatedWarnings(withIds, initialDecisions(withIds))).toEqual([])
  })
})

// 화면 규칙을 통과한 답은 서버(mock)도 받고, 화면이 막는 답은 서버도 422로 막는지 본다
describe('서버(mock)와 같은 결과', () => {
  const server = setupServer()
  beforeAll(() => {
    setApiBaseUrl('http://specton.test')
    server.listen({ onUnhandledRequest: 'error' })
  })
  afterAll(() => server.close())
  beforeEach(() => server.resetHandlers(...createMockBackend({ stepMs: 0 }).handlers))

  async function waiting(name = '요구사항.csv') {
    const created = await createRun(new File(['내용'], name), 'inventory')
    const run = await getRun(created.run_id)
    const view = await getView(run.run_id, 'extraction')
    return { run, items: view.items as ExtractionBlock[] }
  }
  const answer = (run: Awaited<ReturnType<typeof waiting>>['run'], response: ExtractionResponse) =>
    resumeRun(run.run_id, { interrupt_id: run.interrupt!.interrupt_id, expected_revision: run.revision, response })

  it('mock 블록: 원문 없는 행은 review이고, 확인할 블록이 있다', async () => {
    const { run, items } = await waiting()
    expect(run.interrupt?.kind).toBe('extraction')
    expect(items.find((b) => b.source_text === null)?.extraction_status).toBe('review')
    expect(problems(items, initialDecisions(items))).toEqual(['B5: 추출에 실패한 블록은 제외해야 합니다'])
  })

  it('화면이 막는 답(fail 미제외)은 서버도 422, 메시지는 같은 블록 ID로 시작', async () => {
    const { run, items } = await waiting()
    const err = await answer(run, buildResponse(items, initialDecisions(items))).catch((e: unknown) => e)
    expect((err as ApiError).status).toBe(422)
    expect((err as ApiError).message).toMatch(/^B5: /)
  })

  it('화면 규칙을 통과한 답은 받아들여 분석으로 넘어가고, 관련 요구사항 경고를 남긴다', async () => {
    const { run, items } = await waiting()
    const d: Decisions = { ...initialDecisions(items), B5: { exclude: true, reason: '' }, B3: { exclude: true, reason: '중복 행' } }
    expect(problems(items, d)).toEqual([])
    expect(relatedWarnings(items, d)).toEqual([{ block_id: 'B3', source_id: 'SFR-002', related_block_ids: ['B4'] }])
    const next = await answer(run, buildResponse(items, d))
    expect(next.status).toBe('analysing')
  })

  it('conflict: 첫 답은 409, 상태를 다시 읽어 새 확인 요청으로 답하면 받아들인다', async () => {
    const { run, items } = await waiting('재고_conflict.csv')
    const d: Decisions = { ...initialDecisions(items), B5: { exclude: true, reason: '' } }
    const err = await answer(run, buildResponse(items, d)).catch((e: unknown) => e)
    expect((err as ApiError).code).toBe('INTERRUPT_STALE')
    const fresh = await getRun(run.run_id)
    expect(fresh.interrupt?.interrupt_id).not.toBe(run.interrupt?.interrupt_id)
    expect((await answer(fresh, buildResponse(items, d))).status).toBe('analysing')
  })
})
