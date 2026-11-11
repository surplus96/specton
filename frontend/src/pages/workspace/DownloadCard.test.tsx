import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ArtifactRef } from '../../api/viewItems.ts'
import DownloadCard from './DownloadCard.tsx'

const artifact = (kind: ArtifactRef['kind'], file_format: ArtifactRef['file_format'], approved = true): ArtifactRef =>
  ({ kind, file_format, approved, revision: 0, hash: 'h' })
const render = (artifacts: ArtifactRef[], approved = true) => renderToStaticMarkup(
  <DownloadCard runId="r" artifacts={artifacts} approved={approved} subject="재고관리 요구사항" />,
)

describe('다운로드 카드의 기존 파일 접근 보존', () => {
  it('승인 manifest와 과거 요구사항·검토 파일을 추가 파일로 제공한다', () => {
    const html = render([artifact('manifest', 'json'), artifact('requirements', 'md'), artifact('review', 'md')])
    for (const label of ['파일 목록 JSON 내려받기', '요구사항 md 내려받기', '검토 결과 md 내려받기']) {
      const button = html.split('<button').find((part) => part.includes(`aria-label="${label}"`))?.split('</button>')[0]
      expect(button).toBeDefined()
      expect(button).not.toContain('disabled')
    }
    expect(render([])).not.toContain('추가 파일')
  })
  it('승인 전 PDF와 manifest는 막고 파일 없음은 문구로 설명한다', () => {
    const html = render([artifact('functions', 'pdf', false), artifact('manifest', 'json', false)], false)
    expect(html).toMatch(/disabled=""[^>]*>PDF \(승인 후\)/)
    const manifest = html.split('<button').find((part) => part.includes('aria-label="파일 목록 JSON 내려받기"'))?.split('</button>')[0]
    expect(manifest).toContain('disabled')
    expect(manifest).toContain('승인 후')
    expect(html).toContain('SQL (없음)')
  })
})
