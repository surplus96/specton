// API 함수 + mock 서버 테스트. 진짜 서버 없이 `npm test`로 돈다.
// mock이 docs/06-api.md 규칙대로 응답하는지, API 함수가 오류를 ApiError로 바꾸는지 본다.
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createMockBackend } from '../mocks/backend.ts'
import {
  cancelRun,
  createRun,
  downloadArtifact,
  getRun,
  getView,
  listRuns,
  resumeRun,
  setApiBaseUrl,
} from './client.ts'
import { ApiError, errorMessage, nextAction } from './errors.ts'
import type { RunStatus } from './types.ts'

const server = setupServer()
let clock = 0
let backend = createMockBackend()

beforeAll(() => {
  setApiBaseUrl('http://specton.test')
  server.listen({ onUnhandledRequest: 'error' })
})
afterAll(() => server.close())
beforeEach(() => {
  clock = 0
  // 한 단계 10ms, 취소 100ms. 시간은 clock으로 직접 움직인다.
  backend = createMockBackend({ stepMs: 10, cancelMs: 100, now: () => clock })
  server.resetHandlers(...backend.handlers)
})

const csv = (name = '요구사항.csv') => new File(['요구사항 ID,요구사항명\nSFR-001,재고 관리\n'], name)
const later = (ms = 1000) => {
  clock += ms
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (err) {
    if (err instanceof ApiError) return err
    throw err
  }
  throw new Error('요청이 실패해야 하는데 성공했습니다')
}

async function startAndWait(name?: string): Promise<RunStatus> {
  const created = await createRun(csv(name), 'inventory')
  later()
  return getRun(created.run_id)
}

describe('실행 만들기 (UI-01)', () => {
  it('파일을 올리면 202로 접수되고, 시간이 지나면 추출 확인에서 멈춘다', async () => {
    const created = await createRun(csv(), 'inventory')
    expect(created).toMatchObject({ status: 'queued', revision: 0 })

    later()
    const run = await getRun(created.run_id)
    expect(run.status).toBe('awaiting_input')
    expect(run.interrupt?.kind).toBe('extraction')
  })

  it.each([
    ['문서.pdf', 415, 'UNSUPPORTED_MEDIA_TYPE', '지원하는 형식은 .xlsx, .csv, .hwpx, .hwp입니다.'],
  ])('%s는 %i로 거절하고 서버 문구를 그대로 보여 준다', async (name, status, code, message) => {
    const err = await rejection(createRun(csv(name), 'inventory'))
    expect(err.status).toBe(status)
    expect(err.code).toBe(code)
    expect(errorMessage(err)).toBe(message)
    expect(nextAction(err.code)).toBe('reupload')
  })

  it('없는 팩은 422 PACK_UNSUPPORTED', async () => {
    // @ts-expect-error 계약에 없는 팩을 일부러 보낸다
    const err = await rejection(createRun(csv(), 'hospital'))
    expect([err.status, err.code]).toEqual([422, 'PACK_UNSUPPORTED'])
  })

  it('빈 파일은 422 INVALID_REQUEST', async () => {
    const err = await rejection(createRun(new File([], 'empty.csv'), 'inventory'))
    expect([err.status, err.code]).toEqual([422, 'INVALID_REQUEST'])
  })

  it('목록은 최근 실행부터 돌려준다', async () => {
    const first = await createRun(csv(), 'inventory')
    later()
    const second = await createRun(csv(), 'maintenance')
    const list = await listRuns()
    expect(list.map((r) => r.run_id)).toEqual([second.run_id, first.run_id])
  })
})

