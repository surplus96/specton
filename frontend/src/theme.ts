// 화면 전체의 색·글꼴·크기를 모아 두는 곳. 여기만 고치면 모든 화면이 바뀐다.
//
// 대형 강의장 프로젝터 시연 기준 (A안: 남색 + 파랑):
// - 흰 바탕에 남색 글자. 조명이 켜진 강의장에서도 무너지지 않는다 (어두운 바탕은 프로젝터에서 탁한 회색).
// - 강조는 진한 파랑 면 + 흰 글자(6.7:1). 파랑은 프로젝터에서 색이 가장 덜 틀어진다.
// - 연한 바탕색만으로 구분하지 않는다(연한 파랑도 흰색과 1.2:1이라 프로젝터에서 사라짐). 영역은 테두리로.
// - 상태는 진한 바탕 + 흰 글자, 주의만 연노랑 + 검정 글자. 색과 함께 반드시 글자(차단·완료 등)를 쓴다.
// - 글자는 크게: 기본 17px, 표 16px.
//
// 글씨체·버튼 모양은 Wise 디자인 분석(DESIGN-wise.md)에서 가져왔다. 색은 위 A안 그대로.
// - 글꼴: Pretendard (Wise 본문 글꼴 Inter를 바탕으로 한 한글 글꼴. index.html에서 불러옴)
// - 굵기 두 단계: 큰 제목은 900(아주 굵게), 그 밖의 강조는 600. 본문은 400
// - 버튼: 높이 48px · 모서리 24px(알약 모양) · 좌우 여백 24px · 글자 600
import type { ThemeConfig } from 'antd'

export const colors = {
  primary: '#1d4ed8', // 강조 파랑: 버튼·현재 단계·선택 탭·링크 (흰 글자와 6.7:1, 흰 바탕 위 글자로도 6.7:1)
  primaryStrong: '#1e3a8a', // 더 진한 파랑: 누른 상태·두 번째 강조 면
  primarySoft: '#dbeafe', // 연한 파랑: 선택 칸 바탕. 프로젝터에서 흰색과 구분이 약하니 테두리와 함께 쓴다
  navy: '#0f172a', // 남색: 맨 위 바·아래 띠·큰 제목 면 (흰 글자와 17.9:1)
  onDark: '#ffffff', // 남색·파랑 면 위의 글자
  onDarkMuted: '#bfdbfe', // 남색 면 위의 보조 글자 (남색과 12:1 이상)
  ink: '#0f172a', // 본문 글자 (17.9:1)
  inkMuted: '#334155', // 보조 글자 (10.4:1). 더 흐린 회색은 뒷자리에서 안 보인다
  canvas: '#ffffff', // 카드 바탕
  page: '#ffffff', // 화면 바탕
  border: '#64748b', // 카드·영역 테두리 (흰색과 4.8:1, 1.5px로 써서 프로젝터에서도 보이게)
  line: '#94a3b8', // 표 칸 선
}

/** 상태 표시 색. 진한 바탕 + 흰 글자, 주의만 연노랑 + 검정 글자 (모두 5:1 이상). */
export const tones = {
  danger: { bg: '#b91c1c', fg: '#ffffff' }, // 차단·실패 (6.5:1)
  warning: { bg: '#fde68a', fg: '#0f172a' }, // 주요·확인 필요·초안 (14:1)
  success: { bg: '#15803d', fg: '#ffffff' }, // 완료·정상·승인본 (5.0:1)
  info: { bg: '#1d4ed8', fg: '#ffffff' }, // 진행 중 (6.7:1)
  neutral: { bg: '#e2e8f0', fg: '#0f172a' }, // 참고·대기 (15:1)
} as const

export type Tone = keyof typeof tones

const fontFamily =
  "'Pretendard Variable', Pretendard, system-ui, -apple-system, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif"

/** 글자 굵기 (Wise: 큰 제목 900, 나머지 강조 600) */
export const weights = {
  display: 900, // 첫 화면 큰 제목·화면 제목·카드 제목·이름
  strong: 600, // 소제목·버튼·표 머리·상태 표시
  regular: 400, // 본문
} as const

