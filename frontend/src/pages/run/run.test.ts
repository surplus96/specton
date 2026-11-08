// 4단계: 실행 상태 → 화면, 이벤트(SSE) 받기, 따라가기 테스트. 진짜 서버 없이 mock으로 돈다.
// Node에는 EventSource가 없어, 브라우저처럼 동작하는 대역(TestEventSource)을 아래에 둔다.
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { cancelRun, createRun, eventsUrl, getRun, resumeRun, setApiBaseUrl } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import { watchRun, type EventSourceFactory } from '../../api/events.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import { createMockBackend } from '../../mocks/backend.ts'
import { followRun, type Connection } from './followRun.ts'
import {
  SKIPPED_REQUIREMENTS_MESSAGE,
  canCancel,
  displayStage,
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
    ['exporting', 'UI-04'],
    ['completed', 'UI-07'],
    ['failed', 'UI-04'],
    ['cancel_requested', 'UI-04'],
    ['cancelled', 'UI-04'],
  ] as const)('%s → %s', (status, screen) => {
    expect(screenFor(status)).toBe(screen)
  })

  it('확인 화면은 status보다 interrupt.kind로 고른다 (강의 09)', () => {
    expect(screenFor('awaiting_input', 'extraction')).toBe('UI-02')
    expect(screenFor('awaiting_input', 'requirements')).toBe('UI-03')
    expect(screenFor('awaiting_review', 'review')).toBe('UI-06')
    expect(screenFor('cancelled', 'extraction')).toBe('UI-04') // 끝난 실행은 확인 화면이 아니다
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

  it('실패해 stage가 비면 마지막 진행 이벤트의 단계를 쓴다 (실제 서버 확인에서 찾음)', () => {
    // 실제 서버는 실패하면 run.stage를 비우고 error 이벤트에 stage: 'failed'를 남긴다.
    // 이때 첫 단계(문서 읽기)가 아니라 실패한 단계(요구사항 분석)에 실패 표시가 가야 한다.
    const events = [
      event(1, 'status', '문서를 읽고 있습니다', { stage: 'parsing' }),
      event(3, 'status', '추출 결과 확인을 기다립니다', { stage: 'awaiting_input' }),
      event(5, 'status', '답변을 받아 다시 진행합니다', { stage: 'analysing' }),
      event(6, 'error', '모델을 호출하지 못했습니다.', { stage: 'failed' }),
    ]
    expect(displayStage(null, events)).toBe('analysing')
    expect(progressIndex(displayStage(null, events))).toBe(1)
    expect(displayStage('designing', events)).toBe('designing') // 서버 stage가 있으면 그대로
    expect(displayStage(null, [])).toBeNull() // 대기 중(queued)은 그대로 -1
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

// ── 브라우저 EventSource 대역 ──────────────────────────────
// 브라우저와 같게: 이름 있는 이벤트를 MessageEvent로, 스트림이 끝나면 Last-Event-ID를 붙여 다시 연결,
// 200이 아닌 응답(404·409)이면 연결을 닫고(readyState 2) error를 보낸다.

class TestEventSource extends EventTarget {
  static opened: { url: string; lastEventId: string | null }[] = []
  readyState = 0
  private lastEventId = ''
  private reader: ReadableStreamDefaultReader<string> | null = null
  readonly url: string

  constructor(url: string) {
    super()
    this.url = url
    void this.connect()
  }

  close() {
    this.readyState = 2
    void this.reader?.cancel().catch(() => {})
  }

  private async connect() {
    const lastEventId = this.lastEventId || null
    TestEventSource.opened.push({ url: this.url, lastEventId })
    let res: Response
    try {
      res = await fetch(this.url, { headers: lastEventId ? { 'Last-Event-ID': lastEventId } : {} })
    } catch {
      return this.lose()
    }
    if (this.readyState === 2) return
    if (!res.ok || !res.body) {
      this.readyState = 2
      this.dispatchEvent(new Event('error'))
      return
    }
    this.readyState = 1
    this.dispatchEvent(new Event('open'))
    this.reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
    let buffer = ''
    try {
      for (;;) {
        const { done, value } = await this.reader.read()
        if (done) break
        buffer += value
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''
        for (const frame of frames) this.deliver(frame)
      }
    } catch {
      // 끊김
    }
    this.lose()
  }

  private deliver(frame: string) {
    let name = 'message'
    const data: string[] = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('id: ')) this.lastEventId = line.slice(4)
      else if (line.startsWith('event: ')) name = line.slice(7)
      else if (line.startsWith('data: ')) data.push(line.slice(6))
    }
    if (data.length && this.readyState !== 2) {
      this.dispatchEvent(new MessageEvent(name, { data: data.join('\n'), lastEventId: this.lastEventId }))
    }
  }

  /** 스트림이 끝났다: 브라우저처럼 다시 연결한다 (닫지 않았다면) */
  private lose() {
    if (this.readyState === 2) return
    this.readyState = 0
    this.dispatchEvent(new Event('error'))
    setTimeout(() => {
      if (this.readyState !== 2) void this.connect()
    }, 5)
  }
}

const openTest: EventSourceFactory = (url) => new TestEventSource(url) as unknown as EventSource

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
  TestEventSource.opened = []
})