describe('처음부터 끝까지', () => {
  it('추출 확인 → 요구사항 확인 → 최종 승인 → 완료, PDF는 승인 뒤에만', async () => {
    let run = await startAndWait()
    const extraction = await getView(run.run_id, 'extraction')
    expect(extraction.items.length).toBe(6)

    // UI-02: fail 블록(B5)은 제외, review 블록(B3)은 확인
    run = await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: { kind: 'extraction', confirmed: true, excluded_blocks: [{ block_id: 'B5', reason: null }] },
    })
    expect(run).toMatchObject({ status: 'analysing', revision: 1 })

    later()
    run = await getRun(run.run_id)
    expect(run.interrupt?.kind).toBe('requirements')

    // UI-03: REQ-03을 두 문장으로 나눈다 → 두 번째 조각은 새 ID
    run = await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: {
        kind: 'requirements',
        answers: [{ req_id: 'REQ-03', action: 'split', texts: ['입고 내역을 조회한다', '품목분류로 거른다'] }],
      },
    })
    expect(run.status).toBe('designing')
    const requirements = await getView(run.run_id, 'requirements')
    expect(requirements.items.map((r) => r.id)).toEqual(['REQ-01', 'REQ-02', 'REQ-03', 'REQ-05', 'REQ-04'])

    later()
    run = await getRun(run.run_id)
    expect(run.interrupt?.kind).toBe('review')

    // 승인 전: 초안 파일 이름, PDF는 409
    const draft = await downloadArtifact(run.run_id, 'ddl', 'sql', run.revision)
    expect(draft.fileName).toBe('specton-ddl-r1-draft.sql')
    const notReady = await rejection(downloadArtifact(run.run_id, 'erd', 'pdf', run.revision))
    expect(notReady.code).toBe('ARTIFACT_NOT_READY')

    // UI-06 승인
    run = await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: { kind: 'review', decision: 'approve', feedback: '' },
    })
    expect(run.status).toBe('exporting')
    later()
    expect((await getRun(run.run_id)).status).toBe('completed')

    const pdf = await downloadArtifact(run.run_id, 'erd', 'pdf', 1)
    expect(pdf.fileName).toBe('specton-erd-r1.pdf')
  })

  it('수정 요청하면 revision이 올라가고 다시 최종 검토에서 멈춘다', async () => {
    let run = await startAndWait('quick.csv')
    expect(run.interrupt?.kind).toBe('review')
    run = await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: { kind: 'review', decision: 'revise', feedback: '창고 관리 기능을 추가해 주세요.' },
    })
    expect(run).toMatchObject({ status: 'designing', revision: 2 })
    later()
    expect((await getRun(run.run_id)).status).toBe('awaiting_review')
  })

  it('보류하면 같은 확인 요청으로 계속 기다린다', async () => {
    const run = await startAndWait('quick.csv')
    const held = await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: { kind: 'review', decision: 'hold', feedback: '' },
    })
    expect(held.interrupt?.interrupt_id).toBe(run.interrupt!.interrupt_id)
  })
})

describe('확인 답변 오류', () => {
  it('fail 블록을 제외하지 않으면 422, 메시지는 블록 ID로 시작', async () => {
    const run = await startAndWait()
    const err = await rejection(
      resumeRun(run.run_id, {
        interrupt_id: run.interrupt!.interrupt_id,
        expected_revision: run.revision,
        response: { kind: 'extraction', confirmed: true, excluded_blocks: [] },
      }),
    )
    expect(err.code).toBe('INVALID_RESPONSE')
    expect(errorMessage(err)).toMatch(/^B5: /)
  })

  it('review 블록을 사유 없이 제외하면 422', async () => {
    const run = await startAndWait()
    const err = await rejection(
      resumeRun(run.run_id, {
        interrupt_id: run.interrupt!.interrupt_id,
        expected_revision: run.revision,
        response: {
          kind: 'extraction',
          confirmed: true,
          excluded_blocks: [
            { block_id: 'B5', reason: null },
            { block_id: 'B3', reason: '  ' },
          ],
        },
      }),
    )
    expect(errorMessage(err)).toMatch(/^B3: /)
  })

  it('split 문장이 하나뿐이거나 빈 문장이면 422 (#136)', async () => {
    let run = await startAndWait()
    run = await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: { kind: 'extraction', confirmed: true, excluded_blocks: [{ block_id: 'B5', reason: null }] },
    })
    later()
    run = await getRun(run.run_id)
    for (const texts of [['하나'], ['하나', ' ']]) {
      const err = await rejection(
        resumeRun(run.run_id, {
          interrupt_id: run.interrupt!.interrupt_id,
          expected_revision: run.revision,
          response: { kind: 'requirements', answers: [{ req_id: 'REQ-01', action: 'split', texts }] },
        }),
      )
      expect(errorMessage(err)).toMatch(/^REQ-01: /)
    }
    // 거절된 뒤에도 같은 확인 요청에 다시 답할 수 있다
    expect((await getRun(run.run_id)).status).toBe('awaiting_requirements')
  })

  it('같은 답을 두 번 보내면 409 INTERRUPT_STALE → 새로고침 안내', async () => {
    const run = await startAndWait('quick.csv')
    const request = {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: { kind: 'review' as const, decision: 'approve' as const, feedback: '' },
    }
    await resumeRun(run.run_id, request)
    const err = await rejection(resumeRun(run.run_id, request))
    expect([err.status, err.code]).toEqual([409, 'INTERRUPT_STALE'])
    expect(nextAction(err.code)).toBe('refresh')
  })

  it('다른 revision 기준이면 409 RUN_REVISION_CONFLICT', async () => {
    const run = await startAndWait()
    const err = await rejection(
      resumeRun(run.run_id, {
        interrupt_id: run.interrupt!.interrupt_id,
        expected_revision: 7,
        response: { kind: 'extraction', confirmed: false, excluded_blocks: [] },
      }),
    )
    expect(err.code).toBe('RUN_REVISION_CONFLICT')
  })
})

