import { useEffect, useState } from 'react'
import StatusTag from '../../layout/StatusTag.tsx'
import { useNavigate, useSearchParams } from 'react-router'
import { Alert, Button, Flex, Spin, Table, Tooltip, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus } from '../../api/types.ts'
import type { ArtifactRef, DesignItem, Finding } from '../../api/viewItems.ts'
import PageCard from '../../layout/PageCard.tsx'
import DownloadAll from './DownloadAll.tsx'
import Pipeline from './Pipeline.tsx'
import ResultSummary from './ResultSummary.tsx'
import type { WorkspaceTab } from './pipeline.ts'
import { DownloadButton } from './WorkspacePanel.tsx'
import {
  FORMAT_LABEL,
  KIND_LABEL,
  downloadRows,
  isApproved,
  toArtifacts,
  type DownloadRow,
} from './rules.ts'

// UI-07 다운로드 (docs/09): 형식별 다운로드·승인 상태. 이전 실행 목록은 UI-01 실행 시작 화면으로 옮겼다(RecentRuns).
// 생성 대기·파일 없음·접근 불가는 칸마다 안내한다. 초안 파일 이름에는 서버가 -draft를 붙인다 (docs/06).
// 위쪽에 결과 요약 숫자와 산출물 파이프라인(요구사항 → … → RTM)을 둔다. 카드를 누르면 결과 작업공간 탭으로 간다.
type Props = {
  run: RunStatus
}

function DownloadPanel({ run }: Props) {
  const navigate = useNavigate()
  const [, setParams] = useSearchParams()
  const [artifacts, setArtifacts] = useState<ArtifactRef[] | null>(null)
  const [design, setDesign] = useState<DesignItem[]>([])
  // null: 검토 지적을 불러오지 못함 (요약의 지적 칸만 비우고 다운로드는 그대로)
  const [findings, setFindings] = useState<Finding[] | null>([])
  const [loadError, setLoadError] = useState<unknown>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let alive = true
    setArtifacts(null)
    setLoadError(null)
    // 다운로드에 필요한 것은 design(산출물 목록)뿐이다. review는 요약 카드용이라 따로 받고 실패해도 파일은 받을 수 있다
    getView(run.run_id, 'design', run.revision)
      .then((designView) => {
        if (!alive) return
        setDesign(designView.items as DesignItem[])
        setArtifacts(toArtifacts(designView.artifacts))
      })
      .catch((err: unknown) => alive && setLoadError(err))
    getView(run.run_id, 'review', run.revision)
      .then((reviewView) => alive && setFindings(reviewView.items as Finding[]))
      .catch(() => alive && setFindings(null))
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, reloadKey])

  const approved = artifacts ? isApproved(artifacts) : false

  function openWorkspace(tab: WorkspaceTab) {
    setParams((p) => {
      const q = new URLSearchParams(p)
      q.set('view', 'workspace')
      q.set('tab', tab)
      return q
    })
  }

  const fileColumns: TableColumnsType<DownloadRow> = [
    { title: '산출물', key: 'kind', width: 160, render: (_, r) => KIND_LABEL[r.kind] },
    {
      title: '내려받기',
      key: 'files',
      render: (_, r) => (
        <Flex gap={8} wrap>
          {r.files.map(({ format, file }) =>
            file.state === 'ready' ? (
              <DownloadButton key={format} runId={run.run_id} artifact={file.artifact} />
            ) : (
              <Tooltip
                key={format}
                title={file.state === 'needs-approval' ? 'PDF는 승인한 뒤에 만들어집니다.' : '아직 만들어지지 않았습니다.'}
              >
                <Button disabled>
                  {FORMAT_LABEL[format]} · {file.state === 'needs-approval' ? '승인 후' : '없음'}
                </Button>
              </Tooltip>
            ),
          )}
        </Flex>
      ),
    },
  ]


  return (
    <PageCard
      title="다운로드"
      subtitle={`revision ${run.revision} 산출물을 형식별로 내려받습니다.`}
      actions={
        // 끝난 실행에서 바로 다음 문서로. 이 실행은 실행 시작 화면의 「이전 실행」 목록에서 다시 열 수 있다
        <Button type="primary" size="large" onClick={() => navigate('/start')}>
          새 문서로 시작
        </Button>
      }
    >
      <Flex vertical gap={24}>
        {loadError ? (
          <Alert
            type="error"
            showIcon
            title={errorMessage(loadError)}
            action={<Button onClick={() => setReloadKey((k) => k + 1)}>다시 불러오기</Button>}
          />
        ) : !artifacts ? (
          <Flex justify="center">
            <Spin />
          </Flex>
        ) : (
          <>
            <ResultSummary design={design} findings={findings} />
            <section aria-label="산출물 흐름">
              <Typography.Title level={5}>산출물 파이프라인</Typography.Title>
              <Typography.Paragraph type="secondary" style={{ marginTop: -4 }}>
                카드를 누르면 결과 작업공간에서 내용을 봅니다.
              </Typography.Paragraph>
              <Pipeline design={design} artifacts={artifacts} onOpen={openWorkspace} />
            </section>
            <section aria-label="산출물">
              <Flex gap={8} align="center" style={{ marginBottom: 12 }}>
                <Typography.Title level={5} style={{ margin: 0 }}>
                  산출물
                </Typography.Title>
                <StatusTag tone={approved ? 'success' : 'warning'}>{approved ? '승인본' : '초안 (승인 전)'}</StatusTag>
              </Flex>
              {!approved && (
                <Alert
                  style={{ marginBottom: 12 }}
                  type="info"
                  showIcon
                  title="승인 전 파일은 초안입니다."
                  description="파일 이름 끝에 -draft가 붙고, PDF는 승인한 뒤에 만들어집니다."
                />
              )}
              <DownloadAll runId={run.run_id} artifacts={artifacts} />
              <Table
                rowKey="kind"
                size="small"
                pagination={false}
                columns={fileColumns}
                dataSource={downloadRows(artifacts, approved)}
              />
            </section>
          </>
        )}

      </Flex>
    </PageCard>
  )
}

export default DownloadPanel
