// 화면 전체의 색·글꼴·모서리를 모아 두는 곳. 여기만 고치면 모든 화면이 바뀐다.
// 색: 한화 오렌지(100%·70%·50%)와 블랙. 그림자·장식 없이 회백색 바탕에 흰 카드를 올린다.
// 글자 대비: 오렌지 바탕에는 검정 글자(7.3:1). 흰 바탕의 작은 오렌지 글자는 진한 오렌지(4.6:1).
import type { ThemeConfig } from 'antd'

export const colors = {
  orange: '#f37321', // 한화 오렌지 100%: 버튼·단계 표시·강조 바탕
  orange70: '#f89b6c', // 한화 오렌지 70%
  orange50: '#fbb584', // 한화 오렌지 50%
  orangeTint: '#fff1e8', // 아주 옅은 오렌지 바탕
  orangeText: '#c2540a', // 흰 바탕 위의 오렌지 글자·링크(읽기 쉬운 진한 오렌지)
  black: '#000000', // 한화 블랙: 맨 위 바, 아래 띠
  ink: '#1d1d1f', // 본문 글자
  inkMuted: '#6e6e73', // 보조 글자
  canvas: '#ffffff', // 카드 바탕
  parchment: '#f5f5f7', // 화면 바탕(회백색)
  hairline: '#e0e0e0', // 얇은 테두리
}

const fontFamily =
  "system-ui, -apple-system, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif"

export const theme: ThemeConfig = {
  token: {
    colorPrimary: colors.orange,
    colorLink: colors.orangeText,
    colorText: colors.ink,
    colorTextSecondary: colors.inkMuted,
    colorBgLayout: colors.parchment,
    colorBorder: colors.hairline,
    colorBorderSecondary: colors.hairline,
    fontFamily,
    fontSize: 15, // 표가 많은 화면이라 15px
    borderRadius: 8,
    borderRadiusLG: 18,
    boxShadow: 'none',
    boxShadowSecondary: 'none',
  },
  components: {
    Button: {
      // 알약 모양 버튼, 그림자 없음, 오렌지 버튼의 글자는 검정
      borderRadius: 980,
      borderRadiusLG: 980,
      borderRadiusSM: 980,
      primaryColor: colors.black,
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
      fontWeight: 600,
    },
    Layout: {
      headerBg: colors.black,
      headerHeight: 44,
      headerPadding: '0 24px',
      bodyBg: colors.parchment,
    },
  },
}
