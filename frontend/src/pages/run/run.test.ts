// 4단계: 실행 상태 → 화면, 이벤트(SSE) 읽기, 따라가기(재연결) 테스트. 진짜 서버 없이 mock으로 돈다.
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { cancelRun, createRun, getRun, resumeRun, setApiBaseUrl } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import { parseFrame, readEvents } from '../../api/events.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import { createMockBackend } from '../../mocks/backend.ts'
import { followRun, type Connection } from './followRun.ts'
import {
  SKIPPED_REQUIREMENTS_MESSAGE,
  canCancel,
  failureOf,
  progressIndex,
  recentMessages,
  requirementsCheckSkipped,
  screenFor,
} from './screens.ts'

const event = (id: number, name: SseEvent['event'], message: string, extra: Partial<SseEvent['data']> = {}): SseEvent => ({
  id,
  event: name,
  data: { run_id: 'r1', revision: 0, stage: null, message, ...extra },
})

describe('screenFor: 상태 → 화면 (docs/09)', () => {
  it.each([
    ['queued', 'UI-04'],
    ['parsing', 'UI-04'],
    ['awaiting_input', 'UI-02'],
    ['analysing', 'UI-04'],
    ['awaiting_requirements', 'UI-03'],
    ['designing', 'UI-04'],
    ['reviewing', 'UI-04'],
    ['awaiting_review', 'UI-06'],
    ['exporting', 'UI-07'],
    ['completed', 'UI-07'],
    ['failed', 'UI-04'],
    ['cancel_requested', 'UI-04'],
    ['cancelled', 'UI-04'],
  ] as const)('%s → %s', (status, screen) => {
    expect(screenFor(status)).toBe(screen)
  })

  it('취소 버튼은 진행·대기 중에만', () => {
    expect(canCancel('designing')).toBe(true)
    expect(canCancel('awaiting_input')).toBe(true)
    expect(canCancel('cancel_requested')).toBe(false)
    expect(canCancel('completed')).toBe(false)
  })

  it('진행 단계 위치', () => {
    expect(progressIndex(null)).toBe(-1)
    expect(progressIndex('parsing')).toBe(0)
    expect(progressIndex('reviewing')).toBe(4)
    expect(progressIndex('review')).toBe(5)
  })
})

describe('이벤트로 정하는 표시', () => {
  it('분석 확인 생략은 designing 단계의 생략 문구로 안다', () => {
    const skipped = event(3, 'status', SKIPPED_REQUIREMENTS_MESSAGE, { stage: 'designing' })
    expect(requirementsCheckSkipped([skipped])).toBe(true)
    expect(requirementsCheckSkipped([event(3, 'status', '설계 모델을 만들고 있습니다', { stage: 'designing' })])).toBe(false)
  })

  it('실패 안내의 자세히 보기는 error 이벤트에서 가져온다', () => {
    const err = event(4, 'error', '표를 찾지 못했어요', {
      payload: { code: 'EXTRACTION_FAILED', retryable: false, detail: '찾은 칸 이름: 번호' },
    })
    expect(failureOf({ code: 'EXTRACTION_FAILED', message: '표를 찾지 못했어요', retryable: false }, [err])).toEqual({
      code: 'EXTRACTION_FAILED',
      message: '표를 찾지 못했어요',
      retryable: false,
      detail: '찾은 칸 이름: 번호',
    })
    expect(failureOf(null, [])).toBeNull()
  })

  it('진행 기록은 같은 문장이 이어지면 하나만', () => {
    const events = [event(1, 'status', 'a'), event(2, 'status', 'a'), event(3, 'status', 'b')]
    expect(recentMessages(events)).toEqual(['a', 'b'])
  })
})

describe('parseFrame: SSE 한 덩어리', () => {
  it('id·event·data를 읽는다', () => {
    const frame = 'id: 7\nevent: interrupt\ndata: {"run_id":"r","revision":1,"message":"확인","payload":{"kind":"extraction"}}'
    expect(parseFrame(frame)).toEqual({
      id: 7,
      event: 'interrupt',
      data: { run_id: 'r', revision: 1, message: '확인', payload: { kind: 'extraction' } },
    })
  })

  it.each([': keep-alive', 'id: x\nevent: status\ndata: {}', 'id: 1\nevent: unknown\ndata: {}', 'id: 1\nevent: status\ndata: {깨짐'])(
    '무시: %s',
    (frame) => {
      expect(parseFrame(frame)).toBeNull()
    },
  )
})

