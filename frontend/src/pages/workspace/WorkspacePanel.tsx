import RunEyebrow from '../run/RunEyebrow.tsx'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus } from '../../api/types.ts'
import type { ArtifactRef, DesignItem, Finding } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import Button from '../../ui/Button.tsx'
import DataTable from '../../ui/DataTable.tsx'
import Loading from '../../ui/Loading.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import Tabs from '../../ui/Tabs.tsx'
import { useViewSection } from '../useViewSection.ts'
import SectionState from '../../ui/SectionState.tsx'
import DesignTables from '../review/DesignTables.tsx'
import FindingsTable from '../review/FindingsTable.tsx'
import { nameIndex } from '../review/rules.ts'
import DownloadButton from './DownloadButton.tsx'
import ErdView from './ErdView.tsx'
import { artifactText } from './files.ts'
import { workspaceTab, type WorkspaceTab } from './pipeline.ts'
import ResultSummary from './ResultSummary.tsx'
import { parseRtmCsv, RtmFormatError, RTM_COLUMNS, type RtmRow } from './rtm.ts'
import { revisionText } from '../runMeta.ts'
import { KIND_LABEL, downloadErrorText, isApproved, isDownloadable, missingKinds, revisionOptions, toArtifacts, type ArtifactKind } from './rules.ts'

// UI-05 결과 작업공간: 기능·ERD·DDL·RTM·검토 탭, revision 고르기, 미완성 가지 표시.
// 설계를 직접 고치지는 않는다. 바꾸려면 최종 검토(UI-06)에서 수정을 요청한다.
// AI가 판단한 탭(기능·검토)에만 「AI 판단」 표시를 단다. 코드가 만드는 ERD·DDL·RTM 탭에는 표시하지 않는다.
type Props = {
  run: RunStatus
  label: string
  /** 최종 검토 대기 중이면 「최종 검토로」 버튼 */
  onReview?: () => void
}


const ORIGIN: Partial<Record<WorkspaceTab, string>> = {
  design: 'AI 판단',
  review: 'AI 검토 · 규칙',
}

function WorkspacePanel({ run, label, onReview }: Props) {
  const [revision, setRevision] = useState(run.revision)
  const designSection = useViewSection(run.run_id, revision, 'design')
  const reviewSection = useViewSection(run.run_id, revision, 'review')
  useEffect(() => setRevision(run.revision), [run.revision])
  const data = useMemo(() => designSection.data ? {
    design: designSection.data.items as DesignItem[],
    artifacts: toArtifacts(designSection.data.artifacts),
  } : null, [designSection.data])
  const findings = reviewSection.data?.items as Finding[] | undefined

  // 고른 탭은 주소(&tab=)에 둔다. 다운로드 화면의 파이프라인 카드가 이 탭으로 바로 연다.
  const [params, setParams] = useSearchParams()
  const tab = workspaceTab(params.get('tab'))
  function openTab(next: WorkspaceTab) {
    setParams(
      (p) => {
        const q = new URLSearchParams(p)
        q.set('tab', next)
        return q
      },
      { replace: true },
    )
  }

  const names = useMemo(() => nameIndex(data?.design ?? []), [data])
  const missing = data ? missingKinds(data.artifacts) : []
  const find = (kind: ArtifactKind, format: ArtifactRef['file_format']) => data?.artifacts.find((a) => a.kind === kind && a.file_format === format)

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={<RunEyebrow screen="결과 보기" label={label} run={run} />}
        title={
          <>
            <strong>설계 초안</strong>이 준비됐어요
          </>
        }
        lead="설계 결과를 문서별로 볼 수 있어요. 고칠 게 있으면 최종 승인 화면에서 수정을 요청해 주세요."
        actions={
          onReview && (
            <Button variant="accent" size="lg" onClick={onReview} iconEnd={<Icon name="arrowRight" size={18} />}>
              최종 승인으로
            </Button>
          )
        }
      />

      <div className="row">
        <label htmlFor="revision" className="muted">
          설계안
        </label>
        <select id="revision" className="select" style={{ width: 160 }} value={revision} onChange={(e) => setRevision(Number(e.target.value))}>
          {revisionOptions(run.revision).map((r) => (
            <option key={r} value={r}>
              {r === run.revision ? `${revisionText(r)} (최신)` : revisionText(r)}
            </option>
          ))}
        </select>
        {data && data.artifacts.length > 0 && (
          <StatusTag tone={isApproved(data.artifacts) ? 'success' : 'warning'}>{isApproved(data.artifacts) ? '승인본' : '초안'}</StatusTag>
        )}
      </div>

      <SectionState title="검토 지적" error={reviewSection.error} loading={!reviewSection.data && !reviewSection.error} reload={reviewSection.reload} />
      {designSection.error || !data ? (
        <>
          <SectionState title="설계 결과" error={designSection.error} loading={!designSection.error} reload={designSection.reload} />
          {findings && <FindingsTable findings={findings} names={names} />}
        </>
      ) : (
        <>
          {missing.length > 0 && (
            <Notice kind="warning" title={`아직 없는 문서: ${missing.map((k) => KIND_LABEL[k]).join(', ')}`}>
              이 설계안에서는 아직 못 만들었어요.
            </Notice>
          )}
          {findings && <ResultSummary design={data.design} findings={findings} />}
          <Tabs<WorkspaceTab>
            label="결과 탭"
            active={tab}
            onChange={openTab}
            extra={ORIGIN[tab] ? <span className="badge">{ORIGIN[tab]}</span> : undefined}
            items={[
              { key: 'design', label: '기능', content: <DesignTables items={data.design} names={names} /> },
              { key: 'erd', label: 'ERD', content: <ErdView runId={run.run_id} artifact={find('erd', 'mmd')} /> },
              { key: 'ddl', label: 'DDL', content: <TextArtifact runId={run.run_id} artifact={find('ddl', 'sql')} kind="ddl" /> },
              { key: 'rtm', label: 'RTM', content: <RtmTab key={`${run.run_id}:${revision}`} runId={run.run_id} artifacts={data.artifacts} /> },
              { key: 'review', label: `검토 ${findings?.length ?? (reviewSection.error ? '조회 실패' : '조회 중')}`, content: findings ? <FindingsTable findings={findings} names={names} /> : <SectionState title="검토 지적" error={reviewSection.error} loading={!reviewSection.error} reload={reviewSection.reload} /> },
            ]}
          />
        </>
      )}
    </div>
  )
}

