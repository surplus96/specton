import { useState } from 'react'
import { Alert, Button, Flex, Typography } from 'antd'
import type { ArtifactRef } from '../../api/viewItems.ts'
import { saveArtifact } from './files.ts'
import { artifactLabel, downloadAllList, downloadErrorText } from './rules.ts'

// 「전체 내려받기」: 지금 받을 수 있는 산출물을 하나씩 차례로 저장한다 (UI-07).
// 묶음(zip) API가 없어 파일마다 따로 받는다. 하나가 실패해도 나머지는 계속 받고, 실패한 것만 알린다.
type Props = {
  runId: string
  artifacts: readonly ArtifactRef[]
}

type Result = { saved: number; failed: { label: string; reason: string }[] }

// 브라우저가 연속 다운로드를 한꺼번에 막지 않게 파일 사이에 잠깐 쉰다
const GAP_MS = 400

function DownloadAll({ runId, artifacts }: Props) {
  const files = downloadAllList(artifacts)
  const [progress, setProgress] = useState<number | null>(null) // 받는 중이면 지금까지 끝낸 수
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
    <Flex vertical gap={8} style={{ marginBottom: 12 }}>
      <Flex gap={12} align="center" wrap>
        <Button type="primary" onClick={downloadAll} loading={running} disabled={files.length === 0}>
          {running ? `내려받는 중 ${progress + 1}/${files.length}` : `전체 내려받기 (${files.length}개)`}
        </Button>
        <Typography.Text type="secondary">
          파일마다 따로 저장됩니다. 처음에 브라우저가 「여러 파일 다운로드」 허용을 물으면 허용해 주세요.
        </Typography.Text>
      </Flex>
      {result && result.failed.length === 0 && (
        <Alert type="success" showIcon title={`${result.saved}개 파일을 저장했습니다.`} />
      )}
      {result && result.failed.length > 0 && (
        <Alert
          type="warning"
          showIcon
          title={`${result.saved}개 저장, ${result.failed.length}개 실패`}
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {result.failed.map((f) => (
                <li key={f.label}>
                  {f.label}: {f.reason}
                </li>
              ))}
            </ul>
          }
        />
      )}
    </Flex>
  )
}

export default DownloadAll
