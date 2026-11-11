import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { workspaceTab, type WorkspaceTab } from './pipeline.ts'
import ResultSummary from './ResultSummary.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import { Alert, Button, Flex, Select, Spin, Tabs, Typography } from 'antd'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus } from '../../api/types.ts'
import type { ArtifactRef, DesignItem, Finding } from '../../api/viewItems.ts'
import PageCard from '../../layout/PageCard.tsx'
import { colors } from '../../theme.ts'
import DesignTables from '../review/DesignTables.tsx'
import FindingsTable from '../review/FindingsTable.tsx'
import { nameIndex } from '../review/rules.ts'
import ErdView from './ErdView.tsx'
import { artifactText, saveArtifact } from './files.ts'
import {
  FORMAT_LABEL,
  KIND_LABEL,
  downloadErrorText,
  isApproved,
  isDownloadable,
  missingKinds,
  revisionOptions,
  toArtifacts,
  type ArtifactKind,
} from './rules.ts'

// UI-05 결과 작업공간 (docs/09): 기능·ERD·DDL·RTM·검토 탭, revision 고르기, 미완성 가지 표시.
// 설계를 직접 고치지는 않는다. 바꾸려면 최종 검토(UI-06)에서 수정을 요청한다 (docs/09 범위 밖).
type Props = {
  run: RunStatus
}

type Loaded = { design: DesignItem[]; findings: Finding[]; artifacts: ArtifactRef[] }

function WorkspacePanel({ run }: Props) {
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
        setData({
          design: design.items as DesignItem[],
          findings: review.items as Finding[],
          artifacts: toArtifacts(design.artifacts),
        })
      })
      .catch((err: unknown) => alive && setLoadError(err))
    return () => {
      alive = false
    }
  }, [run.run_id, revision, reloadKey])

  // 고른 탭은 주소(&tab=)에 둔다. 완료 화면의 파이프라인 카드가 이 탭으로 바로 연다.
  const [params, setParams] = useSearchParams()
  const tab = workspaceTab(params.get('tab'))
  // 탭 바꾸기는 기록을 쌓지 않는다(replace). 뒤로가기가 탭을 하나씩 거슬러 가지 않게
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
  const find = (kind: ArtifactKind, format: ArtifactRef['file_format']) =>
    data?.artifacts.find((a) => a.kind === kind && a.file_format === format)

  return (
    <PageCard title="결과 작업공간" subtitle="설계 결과와 산출물을 탭으로 봅니다. 설계를 바꾸려면 최종 검토에서 수정을 요청하세요.">
      <Flex vertical gap={16}>
        <Flex gap={12} align="center" wrap>
          <Typography.Text>revision</Typography.Text>
          <Select
            aria-label="revision 고르기"
            style={{ width: 160 }}
            value={revision}
            onChange={setRevision}
            options={revisionOptions(run.revision).map((r) => ({
              value: r,
              label: r === run.revision ? `${r} (최신)` : String(r),
            }))}
          />
          {data && data.artifacts.length > 0 && (
            <StatusTag tone={isApproved(data.artifacts) ? 'success' : 'warning'}>
              {isApproved(data.artifacts) ? '승인본' : '초안 (승인 전)'}
            </StatusTag>
          )}
        </Flex>

        {loadError ? (
          <Alert
            type="error"
            showIcon
            title={errorMessage(loadError)}
            action={<Button onClick={() => setReloadKey((k) => k + 1)}>다시 불러오기</Button>}
          />
        ) : !data ? (
          <Flex justify="center" style={{ padding: 32 }}>
            <Spin />
          </Flex>
        ) : (
          <>
            {missing.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`미완성: ${missing.map((k) => KIND_LABEL[k]).join(', ')}`}
                description="이 revision에서 아직 만들어지지 않았거나 생성에 실패한 산출물입니다."
              />
            )}
            <ResultSummary design={data.design} findings={data.findings} />
            <Tabs
              activeKey={tab}
              onChange={(key) => openTab(key as WorkspaceTab)}
              items={[
                {
                  key: 'design',
                  label: <TabLabel text="기능·엔티티·관계" origin="AI 판단" />,
                  children: <DesignTables items={data.design} names={names} />,
                },
                {
                  key: 'erd',
                  label: <TabLabel text="ERD" origin="코드 생성" />,
                  children: <ErdView runId={run.run_id} artifact={find('erd', 'mmd')} />,
                },
                {
                  key: 'ddl',
                  label: <TabLabel text="DDL" origin="코드 생성" />,
                  children: <TextArtifact runId={run.run_id} artifact={find('ddl', 'sql')} kind="ddl" />,
                },
                {
                  key: 'rtm',
                  label: <TabLabel text="RTM" origin="코드 생성" />,
                  children: <FilesOnly runId={run.run_id} artifacts={data.artifacts} kind="rtm" />,
                },
                {
                  key: 'review',
                  label: <TabLabel text={`검토 (${data.findings.length})`} origin="AI 검토 · 규칙" />,
                  children: <FindingsTable findings={data.findings} names={names} />,
                },
              ]}
            />
          </>
        )}
      </Flex>
    </PageCard>
  )
}

