// 산출물 파일 받기·저장. 파일 이름은 서버가 Content-Disposition으로 정한다 (docs/06).
import { downloadArtifact } from '../../api/client.ts'
import type { ArtifactRef } from '../../api/viewItems.ts'

/** 브라우저 「다운로드」로 저장한다. */
export function saveFile(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  // 클릭 처리가 끝난 뒤 지운다. 바로 지우면 일부 브라우저에서 저장이 취소된다.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 산출물 하나를 받아 저장한다. 실패하면 ApiError를 그대로 던진다. */
export async function saveArtifact(runId: string, a: Pick<ArtifactRef, 'kind' | 'file_format' | 'revision'>): Promise<void> {
  const { blob, fileName } = await downloadArtifact(runId, a.kind, a.file_format, a.revision)
  saveFile(blob, fileName)
}

/** 글자 산출물(ERD .mmd, DDL .sql)을 화면에 보이려고 글자로 받는다. */
export async function artifactText(runId: string, a: Pick<ArtifactRef, 'kind' | 'file_format' | 'revision'>): Promise<string> {
  const { blob } = await downloadArtifact(runId, a.kind, a.file_format, a.revision)
  return blob.text()
}
