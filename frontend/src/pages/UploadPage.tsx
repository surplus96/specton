import { Flex } from 'antd'
import StageSteps from '../layout/StageSteps.tsx'
import PageCard from '../layout/PageCard.tsx'

// UI-01 실행 시작. 파일 선택·팩 선택·실행 요청은 3단계에서 만든다.
function UploadPage() {
  return (
    <Flex vertical gap={24}>
      <StageSteps current="UI-01" />
      <PageCard
        title="요구사항 문서 올리기"
        subtitle="요구사항 정의서(.xlsx · .csv · .hwpx)를 올리면 기능 명세·ERD·DDL·RTM을 만듭니다."
      >
        (3단계에서 업로드 칸이 들어갑니다)
      </PageCard>
    </Flex>
  )
}

export default UploadPage