/** 글자 산출물(DDL)을 그대로 보이고 내려받게 한다. */
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

  if (!artifact) return <Alert type="warning" showIcon title={`${KIND_LABEL[kind]}이 아직 없습니다 (미완성)`} />
  return (
    <Flex vertical gap={12}>
      <Flex>
        <DownloadButton runId={runId} artifact={artifact} />
      </Flex>
      {error ? (
        <Alert type="error" showIcon title={error} />
      ) : text === null ? (
        <Spin />
      ) : (
        <pre
          aria-label={`${KIND_LABEL[kind]} 원문`}
          style={{
            margin: 0,
            maxHeight: '60vh',
            overflow: 'auto',
            padding: 16,
            background: '#f1f5f9',
            border: `1.5px solid ${colors.line}`,
            color: colors.ink,
            borderRadius: 12,
            fontSize: 13,
            whiteSpace: 'pre',
          }}
        >
          {text}
        </pre>
      )}
    </Flex>
  )
}

/** 화면에서 바로 보이기 어려운 산출물(RTM Excel·CSV)은 형식별로 내려받게만 한다. */
function FilesOnly({ runId, artifacts, kind }: { runId: string; artifacts: ArtifactRef[]; kind: ArtifactKind }) {
  const mine = artifacts.filter((a) => a.kind === kind && isDownloadable(a)) // 승인 전 PDF 후보는 받을 수 없다
  if (mine.length === 0) return <Alert type="warning" showIcon title={`${KIND_LABEL[kind]}이 아직 없습니다 (미완성)`} />
  return (
    <Flex gap={8} wrap>
      {mine.map((a) => (
        <DownloadButton key={a.file_format} runId={runId} artifact={a} />
      ))}
    </Flex>
  )
}

/** 산출물 하나 내려받기 버튼. 실패하면 버튼 아래에 안내한다. */
export function DownloadButton({ runId, artifact }: { runId: string; artifact: ArtifactRef }) {
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
    <Flex vertical gap={4}>
      <Button onClick={click} loading={busy}>
        {FORMAT_LABEL[artifact.file_format]} 내려받기{artifact.approved ? '' : ' (초안)'}
      </Button>
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
    </Flex>
  )
}

export default WorkspacePanel

/**
 * 탭 이름 + 누가 만들었는지. 규칙(CLAUDE.md): LLM은 판단만 하고 ID·SQL·도면·RTM은 코드가 만든다.
 * 발표에서 이 원칙이 화면에 보이게 한다.
 */
function TabLabel({ text, origin }: { text: string; origin: string }): ReactNode {
  const ai = origin.startsWith('AI')
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      {text}
      <span
        style={{
          fontSize: 13,
          fontWeight: 600,
          padding: '1px 8px',
          borderRadius: 999,
          border: `1.5px solid ${ai ? colors.primary : colors.border}`,
          color: ai ? colors.primary : colors.inkMuted,
        }}
      >
        {origin}
      </span>
    </span>
  )
}
