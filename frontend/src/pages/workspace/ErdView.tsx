import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Flex, Spin, Typography } from 'antd'
import { errorMessage } from '../../api/errors.ts'
import type { ArtifactRef } from '../../api/viewItems.ts'
import { colors } from '../../theme.ts'
import { artifactText, saveArtifact } from './files.ts'
import {
  downloadErrorText,
  isAllowedErdSource,
  mermaidConfig,
  svgDataUri,
  svgSize,
  zoomSteps,
} from './rules.ts'

// ERD 보기 (UI-05, docs/09 「ERD는 확대·이동과 원문 다운로드」).
// 서버가 만든 .mmd(specton/codegen/erd.py, #177·#178)만 그린다. 웹·PDF 모두 Mermaid 11.17.2 (#13, #223, ADR-0004).
// 보안 (#190 R1 리뷰, ADR-0004 「Mermaid 설정 보안」):
//   1. 원문 검사: erDiagram이 아니거나 지시문(%%{)이 있으면 그리지 않는다 (isAllowedErdSource).
//   2. 설정: 개발자가 정한 mermaidConfig()만 넘기고 secure 목록으로 원문이 바꾸지 못하게 한다.
//   3. 격리: 그린 SVG를 <img>(data URI)로 보여, 그림 안 CSS·스크립트가 화면에 닿지 않게 한다.
type Props = {
  runId: string
  artifact: ArtifactRef | undefined
}

type Mermaid = typeof import('mermaid').default

// mermaid는 크다. ERD 탭을 처음 열 때만 불러오고, 한 번만 초기화한다.
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
          if (alive) setError('ERD 원문 형식이 맞지 않아 그리지 않았습니다 (ERD 외 내용 또는 지시문 포함).')
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
        setError(err instanceof Error && !('status' in err) ? `ERD를 그리지 못했습니다: ${err.message}` : errorMessage(err))
      })
    return () => {
      alive = false
    }
  }, [runId, artifact])

  const size = useMemo(() => (svg ? svgSize(svg) : null), [svg])
  const src = useMemo(() => (svg ? svgDataUri(svg) : null), [svg])

  function fit() {
    const width = box.current?.clientWidth
    if (size && width) setScale(Math.min(1, (width - 24) / size.width))
  }

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
    return <Alert type="warning" showIcon title="ERD가 아직 없습니다 (미완성)" description="ERD 생성 가지가 끝나지 않았거나 실패했습니다." />
  }

  return (
    <Flex vertical gap={12}>
      <Flex gap={8} wrap align="center">
        <Button onClick={() => setScale((s) => zoomSteps.prev(s))} disabled={!src} aria-label="ERD 축소">
          축소
        </Button>
        <Button onClick={() => setScale((s) => zoomSteps.next(s))} disabled={!src} aria-label="ERD 확대">
          확대
        </Button>
        <Button onClick={() => setScale(1)} disabled={!src}>
          원래 크기
        </Button>
        <Button onClick={fit} disabled={!src}>
          화면에 맞춤
        </Button>
        <Typography.Text type="secondary">{Math.round(scale * 100)}%</Typography.Text>
        <Button type="link" onClick={download}>
          원문(.mmd) 내려받기
        </Button>
      </Flex>
      {downloadError && <Alert type="error" showIcon title={downloadError} />}
      {error ? (
        <Alert type="error" showIcon title={error} description="원문(.mmd)은 내려받아 확인할 수 있습니다." />
      ) : !src || !size ? (
        <Flex justify="center" style={{ padding: 32 }}>
          <Spin />
        </Flex>
      ) : (
        // 크기 조절: SVG 원래 크기(viewBox)에 배율을 곱한다. 넘치면 상자 안에서 스크롤로 이동한다.
        <div
          ref={box}
          style={{
            overflow: 'auto',
            maxHeight: '70vh',
            border: `1.5px solid ${colors.border}`,
            borderRadius: 12,
            padding: 12,
            background: '#fff',
          }}
        >
          <img
            src={src}
            alt={`ERD revision ${artifact.revision}`}
            width={Math.round(size.width * scale)}
            height={Math.round(size.height * scale)}
            style={{ display: 'block', maxWidth: 'none' }}
          />
        </div>
      )}
    </Flex>
  )
}

export default ErdView
