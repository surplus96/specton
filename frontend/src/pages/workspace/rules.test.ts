// UI-05 결과 작업공간·UI-07 다운로드 규칙 테스트. 아래 절반은 mock 서버로 실제 흐름(승인 전·후)을 돌린다.
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createRun, downloadArtifact, getRun, getView, listRuns, resumeRun, setApiBaseUrl } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import type { ArtifactRef } from '../../api/viewItems.ts'
import { createMockBackend } from '../../mocks/backend.ts'
import { DDL_SAMPLE, ERD_SAMPLE } from '../../mocks/data.ts'
import { unreachedScreens } from '../run/screens.ts'
import {
  chosenView,
  downloadErrorText,
  downloadRows,
  fileNameOf,
  isApproved,
  missingKinds,
  resultViews,
  revisionOptions,
  shortTime,
  svgSize,
  toArtifacts,
  zoomSteps,
} from './rules.ts'

const ref = (kind: ArtifactRef['kind'], file_format: ArtifactRef['file_format'], approved = false): ArtifactRef => ({
  kind,
  file_format,
  revision: 2,
  hash: `h-${kind}-${file_format}`,
  approved,
})

describe('산출물 목록 읽기', () => {
  it('모양이 맞는 산출물만 고르고, 종류에 없는 형식은 버린다 (docs/06)', () => {
    const raw = [ref('erd', 'mmd'), { kind: 'erd', file_format: 'sql', revision: 2 }, { kind: 'x' }, null, 'erd']
    expect(toArtifacts(raw)).toEqual([ref('erd', 'mmd')])
    expect(toArtifacts(undefined)).toEqual([])
  })

  it('생성 가지(ERD·DDL·RTM) 중 없는 것을 미완성으로 고른다', () => {
    expect(missingKinds([ref('erd', 'mmd'), ref('functions', 'md')])).toEqual(['ddl', 'rtm'])
    expect(missingKinds([ref('erd', 'mmd'), ref('ddl', 'sql'), ref('rtm', 'csv')])).toEqual([])
  })

  it('하나라도 초안이면 초안, 비어 있으면 승인본이 아니다', () => {
    expect(isApproved([ref('erd', 'mmd', true), ref('ddl', 'sql', true)])).toBe(true)
    expect(isApproved([ref('erd', 'mmd', true), ref('ddl', 'sql', false)])).toBe(false)
    expect(isApproved([])).toBe(false)
  })
})

describe('UI-07 다운로드 표', () => {
  it('승인 전에는 PDF를 「승인 후」, 없는 파일을 「없음」으로 나눈다', () => {
    const rows = downloadRows([ref('erd', 'mmd'), ref('ddl', 'sql')], false)
    const erd = rows.find((r) => r.kind === 'erd')!.files
    expect(erd.map((f) => [f.format, f.file.state])).toEqual([
      ['mmd', 'ready'],
      ['pdf', 'needs-approval'],
    ])
    expect(rows.find((r) => r.kind === 'rtm')!.files.map((f) => f.file.state)).toEqual(['not-ready', 'not-ready'])
  })

  it('승인 뒤에도 PDF가 없으면 「없음」(생성 실패)이다', () => {
    const erd = downloadRows([ref('erd', 'mmd', true)], true).find((r) => r.kind === 'erd')!.files
    expect(erd[1].file.state).toBe('not-ready')
  })

  it('파일 이름은 서버와 같은 규칙, 초안이면 -draft', () => {
    expect(fileNameOf(ref('erd', 'mmd'))).toBe('specton-erd-r2-draft.mmd')
    expect(fileNameOf(ref('erd', 'pdf', true))).toBe('specton-erd-r2.pdf')
  })

  it('받기 실패 안내: 서버 문구가 먼저, 없으면 코드별 안내', () => {
    const withMessage = new ApiError(409, { code: 'ARTIFACT_NOT_READY', message: '서버 안내', run_id: null, retryable: false })
    expect(downloadErrorText(withMessage)).toBe('서버 안내')
    const bare = new ApiError(409, null)
    expect(downloadErrorText(bare)).toMatch(/HTTP 409/)
    expect(downloadErrorText(new Error('x'))).toBe('파일을 받지 못했습니다.')
  })
})

describe('화면 고르기', () => {
  it('결과가 있을 때만 결과 작업공간으로 바꿀 수 있고, 첫 화면이 기본이다', () => {
    expect(resultViews('awaiting_review')).toEqual(['review', 'workspace'])
    expect(resultViews('completed')).toEqual(['downloads', 'workspace'])
    expect(resultViews('designing')).toEqual([])
    expect(chosenView('awaiting_review', null)).toBe('review')
    expect(chosenView('awaiting_review', 'workspace')).toBe('workspace')
    expect(chosenView('completed', 'review')).toBe('downloads') // 완료 뒤에는 최종 검토가 없다
    expect(chosenView('designing', 'workspace')).toBeNull()
  })

  it('revision은 최신부터', () => {
    expect(revisionOptions(2)).toEqual([2, 1, 0])
    expect(revisionOptions(0)).toEqual([0])
  })

  it('실패한 실행은 거치지 않은 확인 화면을 완료로 보이지 않는다', () => {
    expect(unreachedScreens('failed', 'analysing')).toEqual(['UI-03'])
    expect(unreachedScreens('failed', 'parsing')).toEqual(['UI-02', 'UI-03'])
    expect(unreachedScreens('failed', null)).toEqual(['UI-02', 'UI-03'])
    expect(unreachedScreens('cancelled', 'designing')).toEqual([])
    expect(unreachedScreens('completed', 'parsing')).toEqual([])
  })
})

