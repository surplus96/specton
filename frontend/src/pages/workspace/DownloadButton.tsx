import { useState } from 'react'
import type { ArtifactRef } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import Button from '../../ui/Button.tsx'
import { saveArtifact } from './files.ts'
import { FORMAT_LABEL, downloadErrorText } from './rules.ts'

// 산출물 하나 내려받기 버튼. 실패하면 버튼 아래에 안내한다. 실제로 받은 파일만 성공으로 본다.
function DownloadButton({ runId, artifact, variant = 'secondary' }: { runId: string; artifact: ArtifactRef; variant?: 'secondary' | 'primary' | 'accent' }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function click() {
    setBusy(true)
    setError(null)
    try {
      await saveArtifact(runId, artifact)
    } catch (err) {
      setError(downloadErrorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="stack-sm" style={{ gap: 4 }}>
      <Button variant={variant} size="sm" onClick={click} loading={busy} loadingText="받는 중" icon={<Icon name="download" size={15} />}>
        {FORMAT_LABEL[artifact.file_format]}
        {artifact.approved ? '' : ' (초안)'}
      </Button>
      {error && (
        <span className="field__error" role="alert">
          {error}
        </span>
      )}
    </span>
  )
}

export default DownloadButton
