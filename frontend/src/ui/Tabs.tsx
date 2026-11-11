import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

// 탭. 고른 탭 아래에 선이 생긴다. 화살표 키로 옮길 수 있다.
export type TabItem<K extends string> = { key: K; label: ReactNode; content: ReactNode }

type Props<K extends string> = {
  items: readonly TabItem<K>[]
  active: K
  onChange: (key: K) => void
  label: string
  extra?: ReactNode
}

function Tabs<K extends string>({ items, active, onChange, label, extra }: Props<K>) {
  const id = useId()
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const index = Math.max(0, items.findIndex((t) => t.key === active))
  const current = items[index]

  function onKey(e: KeyboardEvent) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const next = (index + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length
    onChange(items[next].key)
    refs.current[next]?.focus()
  }

  return (
    <div>
      <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKey}>
        {items.map((t, i) => (
          <button
            key={t.key}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${t.key}`}
            aria-selected={t.key === current?.key}
            aria-controls={`${id}-panel`}
            tabIndex={t.key === current?.key ? 0 : -1}
            className="tab"
            onClick={() => onChange(t.key)}
          >
            {t.label}
          </button>
        ))}
        {extra && <div className="tabs__extra">{extra}</div>}
      </div>
      <div className="tab-panel screen" key={current?.key} role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${current?.key}`}>
        {current?.content}
      </div>
    </div>
  )
}

export default Tabs