/** 제목 글자 크기·줄 간격·자간 (Wise 크기 단계를 프로젝터 기준으로 맞춤) */
export const type = {
  hero: { fontSize: 'clamp(56px, 10vw, 112px)', fontWeight: weights.display, lineHeight: 0.95, letterSpacing: '-0.03em' },
  title: { fontSize: 'clamp(30px, 3.6vw, 40px)', fontWeight: weights.display, lineHeight: 1.15, letterSpacing: '-0.02em' },
  section: { fontSize: 'clamp(26px, 3vw, 32px)', fontWeight: weights.display, lineHeight: 1.2, letterSpacing: '-0.02em' },
  card: { fontSize: 28, fontWeight: weights.display, lineHeight: 1.2, letterSpacing: '-0.02em' },
} as const

export const theme: ThemeConfig = {
  token: {
    colorPrimary: colors.primary,
    colorLink: colors.primary,
    colorText: colors.ink,
    colorTextSecondary: colors.inkMuted,
    colorTextTertiary: colors.inkMuted,
    colorTextDescription: colors.inkMuted,
    colorBgLayout: colors.page,
    colorBorder: colors.border,
    colorBorderSecondary: colors.line,
    colorError: tones.danger.bg,
    colorSuccess: tones.success.bg,
    colorWarning: '#b45309', // 경고 아이콘·글자 (흰 바탕 5:1). 경고 바탕은 연노랑을 따로 쓴다
    colorInfo: colors.primary,
    fontFamily,
    fontSize: 17, // 강의장 뒷자리 기준
    fontWeightStrong: weights.strong, // 굵은 글자·소제목 600. 화면 제목은 PageCard에서 900
    fontSizeHeading1: 40,
    fontSizeHeading2: 32,
    fontSizeHeading3: 24,
    fontSizeHeading4: 22,
    fontSizeHeading5: 22, // 카드 안 소제목 (Wise display-xs 24/600에 가깝게)
    lineWidth: 1.5,
    borderRadius: 8,
    borderRadiusLG: 16,
    boxShadow: 'none',
    boxShadowSecondary: 'none',
  },
  components: {
    Button: {
      // Wise 버튼 모양: 높이 48 · 모서리 24(알약) · 좌우 24 · 글자 600. 그림자 없음
      // 주 버튼은 파랑 면 + 흰 글자, 보조 버튼은 흰 면 + 남색 테두리·글자 (Wise tertiary)
      controlHeight: 48,
      controlHeightLG: 56,
      controlHeightSM: 36,
      paddingInline: 24,
      paddingInlineLG: 32,
      paddingInlineSM: 16,
      borderRadius: 24,
      borderRadiusLG: 28,
      borderRadiusSM: 18,
      contentFontSize: 17,
      contentFontSizeLG: 20,
      contentFontSizeSM: 15,
      fontWeight: weights.strong,
      primaryColor: colors.onDark,
      defaultColor: colors.ink,
      defaultBorderColor: colors.ink,
      defaultHoverColor: colors.primary,
      defaultHoverBorderColor: colors.primary,
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
    },
    Layout: {
      headerBg: colors.navy,
      headerHeight: 52,
      headerPadding: '0 24px',
      bodyBg: colors.page,
    },
    Table: {
      cellFontSize: 16,
      headerBg: '#e2e8f0',
      headerColor: colors.ink,
      headerSplitColor: colors.line,
      borderColor: colors.line,
    },
    Tabs: {
      titleFontSize: 18,
      itemSelectedColor: colors.primary,
      inkBarColor: colors.primary,
    },
    Segmented: {
      // 화면 전환(최종 검토·결과 작업공간·다운로드): 고른 쪽을 파랑 면 + 흰 글자로. 기본 흰 칸은 프로젝터에서 안 보인다
      trackBg: '#e2e8f0',
      itemColor: colors.ink,
      itemHoverColor: colors.ink,
      itemSelectedBg: colors.primary,
      itemSelectedColor: colors.onDark,
    },
    Steps: {
      titleLineHeight: 26,
    },
    Alert: {
      withDescriptionPadding: '16px 20px',
    },
  },
}
