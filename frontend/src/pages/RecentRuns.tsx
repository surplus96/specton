import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Button, Spin, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { listRuns } from '../api/client.ts'
import type { RunSummary } from '../api/types.ts'
import StatusTag from '../layout/StatusTag.tsx'
import { STATUS_LABEL, shortTime } from './workspace/rules.ts'

// 이전 실행 목록. UI-01 실행 시작 화면의 「설계 시작」 아래에 둔다 (docs/09).
// 이 브라우저 세션이 시작한 실행만 서버가 돌려준다(ADR-0011). 이력은 보조 정보라 불러오지 못해도 화면은 그대로 쓴다.
function RecentRuns() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<RunSummary[] | null>(null)

  useEffect(() => {
    let alive = true
    listRuns({ limit: 20 })
      .then((list) => alive && setRuns(list))
      .catch(() => alive && setRuns([]))
    return () => {
      alive = false
    }
  }, [])

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
      {runs === null ? (
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