// ── mock 서버와 함께 ─────────────────────────────────────

const server = setupServer()
beforeAll(() => {
  setApiBaseUrl('http://specton.test')
  server.listen({ onUnhandledRequest: 'error' })
})
afterAll(() => server.close())
beforeEach(() => {
  // 실제 시간으로 빠르게: 한 단계 5ms, 이벤트 확인 5ms
  server.resetHandlers(...createMockBackend({ stepMs: 5, cancelMs: 20, pollMs: 5 }).handlers)
})

const upload = (name = '요구사항.csv') => createRun(new File(['내용'], name), 'inventory')

async function waitFor(check: () => boolean, ms = 2000) {
  const end = Date.now() + ms
  while (!check()) {
    if (Date.now() > end) throw new Error('기다리던 상태가 오지 않았습니다')
    await new Promise((r) => setTimeout(r, 5))
  }
}

/** 실행을 끝(또는 timeout)까지 따라가며 받은 것을 모은다 */
function follow(runId: string) {
  const controller = new AbortController()
  const got = { statuses: [] as RunStatus[], events: [] as SseEvent[], connections: [] as Connection[], resets: 0 }
  const done = followRun(
    runId,
    {
      onStatus: (s) => got.statuses.push(s),
      onEvent: (e) => got.events.push(e),
      onReset: () => {
        got.resets += 1
        got.events.length = 0
      },
      onConnection: (c) => got.connections.push(c),
    },
    { signal: controller.signal, retryMs: 5, refreshMs: 1 },
  )
  const last = () => got.statuses.slice(-1)[0]?.status
  return { got, done, last, stop: () => controller.abort() }
}

