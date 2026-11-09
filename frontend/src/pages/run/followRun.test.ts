import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getRun } from '../../api/client.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import { followRun, type Connection } from './followRun.ts'

vi.mock('../../api/client.ts', () => ({
  getRun: vi.fn(),
  eventsUrl: (runId: string) => `/runs/${runId}/events`,
}))

class ControlledSource extends EventTarget {
  readyState = 1

  close() {
    this.readyState = 2
  }

  emit(name: SseEvent['event'], id: number) {
    this.dispatchEvent(new MessageEvent(name, {
      lastEventId: String(id),
      data: JSON.stringify({ run_id: 'run-1', revision: 1, message: name }),
    }))
  }

  lose() {
    this.readyState = 2
    this.dispatchEvent(new Event('error'))
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const status = (state: RunStatus['status']): RunStatus => ({
  run_id: 'run-1', status: state, revision: 1,
})

function start() {
  const controller = new AbortController()
  const sources: ControlledSource[] = []
  const statuses: RunStatus['status'][] = []
  const connections: Connection[] = []
  const follower = followRun('run-1', {
    onStatus: (s) => statuses.push(s.status),
    onEvent: () => {},
    onConnection: (c) => connections.push(c),
  }, {
    signal: controller.signal,
    refreshMs: 1,
    retryMs: 5,
    open: () => {
      const source = new ControlledSource()
      sources.push(source)
      return source as unknown as EventSource
    },
  })
  return { ...follower, controller, sources, statuses, connections }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(getRun).mockReset().mockResolvedValue(status('generating'))
})
afterEach(() => vi.useRealTimers())

describe('상태 조회 응답 순서', () => {
  it.each(['completed', 'failed', 'cancelled'] as const)('%s 뒤 늦은 생성 중 응답을 버린다', async (terminal) => {
    const delayed = deferred<RunStatus>()
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockReturnValueOnce(delayed.promise)
      .mockResolvedValueOnce(status(terminal))
    const f = start()
    await vi.advanceTimersByTimeAsync(0)
    f.sources[0].emit('status', 1)
    await vi.advanceTimersByTimeAsync(1)
    f.sources[0].emit(terminal === 'failed' ? 'error' : terminal, 2)
    await f.done
    delayed.resolve(status('generating'))
    await vi.advanceTimersByTimeAsync(0)
    expect(f.statuses).toEqual(['generating', terminal])
    expect(f.connections.slice(-1)[0]).toBe('closed')
    expect(f.sources[0].readyState).toBe(2)
    await f.refresh()
    expect(getRun).toHaveBeenCalledTimes(3)
  })

  it('같은 revision의 최종 검토 화면을 오래된 SSE 조회가 되돌리지 못한다', async () => {
    const delayed = deferred<RunStatus>()
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockReturnValueOnce(delayed.promise)
      .mockResolvedValueOnce(status('awaiting_review'))
    const f = start()
    await vi.advanceTimersByTimeAsync(0)
    f.sources[0].emit('status', 1)
    await vi.advanceTimersByTimeAsync(1)
    await f.refresh()
    delayed.resolve(status('generating'))
    await vi.advanceTimersByTimeAsync(0)
    expect(f.statuses).toEqual(['generating', 'awaiting_review'])
    f.controller.abort()
    await f.done
  })

  it('확인·취소 뒤 수동 조회도 최신 SSE 조회를 덮어쓰지 못한다', async () => {
    const delayed = deferred<RunStatus>()
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockReturnValueOnce(delayed.promise)
      .mockResolvedValueOnce(status('completed'))
    const f = start()
    await vi.advanceTimersByTimeAsync(0)
    const manual = f.refresh()
    f.sources[0].emit('completed', 1)
    await f.done
    delayed.resolve(status('generating'))
    await manual
    expect(f.statuses).toEqual(['generating', 'completed'])
  })

  it('화면을 떠난 뒤 초기 조회 응답은 반영하지 않고 SSE도 열지 않는다', async () => {
    const delayed = deferred<RunStatus>()
    vi.mocked(getRun).mockReturnValueOnce(delayed.promise)
    const f = start()
    f.controller.abort()
    await f.done
    delayed.resolve(status('generating'))
    await vi.advanceTimersByTimeAsync(0)
    expect(f.statuses).toEqual([])
    expect(f.sources).toEqual([])
  })

  it('끊김 뒤 조회와 수동 조회가 겹쳐도 최신 상태를 받고 SSE를 다시 연다', async () => {
    const delayed = deferred<RunStatus>()
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockReturnValueOnce(delayed.promise)
      .mockResolvedValueOnce(status('awaiting_review'))
    const f = start()
    await vi.advanceTimersByTimeAsync(0)
    f.sources[0].lose()
    await f.refresh()
    delayed.resolve(status('generating'))
    await vi.advanceTimersByTimeAsync(5)
    expect(f.statuses).toEqual(['generating', 'awaiting_review'])
    expect(f.sources).toHaveLength(2)
    f.controller.abort()
    await f.done
  })

  it('최신 수동 조회가 끝나면 끊김 뒤 이전 조회를 기다리지 않고 종료한다', async () => {
    const delayed = deferred<RunStatus>()
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockReturnValueOnce(delayed.promise)
      .mockResolvedValueOnce(status('completed'))
    const f = start()
    await vi.advanceTimersByTimeAsync(0)
    f.sources[0].lose()
    await f.refresh()
    await f.done
    delayed.resolve(status('generating'))
    await vi.advanceTimersByTimeAsync(0)
    expect(f.statuses).toEqual(['generating', 'completed'])
    expect(f.sources).toHaveLength(1)
  })

  it('최종 이벤트 전에 예약한 조회는 종료 조회를 대체하지 않는다', async () => {
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockResolvedValueOnce(status('completed'))
    const f = start()
    await vi.advanceTimersByTimeAsync(0)
    f.sources[0].emit('status', 1)
    f.sources[0].emit('completed', 2)
    await f.done
    await vi.advanceTimersByTimeAsync(10)
    expect(f.statuses).toEqual(['generating', 'completed'])
    expect(getRun).toHaveBeenCalledTimes(2)
  })

  it('최신 상태를 받은 뒤 이전 조회가 실패해도 추적을 중단하지 않는다', async () => {
    const delayed = deferred<RunStatus>()
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockReturnValueOnce(delayed.promise)
      .mockResolvedValueOnce(status('awaiting_review'))
    const f = start()
    await vi.advanceTimersByTimeAsync(0)
    f.sources[0].lose()
    await f.refresh()
    delayed.reject(new Error('이전 조회 연결 실패'))
    await vi.advanceTimersByTimeAsync(5)
    expect(f.statuses).toEqual(['generating', 'awaiting_review'])
    expect(f.sources).toHaveLength(2)
    f.controller.abort()
    await f.done
  })

  it('끊김 복구를 이어받은 최신 수동 조회가 실패하면 추적도 오류로 끝난다', async () => {
    const delayed = deferred<RunStatus>()
    const error = new Error('최신 조회 연결 실패')
    vi.mocked(getRun)
      .mockResolvedValueOnce(status('generating'))
      .mockReturnValueOnce(delayed.promise)
      .mockRejectedValueOnce(error)
    const f = start()
    const result = f.done.catch((err: unknown) => err)
    await vi.advanceTimersByTimeAsync(0)
    f.sources[0].lose()
    await expect(f.refresh()).rejects.toBe(error)
    expect(await result).toBe(error)
    delayed.resolve(status('generating'))
    await vi.advanceTimersByTimeAsync(10)
    expect(f.statuses).toEqual(['generating'])
    expect(f.sources).toHaveLength(1)
  })
})
