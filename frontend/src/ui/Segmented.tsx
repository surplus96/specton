import type { ReactNode } from 'react'

// 여러 개 중 하나 고르기. variant 'segmented'는 회색 칸 안의 흰 칩, 'choice'는 표 안의 작은 결정 버튼.
type Option<V extends string> = { value: V; label: ReactNode; disabled?: boolean; title?: string }

type Props<V extends string> = {
  options: readonly Option<V>[]
  value: V | null
  onChange: (value: V) => void
  label: string
  variant?: 'segmented' | 'choice'
  size?: 'sm' | 'md'
  disabled?: boolean
}

function Segmented<V extends string>({ options, value, onChange, label, variant = 'segmented', size = 'md', disabled }: Props<V>) {
  const cls = variant === 'choice' ? 'choice' : `segmented${size === 'sm' ? ' segmented--sm' : ''}`
  return (
    <div className={cls} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          disabled={disabled || o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export default Segmented
