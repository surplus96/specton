import { Fragment, useState, type ReactNode } from 'react'

// 표. 표·원문처럼 이어서 읽는 것은 큰 영역에 두고, 넓으면 표 안에서만 가로로 움직인다.
export type Column<T> = {
  key: string
  title: ReactNode
  width?: number
  nowrap?: boolean
  render: (row: T, index: number) => ReactNode
}

type Props<T> = {
  rows: readonly T[]
  columns: readonly Column<T>[]
  rowKey: (row: T) => string
  /** 행을 펼쳐 아래에 더 보일 내용 */
  expand?: (row: T) => ReactNode
  expandLabel?: (row: T, open: boolean) => string
  pageSize?: number
  empty?: ReactNode
  minWidth?: number
  label?: string
  className?: string
}

function DataTable<T>({
  rows,
  columns,
  rowKey,
  expand,
  expandLabel,
  pageSize,
  empty = '내용이 없어요.',
  minWidth = 640,
  label,
  className,
}: Props<T>) {
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const pages = pageSize ? Math.max(1, Math.ceil(rows.length / pageSize)) : 1
  const current = Math.min(page, pages - 1)
  const visible = pageSize ? rows.slice(current * pageSize, (current + 1) * pageSize) : rows

  if (rows.length === 0) return <div className="table-wrap empty">{empty}</div>

  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const colCount = columns.length + (expand ? 1 : 0)

  return (
    <div className={`table-wrap ${className ?? ''}`}>
      <table className="table" style={{ minWidth }} aria-label={label}>
        <thead>
          <tr>
            {expand && <th style={{ width: 44 }} aria-label="펼치기" />}
            {columns.map((c) => (
              <th key={c.key} style={c.width ? { width: c.width } : undefined}>
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, i) => {
            const key = rowKey(row)
            const isOpen = open.has(key)
            return (
              <Fragment key={key}>
                <tr>
                  {expand && (
                    <td>
                      <button
                        type="button"
                        className="icon-btn"
                        style={{ width: 28, height: 28 }}
                        aria-expanded={isOpen}
                        aria-label={expandLabel ? expandLabel(row, isOpen) : isOpen ? '접기' : '펼치기'}
                        onClick={() => toggle(key)}
                      >
                        <span style={{ display: 'inline-block', transform: isOpen ? 'rotate(90deg)' : 'none', transition: 'transform 150ms' }}>
                          ›
                        </span>
                      </button>
                    </td>
                  )}
                  {columns.map((c) => (
                    <td key={c.key} className={c.nowrap ? 'nowrap' : undefined}>
                      {c.render(row, i)}
                    </td>
                  ))}
                </tr>
                {expand && isOpen && (
                  <tr className="sub-row">
                    <td colSpan={colCount}>{expand(row)}</td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
      {pageSize && pages > 1 && (
        <div className="pager">
          <button type="button" className="btn btn--secondary btn--sm" disabled={current === 0} onClick={() => setPage(current - 1)}>
            이전
          </button>
          <span>
            {current + 1} / {pages}
          </span>
          <button type="button" className="btn btn--secondary btn--sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
            다음
          </button>
        </div>
      )}
    </div>
  )
}

export default DataTable
