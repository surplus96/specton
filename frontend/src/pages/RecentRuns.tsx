import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Alert, Button, Spin, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { listRuns } from '../api/client.ts'
import type { RunSummary } from '../api/types.ts'
import StatusTag from '../layout/StatusTag.tsx'
import { STATUS_LABEL, shortTime } from './workspace/rules.ts'

// 이전 실행 목록. UI-01 실행 시작 화면의 「설계 시작」 아래에 둔다 (docs/09).
// 이 브라우저 세션이 시작한 실행만 서버가 돌려준다(ADR-0011). 불러오지 못해도 업로드는 그대로 쓰고,
// 실패는 「없음」과 따로 보인다(끝난 실행으로 돌아가는 길이 이 목록이므로 비어 있다고 읽히면 안 된다).
function RecentRuns() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let alive = true
    setRuns(null)
    setFailed(false)
    listRuns({ limit: 20 })
      .then((list) => alive && setRuns(list))
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [reloadKey])

  const columns: TableColumnsType<RunSummary> = [
    { title: '시작', dataIndex: 'created_at', width: 120, render: (t: string) => shortTime(t) },
    {
      title: '상태',
      dataIndex: 'status',
      width: 140,
      render: (s: RunSummary['status']) => (
        <StatusTag tone={s === 'completed' ? 'success' : s === 'failed' ? 'danger' : 'neutral'}>{STATUS_LABEL[s]}</StatusTag>
      ),
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
      render: (_, r) => (
        <Button size="small" onClick={() => navigate(`/?run=${encodeURIComponent(r.run_id)}`)}>
          열기
        </Button>
      ),
    },
  ]

  return (
    <section aria-label="이전 실행">
      <Typography.Title level={5}>이전 실행</Typography.Title>
      {failed ? (
        <Alert
          type="warning"
          showIcon
          title="이전 실행을 불러오지 못했습니다."
          description="새 문서는 그대로 올릴 수 있습니다."
          action={<Button onClick={() => setReloadKey((k) => k + 1)}>다시 시도</Button>}
        />
      ) : runs === null ? (
        <Spin />
      ) : runs.length === 0 ? (
        <Typography.Text type="secondary">이전 실행이 없습니다.</Typography.Text>
      ) : (
        <Table rowKey="run_id" size="small" pagination={false} columns={columns} dataSource={runs} scroll={{ x: 'max-content' }} />
      )}
    </section>
  )
}

export default RecentRuns
