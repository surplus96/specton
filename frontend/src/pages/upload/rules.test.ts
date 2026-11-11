// UI-01 업로드 규칙 테스트. 미리 검사 문구가 서버·mock과 같은지, 서버 오류가 맞는 칸에 가는지 본다.
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createRun, setApiBaseUrl } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import type { ErrorCode } from '../../api/types.ts'
import { createMockBackend } from '../../mocks/backend.ts'
import { MAX_UPLOAD_MB, PACK_OPTIONS, checkFile, errorPlace, placeError } from './rules.ts'

const MB = 1024 * 1024
const named = (name: string, size = 10) => ({ name, size })

describe('checkFile: 미리 검사', () => {
  it.each(['요구사항.xlsx', '요구사항.CSV', '정의서.hwpx', '정의서.HWP'])('%s는 통과 (한글은 #24)', (name) => {
    expect(checkFile(named(name))).toBeNull()
  })

  it.each(['설비.pdf', '메모.txt', '확장자없음'])('%s는 지원 형식 안내', (name) => {
    expect(checkFile(named(name))).toBe('지원하는 형식은 .xlsx, .csv, .hwpx, .hwp입니다.')
  })

  it('빈 파일', () => {
    expect(checkFile(named('요구사항.csv', 0))).toBe('빈 파일입니다.')
  })

  it('한도는 넘을 때만 거절', () => {
    expect(checkFile(named('a.xlsx', MAX_UPLOAD_MB * MB))).toBeNull()
    expect(checkFile(named('a.xlsx', MAX_UPLOAD_MB * MB + 1))).toBe(`파일이 ${MAX_UPLOAD_MB}MB를 넘습니다.`)
  })
})

describe('errorPlace: 오류를 보일 자리', () => {
  const apiError = (status: number, code: string) =>
    new ApiError(status, { code: code as ErrorCode, message: '서버 문구', retryable: false })

  it.each([
    [413, 'UPLOAD_TOO_LARGE', 'file'],
    [415, 'UNSUPPORTED_MEDIA_TYPE', 'file'],
    [422, 'EXTRACTION_FAILED', 'file'],
    [422, 'PACK_UNSUPPORTED', 'pack'],
    [422, 'INVALID_REQUEST', 'form'],
    [500, 'INTERNAL', 'form'],
  ])('%i %s → %s', (status, code, place) => {
    expect(errorPlace(apiError(status, code))).toBe(place)
  })

  it('연결 실패와 알 수 없는 예외는 버튼 위 안내', () => {
    expect(errorPlace(new ApiError(0, null))).toBe('form')
    expect(errorPlace(new Error('x'))).toBe('form')
  })

  it('서버 문구를 그대로 쓴다', () => {
    expect(placeError(apiError(415, 'UNSUPPORTED_MEDIA_TYPE'))).toEqual({ place: 'file', message: '서버 문구' })
  })
})

describe('팩 선택지', () => {
  it('지금은 재고관리만 고를 수 있다', () => {
    expect(PACK_OPTIONS).toEqual([{ value: 'inventory', label: '재고관리' }])
  })
})

// 미리 검사를 통과하지 못한 파일을 서버(mock)에 보내도 같은 문구·같은 자리가 나오는지 본다.
// 미리 검사가 빠지거나 문구가 어긋나도 화면 안내가 바뀌지 않게 하려는 것이다.
describe('서버(mock)와 같은 결과', () => {
  const server = setupServer()
  beforeAll(() => {
    setApiBaseUrl('http://specton.test')
    server.listen({ onUnhandledRequest: 'error' })
  })
  afterAll(() => server.close())
  beforeEach(() => server.resetHandlers(...createMockBackend().handlers))

  async function serverResult(file: File, pack = 'inventory') {
    try {
      await createRun(file, pack as 'inventory')
    } catch (err) {
      return placeError(err)
    }
    throw new Error('거절되어야 합니다')
  }

  // 화면과 서버가 같은 형식을 받으므로(#24) 서버가 거절한 문구도 미리 검사 문구와 같고 파일 칸에 보인다.
  it.each(['메모.docx', '설비.pdf'])('%s는 서버가 거절해도 같은 문구로 파일 칸', async (name) => {
    const file = new File(['내용'], name)
    const result = await serverResult(file)
    expect(result.place).toBe('file')
    expect(result.message).toBe(checkFile(file))
  })

  it('빈 파일', async () => {
    const file = new File([], '요구사항.csv')
    expect((await serverResult(file)).message).toBe(checkFile(file))
  })

  it('없는 팩은 팩 칸', async () => {
    const result = await serverResult(new File(['내용'], '요구사항.csv'), 'finance')
    expect(result.place).toBe('pack')
  })

  it('정상 파일은 접수된다', async () => {
    const run = await createRun(new File(['내용'], '요구사항.csv'), 'inventory')
    expect(run.status).toBe('queued')
  })

  it('서버에 닿지 못하면 버튼 위 안내', async () => {
    server.use(http.post('*/runs', () => HttpResponse.error()))
    const result = await serverResult(new File(['내용'], '요구사항.csv'))
    expect(result.place).toBe('form')
    expect(result.message).toContain('서버에 연결하지 못했습니다')
  })
})
