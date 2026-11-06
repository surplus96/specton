import { Steps } from 'antd'

// 화면 단계 표시줄. 순서는 docs/09-ui-flow.md의 UI-01~07을 따른다.
export const SCREENS = [
  { id: 'UI-01', title: '실행 시작' },
  { id: 'UI-02', title: '추출 확인' },
  { id: 'UI-03', title: '분석 확인' },
  { id: 'UI-04', title: '설계 진행' },
  { id: 'UI-05', title: '결과 작업공간' },
  { id: 'UI-06', title: '최종 검토' },
  { id: 'UI-07', title: '다운로드' },
] as const

export type ScreenId = (typeof SCREENS)[number]['id']

type Props = {
  current: ScreenId
}

function StageSteps({ current }: Props) {
  const index = SCREENS.findIndex((s) => s.id === current)
  return (
    <Steps
      size="small"
      current={index}
      items={SCREENS.map((s) => ({ title: s.title, content: s.id }))}
    />
  )
}

export default StageSteps
