// 화면 전체의 색·글자 값. CSS 변수(index.css :root)와 같은 값을 TS에서도 쓸 수 있게 모아 둔다.
//
// 기준: SPECTON 디자인 시스템 v0.2 + F안 시안 (Figma Make 「SPECTON Service」)
// - 기준 색 세 개: 딥 포레스트 #18211A(글자·어두운 면·기본 버튼), 라임 #D7FF4F(강조 한 곳), 아이보리 #F3F2E9
// - 작업 화면 바탕은 시안대로 흰색, 사이드바는 딥 포레스트
// - 라임은 글자색으로 쓰지 않는다(흰 바탕 대비 1.02배). 면·점·표시로만 쓴다
// - 상태는 색만으로 구분하지 않고 항상 글자를 함께 쓴다

export const colors = {
  forest: '#18211A',
  lime: '#D7FF4F',
  ivory: '#F3F2E9',
  ink: '#18211A',
  inkMuted: '#5F665F',
  inkSubtle: '#8A9089',
  page: '#FFFFFF',
  canvas: '#FFFFFF',
  soft: '#F2F4F1',
  line: '#E3E6E1',
  border: '#CDD2CB',
}

/** 상태 표시 색 (칩). 진한 면 + 밝은 글자 또는 연한 면 + 진한 글자. 모두 글자와 함께 쓴다. */
export const tones = {
  danger: { bg: '#A8453B', fg: '#FFFFFF' }, // 차단·실패
  warning: { bg: '#F4E6BC', fg: '#4A3606' }, // 주요·확인 필요·초안
  success: { bg: '#2F6B43', fg: '#FFFFFF' }, // 완료·승인본
  info: { bg: '#18211A', fg: '#F3F2E9' }, // 진행 중
  neutral: { bg: '#ECEEEA', fg: '#18211A' }, // 참고·대기
} as const

export type Tone = keyof typeof tones

/** AI Workspace(/workspace, 개발용)의 어두운 캔버스 색. 딥 포레스트 바탕 + 아이보리 글자 + 라임 강조. */
export const dark = {
  page: '#111812',
  panel: '#18211A',
  canvas: '#141C16',
  card: '#1F2A22',
  cardHover: '#27332A',
  border: '#33413A',
  line: '#56645A',
  ink: '#F3F2E9',
  inkMuted: '#B7BCB0',
  accent: '#D7FF4F',
  focus: '#D7FF4F',
}

/** 실행 단계 노드 상태 색 (어두운 바탕용). 아이콘·글자를 함께 보인다. */
export const darkTones = {
  waiting: { fg: '#B7BCB0', border: '#56645A' },
  running: { fg: '#D7FF4F', border: '#D7FF4F' },
  awaiting: { fg: '#F2C14E', border: '#F2C14E' },
  done: { fg: '#8FD19E', border: '#8FD19E' },
  failed: { fg: '#F08A7E', border: '#F08A7E' },
  skipped: { fg: '#B7BCB0', border: '#56645A' },
  cancelled: { fg: '#D5D8CF', border: '#6B756C' },
} as const

/** 글자 굵기 */
export const weights = {
  display: 800,
  strong: 600,
  regular: 400,
} as const
