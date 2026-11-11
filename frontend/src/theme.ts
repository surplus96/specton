// 화면 디자인 값은 index.css :root에서 관리한다. TS는 CSS 변수만 참조한다.

export const colors = {
  forest: 'var(--forest)',
  lime: 'var(--lime)',
  ivory: 'var(--ivory)',
  ink: 'var(--ink)',
  inkMuted: 'var(--ink-muted)',
  inkSubtle: 'var(--ink-subtle)',
  page: 'var(--page)',
  canvas: 'var(--page)',
  soft: 'var(--soft)',
  line: 'var(--line)',
  border: 'var(--border)',
}

/** 상태 표시 색 (칩). 진한 면 + 밝은 글자 또는 연한 면 + 진한 글자. 모두 글자와 함께 쓴다. */
export const tones = {
  danger: { bg: 'var(--tones-danger-bg)', fg: 'var(--tones-danger-fg)' }, // 차단·실패
  warning: { bg: 'var(--tones-warning-bg)', fg: 'var(--tones-warning-fg)' }, // 주요·확인 필요·초안
  success: { bg: 'var(--tones-success-bg)', fg: 'var(--tones-success-fg)' }, // 완료·승인본
  info: { bg: 'var(--tones-info-bg)', fg: 'var(--tones-info-fg)' }, // 진행 중
  neutral: { bg: 'var(--tones-neutral-bg)', fg: 'var(--tones-neutral-fg)' }, // 참고·대기
} as const

export type Tone = keyof typeof tones

/** AI Workspace(/workspace, 개발용)의 어두운 캔버스 색. 딥 포레스트 바탕 + 아이보리 글자 + 라임 강조. */
export const dark = {
  page: 'var(--dark-page)',
  panel: 'var(--dark-panel)',
  canvas: 'var(--dark-canvas)',
  card: 'var(--dark-card)',
  cardHover: 'var(--dark-card-hover)',
  border: 'var(--dark-border)',
  line: 'var(--dark-line)',
  ink: 'var(--dark-ink)',
  inkMuted: 'var(--dark-ink-muted)',
  accent: 'var(--dark-accent)',
  focus: 'var(--dark-focus)',
}

/** 실행 단계 노드 상태 색 (어두운 바탕용). 아이콘·글자를 함께 보인다. */
export const darkTones = {
  waiting: { fg: 'var(--darktones-waiting-fg)', border: 'var(--darktones-waiting-border)' },
  running: { fg: 'var(--darktones-running-fg)', border: 'var(--darktones-running-border)' },
  awaiting: { fg: 'var(--darktones-awaiting-fg)', border: 'var(--darktones-awaiting-border)' },
  done: { fg: 'var(--darktones-done-fg)', border: 'var(--darktones-done-border)' },
  failed: { fg: 'var(--darktones-failed-fg)', border: 'var(--darktones-failed-border)' },
  skipped: { fg: 'var(--darktones-skipped-fg)', border: 'var(--darktones-skipped-border)' },
  cancelled: { fg: 'var(--darktones-cancelled-fg)', border: 'var(--darktones-cancelled-border)' },
} as const

/** 글자 굵기 */
export const weights = {
  display: 800,
  strong: 600,
  regular: 400,
} as const