/** 글자 산출물(DDL)을 그대로 보이고 내려받게 한다. 보여 주기만 한 SQL이라 검증 상태는 최종 검토에서 확인한다. */
function TextArtifact({ runId, artifact, kind }: { runId: string; artifact: ArtifactRef | undefined; kind: ArtifactKind }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!artifact) return
    let alive = true
    setText(null)
    setError(null)
    artifactText(runId, artifact)
      .then((t) => alive && setText(t))
      .catch((err: unknown) => alive && setError(downloadErrorText(err)))
    return () => {
      alive = false
    }
  }, [runId, artifact])

  if (!artifact) return <Notice kind="warning" title={`${KIND_LABEL[kind]}이 아직 없어요`} />
  return (
    <div className="stack-sm" style={{ gap: 14 }}>
      <div className="row row--between">
        <span className="muted" style={{ fontSize: 14 }}>
          {artifact.validation ? `SQL 검증: ${VALIDATION_TEXT[artifact.validation.status]}` : 'SQL 검증 결과는 최종 승인에서 확인해요'}
        </span>
        <DownloadButton runId={runId} artifact={artifact} />
      </div>
      {error ? (
        <Notice kind="error" title={error} />
      ) : text === null ? (
        <Loading text="SQL을 불러오는 중이에요" />
      ) : (
        <pre className="code" aria-label={`${KIND_LABEL[kind]} 원문`} tabIndex={0}>
          {text}
        </pre>
      )}
    </div>
  )
}

const VALIDATION_TEXT: Record<NonNullable<ArtifactRef['validation']>['status'], string> = {
  passed: '통과',
  failed: '실패',
  error: '실행 오류',
  unverified: '미검증',
}

/** RTM: 화면 미리보기 표 + 형식별 내려받기 (Excel·CSV가 정식 산출물) */
function RtmTab({ runId, artifacts }: { runId: string; artifacts: ArtifactRef[] }) {
  const [rows, setRows] = useState<RtmRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const files = artifacts.filter((a) => a.kind === 'rtm' && isDownloadable(a))
  const csv = files.find((a) => a.file_format === 'csv')
  useEffect(() => {
    if (!csv) return
    let alive = true
    setRows(null)
    setError(null)
    artifactText(runId, csv).then(parseRtmCsv)
      .then((data) => { if (alive) setRows(data) })
      .catch((err: unknown) => { if (alive) setError(err instanceof RtmFormatError ? '추적표를 미리 보지 못했어요. 파일은 내려받을 수 있어요.' : errorMessage(err)) })
    return () => { alive = false }
  }, [runId, csv, attempt])
  return (
    <div className="stack-sm">
      <div className="row row--between">
        <span className="muted">요구사항 추적표 전체예요. 내려받는 파일과 같아요.</span>
        <div className="row">{files.map((a) => <DownloadButton key={a.file_format} runId={runId} artifact={a} />)}</div>
      </div>
      {!csv ? <Notice kind="warning" title="RTM CSV가 아직 없어요" />
        : error ? <Notice kind="error" title={error} action={<Button onClick={() => setAttempt((n) => n + 1)}>다시 불러오기</Button>} />
        : rows === null ? <Loading text="추적표를 불러오는 중이에요" />
        : <DataTable<RtmRow> label="요구사항 추적표 미리보기" rows={rows} rowKey={(r) => String(rows.indexOf(r))} pageSize={30} minWidth={1500}
            columns={RTM_COLUMNS.map((name) => ({ key: name, title: name, render: (r: RtmRow) => r[name] || '—' }))} />}
    </div>
  )
}

export default WorkspacePanel
