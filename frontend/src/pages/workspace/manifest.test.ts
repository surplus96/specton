import { describe, expect, it } from 'vitest'
import { downloadAllList, downloadRows, toArtifacts } from './rules.ts'

// 실제 서버는 승인한 revision에 manifest(JSON)를 함께 만든다 (#222). 화면이 버리지 않고 내려받게 한다.
const manifest = { kind: 'manifest', file_format: 'json', revision: 1, hash: 'h', approved: true }
const ddl = { kind: 'ddl', file_format: 'sql', revision: 1, hash: 'h', approved: true }

describe('manifest 산출물', () => {
  it('view의 manifest JSON을 산출물로 받아들인다', () => {
    expect(toArtifacts([manifest, ddl]).map((a) => a.kind)).toEqual(['manifest', 'ddl'])
  })

  it('만들어졌을 때만 다운로드 표·전체 내려받기에 들어간다', () => {
    const withIt = toArtifacts([manifest, ddl])
    expect(downloadRows(withIt, true).some((r) => r.kind === 'manifest')).toBe(true)
    expect(downloadAllList(withIt).map((a) => `${a.kind}.${a.file_format}`)).toContain('manifest.json')
    expect(downloadRows(toArtifacts([ddl]), true).some((r) => r.kind === 'manifest')).toBe(false)
  })
})