const upload = (name = '요구사항.csv') => createRun(new File(['내용'], name), 'inventory')

async function waitFor(check: () => boolean, ms = 2000) {
  const end = Date.now() + ms
  while (!check()) {
    if (Date.now() > end) throw new Error('기다리던 상태가 오지 않았습니다')
    await new Promise((r) => setTimeout(r, 5))
  }
}

const frame = (runId: string, id: number, message: string) =>
  `id: ${id}\nevent: status\ndata: ${JSON.stringify({ run_id: runId, revision: 0, message })}\n\n`

describe('watchRun: 이벤트 받기', () => {
  it('이름 있는 이벤트를 받고, 끝 이벤트에서 스스로 닫는다', async () => {
    const run = await upload('대기_slow-queue.csv')
    const events: SseEvent[] = []
    const closed: string[] = []
    watchRun(run.run_id, { onEvent: (e) => events.push(e), onClosed: (r) => closed.push(r) }, openTest)
    await waitFor(() => events.length > 0)
    await cancelRun(run.run_id, run.revision) // 대기 중이면 바로 cancelled
    await waitFor(() => closed.length > 0)
    expect(closed).toEqual(['finished'])
    expect(events.slice(-1)[0].event).toBe('cancelled')
    expect(events.map((e) => e.id)).toEqual(events.map((_, i) => i + 1))
    expect(TestEventSource.opened).toHaveLength(1) // 서버가 닫은 뒤 다시 붙지 않았다
  })

  it('서버 error 이벤트는 실패 안내 이벤트로 받고 닫는다', async () => {
    const run = await upload('표없음_unreadable.csv')
    const events: SseEvent[] = []
    const closed: string[] = []
    watchRun(run.run_id, { onEvent: (e) => events.push(e), onClosed: (r) => closed.push(r) }, openTest)
    await waitFor(() => closed.length > 0)
    expect(closed).toEqual(['finished'])
    expect(events.slice(-1)[0]).toMatchObject({ event: 'error', data: { payload: { code: 'EXTRACTION_FAILED' } } })
  })

  it('연결이 거절되면(409 등) lost로 닫힌다', async () => {
    server.use(
      http.get('*/runs/:id/events', () =>
        HttpResponse.json({ code: 'EVENT_REPLAY_EXPIRED', message: '다시', run_id: null, retryable: false }, { status: 409 }),
      ),
    )
    const run = await upload()
    const closed: string[] = []
    watchRun(run.run_id, { onEvent: () => {}, onClosed: (r) => closed.push(r) }, openTest)
    await waitFor(() => closed.length > 0)
    expect(closed).toEqual(['lost'])
  })

  it('돌려준 함수로 닫으면 onClosed를 부르지 않는다', async () => {
    const run = await upload()
    const closed: string[] = []
    const close = watchRun(run.run_id, { onEvent: () => {}, onClosed: (r) => closed.push(r) }, openTest)
    close()
    await new Promise((r) => setTimeout(r, 30))
    expect(closed).toEqual([])
  })
})

/** 실행을 끝(또는 stop)까지 따라가며 받은 것을 모은다 */
function follow(runId: string) {
  const controller = new AbortController()
  const got = { statuses: [] as RunStatus[], events: [] as SseEvent[], connections: [] as Connection[] }
  const done = followRun(
    runId,
    {
      onStatus: (s) => got.statuses.push(s),
      onEvent: (e) => got.events.push(e),
      onConnection: (c) => got.connections.push(c),
    },
    { signal: controller.signal, retryMs: 5, refreshMs: 1, open: openTest },
  )
  const last = () => got.statuses.slice(-1)[0]?.status
  const ids = () => got.events.map((e) => e.id)
  return { got, done, last, ids, stop: () => controller.abort() }
}