describe('ERD 보기', () => {
  it('SVG 원래 크기는 viewBox에서 읽는다', () => {
    expect(svgSize('<svg viewBox="0 0 1760.5 840" width="100%">')).toEqual({ width: 1760.5, height: 840 })
    expect(svgSize('<svg width="10">')).toBeNull()
  })

  it('확대·축소는 정한 단계 안에서만', () => {
    expect(zoomSteps.next(1)).toBe(1.25)
    expect(zoomSteps.prev(1)).toBe(0.8)
    expect(zoomSteps.next(2)).toBe(2)
    expect(zoomSteps.prev(0.25)).toBe(0.25)
    expect(zoomSteps.next(0.6)).toBe(0.67) // 「화면에 맞춤」 뒤의 어중간한 배율에서도 다음 단계로
  })

  it('mock ERD는 실제 ERD 생성 코드의 A안 표기다 (#177)', () => {
    expect(ERD_SAMPLE.startsWith('erDiagram\n')).toBe(true)
    expect(ERD_SAMPLE).toContain('varchar(20) 창고코드 PK "wrhus_cd"')
    expect(ERD_SAMPLE).not.toMatch(/%%\{|^\s*(style|classDef)\b/m) // 설정 지시문·스타일 줄 없음 (#190)
  })

  it('실행 시각을 짧게', () => {
    expect(shortTime('not-a-date')).toBe('not-a-date')
    expect(shortTime(new Date(2026, 10, 8, 9, 5).toISOString())).toBe('11/8 09:05')
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

  async function atReview() {
    const created = await createRun(new File(['내용'], '재고_quick.csv'), 'inventory')
    const run = await getRun(created.run_id)
    expect(run.interrupt?.kind).toBe('review')
    return run
  }

  it('승인 전: 산출물은 초안, PDF는 목록에 없고 받으면 409', async () => {
    const run = await atReview()
    const artifacts = toArtifacts((await getView(run.run_id, 'design')).artifacts)
    expect(missingKinds(artifacts)).toEqual([])
    expect(isApproved(artifacts)).toBe(false)
    expect(artifacts.some((a) => a.file_format === 'pdf')).toBe(false)

    const erd = await downloadArtifact(run.run_id, 'erd', 'mmd', run.revision)
    expect(erd.fileName).toBe(`specton-erd-r${run.revision}-draft.mmd`)
    expect(await erd.blob.text()).toBe(ERD_SAMPLE)
    expect(await (await downloadArtifact(run.run_id, 'ddl', 'sql', run.revision)).blob.text()).toBe(DDL_SAMPLE)

    const err = await downloadArtifact(run.run_id, 'erd', 'pdf', run.revision).catch((e: unknown) => e)
    expect((err as ApiError).status).toBe(409)
    expect(downloadErrorText(err)).toMatch(/PDF는 승인한/)
  })

  it('승인 뒤: 모두 승인본, PDF를 받을 수 있고 이름에 -draft가 없다. 이력에 완료로 보인다', async () => {
    const run = await atReview()
    await resumeRun(run.run_id, {
      interrupt_id: run.interrupt!.interrupt_id,
      expected_revision: run.revision,
      response: { kind: 'review', decision: 'approve', feedback: '' },
    })
    const done = await getRun(run.run_id)
    expect(done.status).toBe('completed')
    expect(chosenView(done.status, null)).toBe('downloads')

    const artifacts = toArtifacts((await getView(run.run_id, 'design')).artifacts)
    expect(isApproved(artifacts)).toBe(true)
    const rows = downloadRows(artifacts, true)
    expect(rows.find((r) => r.kind === 'functions')!.files.map((f) => f.file.state)).toEqual(['ready', 'ready'])
    const pdf = await downloadArtifact(run.run_id, 'erd', 'pdf', done.revision)
    expect(pdf.fileName).toBe(`specton-erd-r${done.revision}.pdf`)

    const history = await listRuns()
    expect(history.find((r) => r.run_id === run.run_id)?.status).toBe('completed')
  })

  it('형식이 맞지 않으면 422 안내', async () => {
    const run = await atReview()
    const err = await downloadArtifact(run.run_id, 'ddl', 'pdf', run.revision).catch((e: unknown) => e)
    expect((err as ApiError).status).toBe(422)
    expect(downloadErrorText(err)).toBe('이 산출물은 그 형식으로 받을 수 없습니다.')
  })
})
