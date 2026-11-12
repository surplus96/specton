import { useState } from 'react'
import type { ArtifactRef } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import { saveArtifact } from './files.ts'
import { KIND_LABEL, downloadErrorText, downloadRows, type ArtifactFormat, type ArtifactKind, type DownloadRow } from './rules.ts'

// UI-07 내려받기 카드 (시안): 어두운 판 + 라임 타일 4개(기능 명세 · ERD · DDL · RTM).
// 타일 안 형식 글자(md · PDF 등)를 누르면 그 파일을 받는다. 승인 전 PDF·아직 없는 파일은 흐리게 막는다.
// 추가 산출물은 생성된 경우에만 별도 펼침 영역에서 제공한다.
const TILES: readonly { kind: ArtifactKind; title: string }[] = [
  { kind: 'functions', title: '기능 명세' },
  { kind: 'erd', title: 'ERD' },
  { kind: 'ddl', title: 'DDL' },
  { kind: 'rtm', title: 'RTM' },
]

const SHORT: Record<ArtifactFormat, string> = { md: 'md', pdf: 'PDF', mmd: 'mmd', sql: 'SQL', xlsx: 'Excel', csv: 'CSV', json: 'JSON' }

type Props = {
  runId: string
  artifacts: readonly ArtifactRef[]
  approved: boolean
  /** 위 작은 글 (예: 재고관리 요구사항) */
  subject: string
}

function DownloadCard({ runId, artifacts, approved, subject }: Props) {
  const rows = downloadRows(artifacts, approved)
  const extraRows = rows.filter((row) => !TILES.some((tile) => tile.kind === row.kind))
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function get(artifact: ArtifactRef) {
    const key = `${artifact.kind}.${artifact.file_format}`
    setBusy(key)
    setError(null)
    try {
      await saveArtifact(runId, artifact)
    } catch (err) {
      setError(downloadErrorText(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="dl-card" aria-label="설계 문서 내려받기">
      <div className="dl-card__eyebrow">
        {subject} · {approved ? '승인본' : '초안'}
      </div>
      <h2 className="dl-card__title">{approved ? '설계 완성.' : '설계 초안.'}</h2>
      <div className="dl-card__grid">
        {TILES.map((tile) => {
          const row = rows.find((r: DownloadRow) => r.kind === tile.kind)
          return (
            <div key={tile.kind} className="dl-tile">
              <span className="dl-tile__name">{tile.title}</span>
              <span className="dl-tile__formats">
                {row?.files.map(({ format, file }, i) => {
                  const ready = file.state === 'ready'
                  const key = `${tile.kind}.${format}`
                  return (
                    <span key={format}>
                      {i > 0 && <span aria-hidden="true"> · </span>}
                      <button
                        type="button"
                        className="dl-tile__format"
                        disabled={!ready || busy !== null}
                        onClick={() => ready && void get(file.artifact)}
                        aria-label={`${tile.title} ${SHORT[format]} ${ready ? '내려받기' : file.state === 'needs-approval' ? '승인 후' : '파일 없음'}`}
                        title={ready ? `${tile.title} ${SHORT[format]} 내려받기` : file.state === 'needs-approval' ? 'PDF는 승인 후 내려받을 수 있어요' : '아직 만들어지지 않았어요'}
                      >
                        {busy === key ? '받는 중' : SHORT[format]}{!ready && (file.state === 'needs-approval' ? ' (승인 후)' : ' (없음)')}
                      </button>
                    </span>
                  )
                })}
                <Icon name="download" size={15} />
              </span>
            </div>
          )
        })}
      </div>
      {extraRows.length > 0 && <details>
        <summary>추가 파일</summary>
        {extraRows.map((row) => <div key={row.kind} className="row">
          <span>{KIND_LABEL[row.kind]}</span>
          {row.files.map(({ format, file }) => {
            const ready = file.state === 'ready' && (row.kind !== 'manifest' || file.artifact.approved)
            return <button key={format} type="button" className="dl-tile__format"
              aria-label={`${KIND_LABEL[row.kind]} ${SHORT[format]} 내려받기`}
              disabled={!ready || busy !== null}
              onClick={() => ready && file.state === 'ready' && void get(file.artifact)}>
              {SHORT[format]}{!ready && (row.kind === 'manifest' && !approved ? ' (승인 후)' : ' (없음)')}
            </button>
          })}
        </div>)}
      </details>}
      {!approved && <p className="dl-card__note">승인 전 파일이라 이름에 -draft가 붙어요. PDF는 승인 후 내려받을 수 있어요.</p>}
      {error && (
        <p className="dl-card__error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

export default DownloadCard