describe('mock /events 스트림', () => {
  it('지난 이벤트를 보내고 새 이벤트를 이어 보낸다', async () => {
    const run = await upload()
    const controller = new AbortController()
    const events: SseEvent[] = []
    const reading = readEvents(run.run_id, { after: 0, signal: controller.signal, onEvent: (e) => events.push(e) })
    await waitFor(() => events.some((e) => e.event === 'interrupt'))
    controller.abort()
    await reading
    expect(events.map((e) => e.id)).toEqual(events.map((_, i) => i + 1)) // 1부터 빠짐없이
    expect(events[0].data.message).toBe('실행을 접수했습니다')
    expect(events.slice(-1)[0]?.data.payload).toMatchObject({ kind: 'extraction' })
  })

  it('Last-Event-ID 다음부터 다시 받는다', async () => {
    const run = await upload()
    await waitFor(() => false, 50).catch(() => {}) // 몇 단계 지나가게
    const controller = new AbortController()
    const events: SseEvent[] = []
    const reading = readEvents(run.run_id, { after: 2, signal: controller.signal, onEvent: (e) => events.push(e) })
    await waitFor(() => events.length > 0)
    controller.abort()
    await reading
    expect(events[0].id).toBe(3)
  })

  it('아직 없는 이벤트 ID는 409 EVENT_REPLAY_EXPIRED', async () => {
    const run = await upload()
    const error = await readEvents(run.run_id, { after: 999, onEvent: () => {} }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('EVENT_REPLAY_EXPIRED')
  })

  it('끝난 실행은 남은 이벤트를 보낸 뒤 스트림을 닫는다', async () => {
    const run = await upload('대기_slow-queue.csv')
    await cancelRun(run.run_id, run.revision) // 대기 중이면 바로 cancelled
    const events: SseEvent[] = []
    await readEvents(run.run_id, { after: 0, onEvent: (e) => events.push(e) }) // 스스로 끝나야 한다
    expect(events.slice(-1)[0]?.event).toBe('cancelled')
  })
})

describe('followRun: 실행 따라가기', () => {
  it('업로드 뒤 추출 확인(UI-02)까지 상태가 따라온다', async () => {
    const run = await upload()
    const f = follow(run.run_id)
    // 처음 조회만으로도 awaiting_input일 수 있어(단계가 5ms) 이벤트 연결까지 기다린다
    await waitFor(() => f.last() === 'awaiting_input' && f.got.events.some((e) => e.event === 'interrupt'))
    f.stop()
    await f.done
    expect(screenFor(f.last()!)).toBe('UI-02')
    expect(f.got.connections).toContain('live')
  })

  it('확인할 것이 없으면 UI-02·03을 건너뛰고 최종 검토까지, 생략 표시가 남는다', async () => {
    const run = await upload('재고_quick.csv')
    const f = follow(run.run_id)
    await waitFor(() => f.last() === 'awaiting_review')
    f.stop()
    await f.done
    expect(f.got.statuses.map((s) => s.status)).not.toContain('awaiting_requirements')
    await waitFor(() => requirementsCheckSkipped(f.got.events))
  })

  it('답을 보내면 다음 확인 화면으로 넘어간다', async () => {
    const run = await upload()
    const f = follow(run.run_id)
    await waitFor(() => f.last() === 'awaiting_input')
    const waiting = await getRun(run.run_id)
    await resumeRun(run.run_id, {
      interrupt_id: waiting.interrupt!.interrupt_id,
      expected_revision: waiting.revision,
      response: { kind: 'extraction', confirmed: true, excluded_blocks: [{ block_id: 'B5', reason: null }] },
    })
    await waitFor(() => f.last() === 'awaiting_requirements')
    f.stop()
    await f.done
    expect(screenFor(f.last()!)).toBe('UI-03')
  })

  it('문서를 못 읽으면 실패로 끝나고, 자세히 보기 문장을 얻는다', async () => {
    const run = await upload('표없음_unreadable.csv')
    const f = follow(run.run_id)
    await f.done // 끝난 실행이면 스스로 돌아온다
    expect(f.last()).toBe('failed')
    expect(f.got.connections.slice(-1)[0]).toBe('closed')
    const failure = failureOf(f.got.statuses.slice(-1)[0]!.error, f.got.events)
    expect(failure?.code).toBe('EXTRACTION_FAILED')
    expect(failure?.detail).toContain('찾은 칸 이름')
  })

  it('스트림이 끊기면 마지막 이벤트 다음부터 다시 연결한다', async () => {
    const run = await upload()
    const seen: (string | null)[] = []
    let first = true
    server.use(
      http.get('*/runs/:id/events', ({ request }) => {
        seen.push(request.headers.get('Last-Event-ID'))
        if (!first) return // 두 번째부터는 원래 mock으로
        first = false
        // 첫 이벤트 하나만 보내고 닫는다 (연결 끊김 흉내)
        const frame = `id: 1\nevent: status\ndata: ${JSON.stringify({ run_id: run.run_id, revision: 0, message: '실행을 접수했습니다' })}\n\n`
        return new HttpResponse(frame, { headers: { 'Content-Type': 'text/event-stream' } })
      }),
    )
    const f = follow(run.run_id)
    await waitFor(() => f.got.events.some((e) => e.event === 'interrupt')) // 이벤트는 다시 연결해야만 온다
    f.stop()
    await f.done
    expect(seen.slice(0, 2)).toEqual([null, '1'])
    expect(f.got.connections).toContain('retrying')
    expect(f.got.events.map((e) => e.id)).toEqual(f.got.events.map((_, i) => i + 1)) // 겹치지도 빠지지도 않는다
  })

  it('409 EVENT_REPLAY_EXPIRED면 처음부터 다시 받는다', async () => {
    const run = await upload()
    let answered409 = false
    server.use(
      http.get('*/runs/:id/events', ({ request }) => {
        if (answered409 || request.headers.get('Last-Event-ID') !== null) return
        answered409 = true
        return HttpResponse.json(
          { code: 'EVENT_REPLAY_EXPIRED', message: '다시 연결하세요', run_id: run.run_id, retryable: false },
          { status: 409 },
        )
      }),
    )
    const f = follow(run.run_id)
    await waitFor(() => f.last() === 'awaiting_input' && f.got.events.length > 0)
    f.stop()
    await f.done
    expect(f.got.resets).toBe(1)
    expect(f.got.events[0].id).toBe(1)
  })

  it('없는 실행은 404를 던진다', async () => {
    const f = follow('없는-실행')
    const error = await f.done.catch((e: unknown) => e)
    expect((error as ApiError).status).toBe(404)
  })
})
