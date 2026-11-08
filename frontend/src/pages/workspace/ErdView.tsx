import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Flex, Spin, Typography } from 'antd'
import { errorMessage } from '../../api/errors.ts'
import type { ArtifactRef } from '../../api/viewItems.ts'
import { colors } from '../../theme.ts'
import { artifactText, saveArtifact } from './files.ts'
import { downloadErrorText, svgSize, zoomSteps } from './rules.ts'

// ERD 보기 (UI-05, docs/09 「ERD는 확대·이동과 원문 다운로드」).
// 서버가 만든 .mmd(specton/codegen/erd.py, #177·#178)만 그린다. 웹·PDF 모두 Mermaid 11.15.0 (#13, #190).
// 보안: securityLevel 'strict'와 고정 설정으로만 초기화한다. 원문 안 설정 지시문은 쓰지 않는다 (#190 본문).
type Props = {
  runId: string
  artifact: ArtifactRef | undefined
}

type Mermaid = typeof import('mermaid').default

// mermaid는 크다. ERD 탭을 처음 열 때만 불러오고, 한 번만 초기화한다.
let mermaidReady: Promise<Mermaid> | null = null
function loadMermaid(): Promise<Mermaid> {
  mermaidReady ??= import('mermaid').then(({ default: mermaid }) => {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'neutral',
      fontFamily: 'Pretendard, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif',
      er: { useMaxWidth: false },
    })
    return mermaid
  })
  return mermaidReady
}

let renderSeq = 0

function ErdView({ runId, artifact }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scale, setScale] = useState(1)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  useEffect(() => {
    if (!artifact) return
    let alive = true
    setSvg(null)
    setError(null)
    Promise.all([artifactText(runId, artifact), loadMermaid()])
      .then(async ([text, mermaid]) => {
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

  // 크기 조절: SVG의 원래 크기(viewBox)에 배율을 곱해 width·height를 정한다. 넘치면 상자 안에서 스크롤로 이동한다.
  useEffect(() => {
    const el = box.current?.querySelector('svg')
    if (!el || !svg) return
    const size = svgSize(svg)
    if (!size) return
    el.removeAttribute('style')
    el.setAttribute('width', String(Math.round(size.width * scale)))
    el.setAttribute('height', String(Math.round(size.height * scale)))
  }, [svg, scale])

  function fit() {
    const size = svg ? svgSize(svg) : null
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
        <Button onClick={() => setScale((s) => zoomSteps.prev(s))} disabled={!svg} aria-label="ERD 축소">
          축소
        </Button>
        <Button onClick={() => setScale((s) => zoomSteps.next(s))} disabled={!svg} aria-label="ERD 확대">
          확대
        </Button>
        <Button onClick={() => setScale(1)} disabled={!svg}>
          원래 크기
        </Button>
        <Button onClick={fit} disabled={!svg}>
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
      ) : !svg ? (
        <Flex justify="center" style={{ padding: 32 }}>
          <Spin />
        </Flex>
      ) : (
        <div
          ref={box}
          role="img"
          aria-label={`ERD revision ${artifact.revision}`}
          style={{
            overflow: 'auto',
            maxHeight: '70vh',
            border: `1px solid ${colors.hairline}`,
            borderRadius: 12,
            padding: 12,
            background: '#fff',
          }}
          // strict 모드의 mermaid가 만든 SVG다 (원문 안 HTML·스크립트는 mermaid가 걸러 낸다)
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}
    </Flex>
  )
}

export default ErdView
