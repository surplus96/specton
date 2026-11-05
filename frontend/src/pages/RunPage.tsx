import { Flex } from 'antd'
import { useParams } from 'react-router'
import StageSteps from '../layout/StageSteps.tsx'
import PageCard from '../layout/PageCard.tsx'

// 실행 하나의 화면 (/run/:runId).
// 지금은 UI-04로 고정. 4단계에서 실행 상태(GET /runs/{id})를 보고 UI-02~07 중 하나를 고른다.
function RunPage() {
  const { runId } = useParams()
  return (
    <Flex vertical gap={24}>
      <StageSteps current="UI-04" />
      <PageCard title="설계 진행" subtitle={`실행 ID: ${runId}`}>
        (4단계에서 실행 상태에 맞는 화면이 들어갑니다)
      </PageCard>
    </Flex>
  )
}

export default RunPage
