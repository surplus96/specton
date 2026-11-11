import type { ButtonHTMLAttributes, ReactNode } from 'react'

// 버튼 (디자인 시스템 v0.2 「버튼」)
// - primary: 딥 포레스트 면 + 아이보리 글자. 한 화면에 하나, 다음으로 가는 행동
// - secondary: 흰 바탕 + 선. 수정 요청·보류처럼 다른 선택
// - accent: 라임 면. 지금 눌러야 할 한 개, 또는 어두운 면 위의 기본 버튼
// - 처리 중에는 누르지 못하게 하고 하는 일을 글자로 적는다(loadingText)
type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'accent' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  loadingText?: string
  block?: boolean
  icon?: ReactNode
  iconEnd?: ReactNode
}

function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  loadingText,
  block,
  icon,
  iconEnd,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: Props) {
  const classes = [
    'btn',
    variant !== 'primary' && `btn--${variant}`,
    size !== 'md' && `btn--${size}`,
    block && 'btn--block',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <button type={type} className={classes} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {loading ? <span className="spin" aria-hidden="true" /> : icon}
      {loading && loadingText ? loadingText : children}
      {!loading && iconEnd}
    </button>
  )
}

export default Button
