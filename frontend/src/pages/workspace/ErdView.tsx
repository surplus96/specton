import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { errorMessage } from '../../api/errors.ts'
import type { ArtifactRef } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import Button from '../../ui/Button.tsx'
import Loading from '../../ui/Loading.tsx'
import Notice from '../../ui/Notice.tsx'
import { artifactText, saveArtifact } from './files.ts'
import { downloadErrorText, erdFitScale, isAllowedErdSource, mermaidConfig, svgDataUri, svgSize, zoomSteps } from './rules.ts'

// ERD 보기 (UI-05 「ERD는 확대·이동과 원문 다운로드」).
// 서버가 만든 .mmd만 그린다. 웹·PDF 모두 Mermaid 11.17.2 (ADR-0004).
// 보안: 1) erDiagram이 아니거나 지시문(%%{)이 있으면 그리지 않는다 2) 개발자가 정한 설정만 넘긴다
//       3) 그린 SVG를 <img>(data URI)로 보여, 그림 안 CSS·스크립트가 화면에 닿지 않게 한다.
type Props = {
  runId: string
  artifact: ArtifactRef | undefined
}

type Mermaid = typeof import('mermaid').default

let mermaidReady: Promise<Mermaid> | null = null
function loadMermaid(): Promise<Mermaid> {
  mermaidReady ??= import('mermaid').then(({ default: mermaid }) => {
    mermaid.initialize(mermaidConfig())
    return mermaid
  })
  return mermaidReady
}

let renderSeq = 0

function ErdView({ runId, artifact }: Props) {
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scale, setScale] = useState(1)
  const box = useRef<HTMLDivElement>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  useEffect(() => {
    if (!artifact) return
    let alive = true
    setSvg(null)
    setError(null)
    setScale(1)
    artifactText(runId, artifact)
      .then(async (text) => {
        if (!isAllowedErdSource(text)) {
          if (alive) setError('ERD를 그리지 못했어요. 원본 파일은 내려받을 수 있어요.')
          return
        }
        const mermaid = await loadMermaid()
        renderSeq += 1
        const { svg: drawn } = await mermaid.render(`specton-erd-${renderSeq}`, text)
        if (alive) setSvg(drawn)
      })
      .catch((err: unknown) => {
        if (!alive) return
        // 받기 실패는 서버 안내, 그리기 실패는 Mermaid 문법 오류다. 원문은 받을 수 있게 둔다.
        setError(err instanceof Error && !('status' in err) ? `ERD를 그리지 못했어요: ${err.message}` : errorMessage(err))
      })
    return () => {
      alive = false
    }
  }, [runId, artifact])

  const size = useMemo(() => (svg ? svgSize(svg) : null), [svg])
  const src = useMemo(() => (svg ? svgDataUri(svg) : null), [svg])

  // 화면에 맞춤: 그림 전체가 가로·세로 모두 상자(.erd-box, 최대 높이 70vh) 안에 들어가는 배율. 원래 크기보다 키우지는 않는다
  const fit = useCallback(() => {
    const width = box.current?.clientWidth
    if (!size || !width) return
    const padding = 32 // .erd-box 안쪽 여백 16px × 2
    const height = window.innerHeight * 0.7 - padding - 2
    setScale(erdFitScale(size, width - padding, height))
  }, [size])

  // 처음 그림을 그리면 전체가 한 번에 보이게 맞춘다
  useEffect(() => {
    if (src) fit()
  }, [src, fit])

  async function download() {
    if (!artifact) return
    setDownloadError(null)
    try {
      await saveArtifact(runId, artifact)
    } catch (err) {
      setDownloadError(downloadErrorText(err))
    }
  }

  if (!artifact) {
    return (
      <Notice kind="warning" title="ERD가 아직 없어요 (미완성)">
        ERD를 아직 못 만들었어요.
      </Notice>
    )
  }

  return (
    <div className="stack-sm" style={{ gap: 14 }}>
      <div className="row">
        <div className="segmented segmented--sm" role="group" aria-label="ERD 확대">
          <button type="button" onClick={() => setScale((s) => zoomSteps.prev(s))} disabled={!src} aria-label="ERD 축소">
            축소
          </button>
          <button type="button" onClick={() => setScale((s) => zoomSteps.next(s))} disabled={!src} aria-label="ERD 확대">
            확대
          </button>
          <button type="button" onClick={() => setScale(1)} disabled={!src}>
            원래 크기
          </button>
          <button type="button" onClick={fit} disabled={!src}>
            화면에 맞춤
          </button>
        </div>
        <span className="muted mono">{Math.round(scale * 100)}%</span>
        <Button variant="ghost" size="sm" icon={<Icon name="download" size={16} />} onClick={download} style={{ marginLeft: 'auto' }}>
          그림 원본(.mmd) 내려받기
        </Button>
      </div>
      {downloadError && <Notice kind="error" title={downloadError} />}
      {error ? (
        <Notice kind="error" title={error}>
          그림 원본(.mmd)은 내려받아 확인할 수 있어요.
        </Notice>
      ) : !src || !size ? (
        <Loading text="ERD를 그리는 중이에요" />
      ) : (
        // 크기 조절: SVG 원래 크기에 배율을 곱한다. 넘치면 상자 안에서 스크롤로 이동한다.
        <div ref={box} className="erd-box" tabIndex={0} aria-label="ERD 그림 영역 (스크롤로 이동)">
          <img
            src={src}
            alt={`ERD revision ${artifact.revision}`}
            width={Math.round(size.width * scale)}
            height={Math.round(size.height * scale)}
            style={{ display: 'block', maxWidth: 'none' }}
          />
        </div>
      )}
    </div>
  )
}

export default ErdView