const inOrder = (ids: number[]) => ids.every((id, i) => id === i + 1)

describe('followRun: 실행 따라가기', () => {
  it('업로드 뒤 추출 확인(UI-02)까지 상태가 따라온다', async () => {
    const run = await upload()
    const f = follow(run.run_id)
    await waitFor(() => f.last() === 'awaiting_input' && f.got.events.some((e) => e.event === 'interrupt'))
    f.stop()
    await f.done
    expect(screenFor(f.last()!)).toBe('UI-02')
    expect(f.got.connections).toContain('live')
  })

  it('확인할 것이 없으면 UI-02·03을 건너뛰고 최종 검토까지, 생략 표시가 남는다', async () => {
    const run = await upload('재고_quick.csv')
    const f = follow(run.run_id)
    await waitFor(() => f.last() === 'awaiting_review' && requirementsCheckSkipped(f.got.events))
    f.stop()
    await f.done
    expect(f.got.statuses.map((s) => s.status)).not.toContain('awaiting_requirements')
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

  it('문서를 못 읽으면 실패로 끝나고 스스로 돌아온다. 자세히 보기 문장을 얻는다', async () => {
    const run = await upload('표없음_unreadable.csv')
    const f = follow(run.run_id)
    await f.done
    expect(f.last()).toBe('failed')
    expect(f.got.connections.slice(-1)[0]).toBe('closed')
    const failure = failureOf(f.got.statuses.slice(-1)[0].error, f.got.events)
    expect(failure?.code).toBe('EXTRACTION_FAILED')
    expect(failure?.detail).toContain('찾은 칸 이름')
  })

  it('스트림이 끊기면 브라우저가 Last-Event-ID로 다시 붙고, 이벤트는 겹치지 않는다', async () => {
    const run = await upload()
    let first = true
    server.use(
      http.get('*/runs/:id/events', () => {
        if (!first) return // 두 번째부터는 원래 mock으로
        first = false
        return new HttpResponse(frame(run.run_id, 1, '실행을 접수했습니다'), {
          headers: { 'Content-Type': 'text/event-stream' },
        })
      }),
    )
    const f = follow(run.run_id)
    await waitFor(() => f.got.events.some((e) => e.event === 'interrupt'))
    f.stop()
    await f.done
    expect(TestEventSource.opened.map((o) => o.lastEventId).slice(0, 2)).toEqual([null, '1'])
    expect(inOrder(f.ids())).toBe(true)
  })

  it('연결이 거절되면(409 EVENT_REPLAY_EXPIRED) 상태를 다시 읽고 새로 연다. 다시 받은 이벤트는 한 번만', async () => {
    const run = await upload()
    let calls = 0
    server.use(
      http.get('*/runs/:id/events', ({ request }) => {
        calls += 1
        if (calls === 1) {
          // 이벤트 둘을 보내고 끊는다 → 브라우저가 Last-Event-ID: 2로 다시 붙는다
          const body = frame(run.run_id, 1, '실행을 접수했습니다') + frame(run.run_id, 2, '문서를 읽고 있습니다')
          return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } })
        }
        if (calls === 2 && request.headers.get('Last-Event-ID') === '2') {
          return HttpResponse.json(
            { code: 'EVENT_REPLAY_EXPIRED', message: '다시 연결하세요', run_id: run.run_id, retryable: false },
            { status: 409 },
          )
        }
        return // 세 번째(새 연결, 처음부터)는 원래 mock
      }),
    )
    const f = follow(run.run_id)
    await waitFor(() => f.got.events.some((e) => e.event === 'interrupt'))
    f.stop()
    await f.done
    expect(TestEventSource.opened.map((o) => o.lastEventId).slice(0, 3)).toEqual([null, '2', null])
    expect(f.got.connections).toContain('retrying')
    expect(inOrder(f.ids())).toBe(true) // 처음부터 다시 받았지만 1·2는 한 번만
  })

  it('없는 실행은 404로 끝난다', async () => {
    const f = follow('없는-실행')
    const error = await f.done.catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
  })
})

describe('mock /events 스트림 (백엔드와 같은 규칙)', () => {
  it('아직 없는 이벤트 ID는 409 EVENT_REPLAY_EXPIRED', async () => {
    const run = await upload()
    const res = await fetch(eventsUrl(run.run_id), { headers: { 'Last-Event-ID': '999' } })
    expect(res.status).toBe(409)
    expect((await res.json()).code).toBe('EVENT_REPLAY_EXPIRED')
  })
})
