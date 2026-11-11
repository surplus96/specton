import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus } from '../../api/types.ts'
import type { AnalysedRequirement, ArtifactRef, DesignItem, Finding } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import Button from '../../ui/Button.tsx'
import DataTable from '../../ui/DataTable.tsx'
import Loading from '../../ui/Loading.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import Tabs from '../../ui/Tabs.tsx'
import DesignTables from '../review/DesignTables.tsx'
import FindingsTable from '../review/FindingsTable.tsx'
import { nameIndex } from '../review/rules.ts'
import DownloadButton from './DownloadButton.tsx'
import ErdView from './ErdView.tsx'
import { artifactText } from './files.ts'
import { workspaceTab, type WorkspaceTab } from './pipeline.ts'
import ResultSummary from './ResultSummary.tsx'
import { rtmRows, type RtmRow } from './rtm.ts'
import { KIND_LABEL, downloadErrorText, isApproved, isDownloadable, missingKinds, revisionOptions, toArtifacts, type ArtifactKind } from './rules.ts'

// UI-05 결과 작업공간: 기능·ERD·DDL·RTM·검토 탭, revision 고르기, 미완성 가지 표시.
// 설계를 직접 고치지는 않는다. 바꾸려면 최종 검토(UI-06)에서 수정을 요청한다.
// 탭마다 누가 만들었는지(AI 판단 / 코드 생성)를 보인다: LLM은 판단만, ID·SQL·도면·RTM은 코드가 만든다.
type Props = {
  run: RunStatus
  label: string
  /** 최종 검토 대기 중이면 「최종 검토로」 버튼 */
  onReview?: () => void
}

type Loaded = { design: DesignItem[]; findings: Finding[]; artifacts: ArtifactRef[] }

const ORIGIN: Record<WorkspaceTab, string> = {
  design: 'AI 판단',
  erd: '코드 생성',
  ddl: '코드 생성',
  rtm: '코드 생성',
  review: 'AI 검토 · 규칙',
}