describe('취소 (#96, ADR-0012)', () => {
  it('사람 확인 대기 중이면 바로 cancelled', async () => {
    const run = await startAndWait()
    expect((await cancelRun(run.run_id, run.revision)).status).toBe('cancelled')
  })

  it('실행 중이면 cancel_requested였다가 시간이 지나면 cancelled', async () => {
    const created = await createRun(csv(), 'inventory')
    later(15) // parsing 중
    expect((await getRun(created.run_id)).status).toBe('parsing')

    const requested = await cancelRun(created.run_id, 0)
    expect(requested.status).toBe('cancel_requested')
    later(50)
    expect((await getRun(created.run_id)).status).toBe('cancel_requested')
    later(100)
    expect((await getRun(created.run_id)).status).toBe('cancelled')
  })

  it('끝난 실행은 409', async () => {
    const run = await startAndWait()
    await cancelRun(run.run_id, run.revision)
    const err = await rejection(cancelRun(run.run_id, run.revision))
    expect(err.status).toBe(409)
  })
})

describe('실패 흐름', () => {
  it('문서를 읽지 못하면 failed, SSE error 이벤트에 자세히 보기 문장', async () => {
    const run = await startAndWait('unreadable.xlsx')
    expect(run.status).toBe('failed')
    expect(run.error?.code).toBe('EXTRACTION_FAILED')
    const errorEvent = backend.eventsOf(run.run_id).find((e) => e.event === 'error')
    expect(errorEvent?.data.payload?.detail).toContain('요구사항 ID')
  })

  it('확인할 것이 없으면 분석 확인 생략 안내를 남긴다', async () => {
    const run = await startAndWait('quick.csv')
    const messages = backend.eventsOf(run.run_id).map((e) => e.data.message)
    expect(messages).toContain('확인할 항목이 없어 분석 확인을 생략했습니다')
  })

  it('없는 실행은 404 RUN_NOT_FOUND', async () => {
    const err = await rejection(getRun('00000000-0000-0000-0000-000000000000'))
    expect([err.status, err.code]).toEqual([404, 'RUN_NOT_FOUND'])
  })

  it('아직 결과가 없는 section은 빈 목록, 미래 revision은 409', async () => {
    const created = await createRun(csv(), 'inventory')
    expect((await getView(created.run_id, 'design')).items).toEqual([])
    const err = await rejection(getView(created.run_id, 'design', 3))
    expect(err.code).toBe('RUN_REVISION_CONFLICT')
  })

  it('서버에 닿지 못하면 NETWORK, 다시 시도 안내', async () => {
    server.use(http.get('*/runs/:id', () => HttpResponse.error()))
    const err = await rejection(getRun('any'))
    expect(err.code).toBe('NETWORK')
    expect(errorMessage(err)).toContain('서버에 연결하지 못했습니다')
    expect(nextAction(err.code)).toBe('retry')
  })
})

describe('세션 쿠키 전달', () => {
  it('API 출처가 달라도 HTTP 세션 전송을 요청한다', async () => {
    server.use(http.get('http://specton.test/runs', ({ request }) => {
      expect(request.credentials).toBe('include')
      return HttpResponse.json([])
    }))
    expect(await listRuns()).toEqual([])
  })
})
