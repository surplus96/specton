import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Alert, Button, Flex, Spin, Table, Tag, Tooltip, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { getView, listRuns } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus, RunSummary } from '../../api/types.ts'
import type { ArtifactRef } from '../../api/viewItems.ts'
import PageCard from '../../layout/PageCard.tsx'
import { DownloadButton } from './WorkspacePanel.tsx'
import {
  FORMAT_LABEL,
  KIND_LABEL,
  STATUS_LABEL,
  downloadRows,
  isApproved,
  shortTime,
  toArtifacts,
  type DownloadRow,
} from './rules.ts'

// UI-07 다운로드·이력 (docs/09): 형식별 다운로드·승인 상태, 이전 실행.
// 생성 대기·파일 없음·접근 불가는 칸마다 안내한다. 초안 파일 이름에는 서버가 -draft를 붙인다 (docs/06).
type Props = {
  run: RunStatus
}

function DownloadPanel({ run }: Props) {
  const navigate = useNavigate()
  const [artifacts, setArtifacts] = useState<ArtifactRef[] | null>(null)
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let alive = true
    setArtifacts(null)
    setLoadError(null)
    getView(run.run_id, 'design', run.revision)
      .then((v) => alive && setArtifacts(toArtifacts(v.artifacts)))
      .catch((err: unknown) => alive && setLoadError(err))
    listRuns({ limit: 20 })
      .then((list) => alive && setRuns(list))
      .catch(() => alive && setRuns([])) // 이력은 보조 정보라 실패해도 다운로드는 보인다
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, reloadKey])

  const approved = artifacts ? isApproved(artifacts) : false

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

  const runColumns: TableColumnsType<RunSummary> = [
    { title: '시작', dataIndex: 'created_at', width: 120, render: (t: string) => shortTime(t) },
    {
      title: '상태',
      dataIndex: 'status',
      width: 140,
      render: (s: RunSummary['status']) => <Tag color={s === 'completed' ? 'green' : s === 'failed' ? 'red' : 'default'}>{STATUS_LABEL[s]}</Tag>,
    },
    { title: 'revision', dataIndex: 'revision', width: 90 },
    {
      title: '실행 ID',
      dataIndex: 'run_id',
      render: (id: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {id}
        </Typography.Text>
      ),
    },
    {
      title: '',
      key: 'open',
      width: 90,
      render: (_, r) =>
        r.run_id === run.run_id ? (
          <Typography.Text type="secondary">지금 실행</Typography.Text>
        ) : (
          <Button size="small" onClick={() => navigate(`/?run=${encodeURIComponent(r.run_id)}`)}>
            열기
          </Button>
        ),
    },
  ]

  return (
    <PageCard title="다운로드" subtitle={`revision ${run.revision} 산출물을 형식별로 내려받습니다.`}>
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
          <section aria-label="산출물">
            <Flex gap={8} align="center" style={{ marginBottom: 12 }}>
              <Typography.Title level={5} style={{ margin: 0 }}>
                산출물
              </Typography.Title>
              <Tag color={approved ? 'green' : 'orange'}>{approved ? '승인본' : '초안 (승인 전)'}</Tag>
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
            <Table
              rowKey="kind"
              size="small"
              pagination={false}
              columns={fileColumns}
              dataSource={downloadRows(artifacts, approved)}
            />
          </section>
        )}

        <section aria-label="이전 실행">
          <Typography.Title level={5}>이전 실행</Typography.Title>
          {runs === null ? (
            <Spin />
          ) : runs.length === 0 ? (
            <Typography.Text type="secondary">이전 실행이 없습니다.</Typography.Text>
          ) : (
            <Table rowKey="run_id" size="small" pagination={false} columns={runColumns} dataSource={runs} />
          )}
        </section>
      </Flex>
    </PageCard>
  )
}

export default DownloadPanel
