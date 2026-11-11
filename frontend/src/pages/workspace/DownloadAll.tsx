import { useState } from 'react'
import type { ArtifactRef } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import Button from '../../ui/Button.tsx'
import Notice from '../../ui/Notice.tsx'
import { saveArtifact } from './files.ts'
import { artifactLabel, downloadAllList, downloadErrorText } from './rules.ts'

// 「전체 내려받기」: 지금 받을 수 있는 산출물을 하나씩 차례로 저장한다.
// 묶음(zip) API가 없어 파일마다 따로 받는다. 하나가 실패해도 나머지는 계속 받고, 실패한 것만 알린다.
type Props = {
  runId: string
  artifacts: readonly ArtifactRef[]
  variant?: 'accent' | 'primary'
}

type Result = { saved: number; failed: { label: string; reason: string }[] }

// 브라우저가 연속 다운로드를 한꺼번에 막지 않게 파일 사이에 잠깐 쉰다
const GAP_MS = 400

function DownloadAll({ runId, artifacts, variant = 'primary' }: Props) {
  const files = downloadAllList(artifacts)
  const [progress, setProgress] = useState<number | null>(null)
  const [result, setResult] = useState<Result | null>(null)

  async function downloadAll() {
    setResult(null)
    const failed: Result['failed'] = []
    for (const [i, artifact] of files.entries()) {
      setProgress(i)
      try {
        await saveArtifact(runId, artifact)
      } catch (err) {
        failed.push({ label: artifactLabel(artifact), reason: downloadErrorText(err) })
      }
      if (i < files.length - 1) await new Promise((resolve) => setTimeout(resolve, GAP_MS))
    }
    setProgress(null)
    setResult({ saved: files.length - failed.length, failed })
  }

  const running = progress !== null
  return (
    <div className="stack-sm">
      <Button
        variant={variant}
        size="lg"
        block
        onClick={downloadAll}
        loading={running}
        loadingText={running ? `내려받는 중 ${progress + 1}/${files.length}` : undefined}
        disabled={files.length === 0}
        iconEnd={<Icon name="download" size={18} />}
      >
        전체 내려받기 ({files.length}개)
      </Button>
      <span style={{ fontSize: 13, opacity: 0.75 }}>파일마다 따로 저장돼요. 브라우저가 「여러 파일 다운로드」 허용을 물으면 허용해 주세요.</span>
      {result && result.failed.length === 0 && (
        <Notice kind="success" title={`${result.saved}개 파일 저장을 요청했어요.`}>
          브라우저가 여러 파일 받기를 막았다면 주소창의 안내에서 허용해 주세요.
        </Notice>
      )}
      {result && result.failed.length > 0 && (
        <Notice kind="warning" title={`${result.saved}개 저장, ${result.failed.length}개 실패`}>
          <ul>
            {result.failed.map((f) => (
              <li key={f.label}>
                {f.label}: {f.reason}
              </li>
            ))}
          </ul>
        </Notice>
      )}
    </div>
  )
}

export default DownloadAll
