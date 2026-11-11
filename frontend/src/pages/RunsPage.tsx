import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { runFileName, titleFromFile } from '../api/runNames.ts'
import type { RunState, RunSummary } from '../api/types.ts'
import Icon from '../layout/Icon.tsx'
import StatusTag from '../layout/StatusTag.tsx'
import Button from '../ui/Button.tsx'
import DataTable from '../ui/DataTable.tsx'
import Segmented from '../ui/Segmented.tsx'
import Loading from '../ui/Loading.tsx'
import Notice from '../ui/Notice.tsx'
import { dotDateTime, matchesQuery, revisionBadge, runBadge } from './runMeta.ts'
import { useRuns } from './useRuns.ts'

// 지난 작업 · 작업 검색 (/history). 이 브라우저 세션이 시작한 실행만 서버가 돌려준다(ADR-0011).
// 검색 API는 없어서 받아 온 목록(최근 100개)을 화면에서 거른다: 파일 이름(이 브라우저에서 올린 것)·상태·날짜·실행 ID.
type Filter = 'all' | 'awaiting' | 'running' | 'completed' | 'stopped'

const FILTERS: { value: Filter; label: string; match: (s: RunState) => boolean }[] = [
  { value: 'all', label: '전체', match: () => true },
  { value: 'awaiting', label: '확인 필요', match: (s) => s.startsWith('awaiting') },
  {
    value: 'running',
    label: '진행 중',
    match: (s) => ['queued', 'parsing', 'analysing', 'designing', 'generating', 'reviewing', 'exporting', 'cancel_requested'].includes(s),
  },
  { value: 'completed', label: '완료', match: (s) => s === 'completed' },
  { value: 'stopped', label: '멈춘 작업', match: (s) => s === 'failed' || s === 'cancelled' },
]

function RunsPage() {
  const [params, setParams] = useSearchParams()
  const { runs, failed, reload } = useRuns(100)
  const query = params.get('q') ?? ''
  const [filter, setFilter] = useState<Filter>('all')
  const search = useRef<HTMLInputElement>(null)
  const searching = params.get('search') === '1'

  useEffect(() => {
    if (searching) search.current?.focus()
  }, [searching])

  const shown = useMemo(() => {
    const f = FILTERS.find((x) => x.value === filter)!
    return (runs ?? []).filter((r) => f.match(r.status) && matchesQuery(r, runFileName(r.run_id), query))
  }, [runs, filter, query])

  function onQuery(value: string) {
    setParams(
      (p) => {
        const q = new URLSearchParams(p)
        if (value) q.set('q', value)
        else q.delete('q')
        return q
      },
      { replace: true },
    )
  }

  return (
    <div className="screen">
      <header className="screen-head">
        <div>
          <p className="eyebrow">{searching ? '작업 검색' : '지난 작업'}</p>
          <h1 className="title">
            지금까지의 <strong>작업</strong>
          </h1>
          <p className="lead">이 브라우저에서 시작한 작업만 보여요. 누르면 그 작업으로 돌아가요.</p>
        </div>
        <Button variant="secondary" icon={<Icon name="refresh" size={16} />} onClick={reload}>
          새로고침
        </Button>
      </header>

      <div className="row" style={{ marginBottom: 20 }}>
        <div className="search">
          <Icon name="search" size={18} />
          <input
            ref={search}
            className="input"
            type="search"
            placeholder="파일 이름, 상태, 날짜로 찾기"
            aria-label="작업 검색"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
          />
        </div>
        <Segmented<Filter> label="상태로 거르기" size="sm" value={filter} onChange={setFilter}
          options={FILTERS.map((f) => ({ value: f.value, label: f.label }))} />
      </div>

      {failed ? (
        <Notice kind="warning" title="지난 작업을 불러오지 못했어요." action={<Button variant="secondary" size="sm" onClick={reload}>다시 시도</Button>}>
          잠시 후 다시 시도해 주세요. 새 작업은 그대로 시작할 수 있어요.
        </Notice>
      ) : runs === null ? (
        <Loading text="지난 작업을 불러오는 중이에요" />
      ) : runs.length === 0 ? (
        <div className="card empty">
          <p style={{ margin: '0 0 16px' }}>아직 시작한 작업이 없어요.</p>
          <Link to="/" className="btn">
            새 작업 시작
          </Link>
        </div>
      ) : (
        <DataTable<RunSummary>
          key={`${query}:${filter}`}
          className="runs-table"
          label="지난 작업"
          rows={shown}
          rowKey={(r) => r.run_id}
          pageSize={20}
          empty="찾는 작업이 없어요. 검색어나 상태를 바꿔 보세요."
          columns={[
            {
              key: 'name',
              title: '작업',
              render: (r) => {
                const file = runFileName(r.run_id)
                return (
                  <div className="stack-sm" style={{ gap: 2 }}>
                    <Link to={`/?run=${encodeURIComponent(r.run_id)}`}>
                      {file ? titleFromFile(file) : '이름 없는 작업'}
                    </Link>
                    <span className="subtle" style={{ fontSize: 13 }}>
                      {file ?? '이 브라우저에 파일 이름이 저장되어 있지 않아요'}
                    </span>
                  </div>
                )
              },
            },
            {
              key: 'status',
              title: '상태',
              width: 130,
              render: (r) => {
                const b = runBadge(r.status)
                return (
                  <StatusTag tone={b.tone} dot={b.dot}>
                    {b.text}
                  </StatusTag>
                )
              },
            },
            { key: 'rev', title: '설계안', width: 90, render: (r) => revisionBadge(r.revision) },
            { key: 'at', title: '시작', width: 160, nowrap: true, render: (r) => dotDateTime(r.created_at) },
            {
              key: 'open',
              title: '',
              width: 90,
              render: (r) => (
                <Link className="btn btn--secondary btn--sm" to={`/?run=${encodeURIComponent(r.run_id)}`}>
                  열기
                </Link>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}

export default RunsPage