function WorkspacePanel({ run, label, onReview }: Props) {
  const [revision, setRevision] = useState(run.revision)
  const [data, setData] = useState<Loaded | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => setRevision(run.revision), [run.revision])

  useEffect(() => {
    let alive = true
    setData(null)
    setLoadError(null)
    Promise.all([getView(run.run_id, 'design', revision), getView(run.run_id, 'review', revision)])
      .then(([design, review]) => {
        if (!alive) return
        setData({ design: design.items as DesignItem[], findings: review.items as Finding[], artifacts: toArtifacts(design.artifacts) })
      })
      .catch((err: unknown) => alive && setLoadError(err))
    return () => {
      alive = false
    }
  }, [run.run_id, revision, reloadKey])

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
        eyebrow={`결과 작업공간 · ${label}`}
        title={
          <>
            <strong>설계 초안</strong>이 준비됐어요
          </>
        }
        lead="설계 결과와 산출물을 탭으로 봐요. 설계를 바꾸려면 최종 검토에서 수정을 요청하세요."
        actions={
          onReview && (
            <Button variant="accent" size="lg" onClick={onReview} iconEnd={<Icon name="arrowRight" size={18} />}>
              최종 검토로
            </Button>
          )
        }
      />

      <div className="row">
        <label htmlFor="revision" className="muted">
          revision
        </label>
        <select id="revision" className="select" style={{ width: 160 }} value={revision} onChange={(e) => setRevision(Number(e.target.value))}>
          {revisionOptions(run.revision).map((r) => (
            <option key={r} value={r}>
              {r === run.revision ? `${r} (최신)` : r}
            </option>
          ))}
        </select>
        {data && data.artifacts.length > 0 && (
          <StatusTag tone={isApproved(data.artifacts) ? 'success' : 'warning'}>{isApproved(data.artifacts) ? '승인본' : '초안 (승인 전)'}</StatusTag>
        )}
      </div>

      {loadError ? (
        <Notice kind="error" title={errorMessage(loadError)} action={<Button variant="secondary" size="sm" onClick={() => setReloadKey((k) => k + 1)}>다시 불러오기</Button>} />
      ) : !data ? (
        <Loading text="설계 결과를 불러오는 중이에요" />
      ) : (
        <>
          {missing.length > 0 && (
            <Notice kind="warning" title={`미완성: ${missing.map((k) => KIND_LABEL[k]).join(', ')}`}>
              이 revision에서 아직 만들어지지 않았거나 생성에 실패한 산출물이에요.
            </Notice>
          )}
          <ResultSummary design={data.design} findings={data.findings} />
          <Tabs<WorkspaceTab>
            label="결과 탭"
            active={tab}
            onChange={openTab}
            extra={<span className="badge">{ORIGIN[tab]}</span>}
            items={[
              { key: 'design', label: '기능', content: <DesignTables items={data.design} names={names} /> },
              { key: 'erd', label: 'ERD', content: <ErdView runId={run.run_id} artifact={find('erd', 'mmd')} /> },
              { key: 'ddl', label: 'DDL', content: <TextArtifact runId={run.run_id} artifact={find('ddl', 'sql')} kind="ddl" /> },
              { key: 'rtm', label: 'RTM', content: <RtmTab runId={run.run_id} revision={revision} design={data.design} artifacts={data.artifacts} names={names} /> },
              { key: 'review', label: `검토 ${data.findings.length}`, content: <FindingsTable findings={data.findings} names={names} /> },
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

  if (!artifact) return <Notice kind="warning" title={`${KIND_LABEL[kind]}이 아직 없어요 (미완성)`} />
  return (
    <div className="stack-sm" style={{ gap: 14 }}>
      <div className="row row--between">
        <span className="muted" style={{ fontSize: 14 }}>
          {artifact.validation ? `SQL 검증: ${VALIDATION_TEXT[artifact.validation.status]}` : 'SQL 검증 결과는 최종 검토에서 확인해요'}
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
function RtmTab({
  runId,
  revision,
  design,
  artifacts,
  names,
}: {
  runId: string
  revision: number
  design: DesignItem[]
  artifacts: ArtifactRef[]
  names: Map<string, string>
}) {
  // 엔티티 ID는 서버가 해시로 붙여 길다(ENT-98727d…). 화면에는 이름을 먼저, ID는 마우스를 올리면 보인다
  const label = (id: string) => (
    <span key={id} title={id}>
      {names.get(id) ?? id}
    </span>
  )
  const join = (ids: string[]) =>
    ids.length === 0 ? '—' : ids.flatMap((id, i) => (i === 0 ? [label(id)] : [<span key={`${id}-sep`}> · </span>, label(id)]))
  const [reqIds, setReqIds] = useState<string[] | null | undefined>(undefined)
  const files = artifacts.filter((a) => a.kind === 'rtm' && isDownloadable(a)) // 승인 전 PDF 후보는 받을 수 없다

  useEffect(() => {
    let alive = true
    getView(runId, 'requirements', revision)
      .then((v) => alive && setReqIds((v.items as AnalysedRequirement[]).map((r) => r.id)))
      .catch(() => alive && setReqIds(null)) // 못 읽으면 설계에 있는 요구사항만으로 보인다
    return () => {
      alive = false
    }
  }, [runId, revision])

  const rows = useMemo(() => rtmRows(design, reqIds ?? undefined), [design, reqIds])

  return (
    <div className="stack-sm" style={{ gap: 14 }}>
      <div className="row row--between">
        <span className="muted" style={{ fontSize: 14 }}>
          화면 미리보기예요. 정식 추적표는 아래 파일이에요.
        </span>
        <div className="row">
          {files.length === 0 ? (
            <StatusTag tone="warning">RTM 파일 없음 (미완성)</StatusTag>
          ) : (
            files.map((a) => <DownloadButton key={a.file_format} runId={runId} artifact={a} />)
          )}
        </div>
      </div>
      {reqIds === undefined ? (
        <Loading text="요구사항을 불러오는 중이에요" />
      ) : (
        <DataTable<RtmRow>
          label="RTM 미리보기"
          rows={rows}
          rowKey={(r) => r.reqId}
          pageSize={30}
          minWidth={720}
          empty="연결할 요구사항이 없어요."
          columns={[
            { key: 'req', title: '요구사항', width: 140, render: (r) => <strong className="mono">{r.reqId}</strong> },
            { key: 'fn', title: '기능', render: (r) => join(r.functions) },
            { key: 'ent', title: '엔티티', render: (r) => join(r.entities) },
            {
              key: 'state',
              title: '상태',
              width: 110,
              render: (r): ReactNode => (r.linked ? '연결됨' : <StatusTag tone="warning">미연결</StatusTag>),
            },
          ]}
        />
      )}
    </div>
  )
}

export default WorkspacePanel
