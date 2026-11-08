// 화면 전체의 색·글꼴·크기를 모아 두는 곳. 여기만 고치면 모든 화면이 바뀐다.
//
// 대형 강의장 프로젝터 시연 기준 (A안: 남색 + 파랑):
// - 흰 바탕에 남색 글자. 조명이 켜진 강의장에서도 무너지지 않는다 (어두운 바탕은 프로젝터에서 탁한 회색).
// - 강조는 진한 파랑 면 + 흰 글자(6.7:1). 파랑은 프로젝터에서 색이 가장 덜 틀어진다.
// - 연한 바탕색만으로 구분하지 않는다(연한 파랑도 흰색과 1.2:1이라 프로젝터에서 사라짐). 영역은 테두리로.
// - 상태는 진한 바탕 + 흰 글자, 주의만 연노랑 + 검정 글자. 색과 함께 반드시 글자(차단·완료 등)를 쓴다.
// - 글자는 크게: 기본 17px, 표 16px.
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
  "system-ui, -apple-system, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif"

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
    lineWidth: 1.5,
    borderRadius: 8,
    borderRadiusLG: 16,
    boxShadow: 'none',
    boxShadowSecondary: 'none',
  },
  components: {
    Button: {
      // 알약 모양, 그림자 없음, 파랑 면에 흰 글자
      borderRadius: 980,
      borderRadiusLG: 980,
      borderRadiusSM: 980,
      primaryColor: colors.onDark,
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
      fontWeight: 600,
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
