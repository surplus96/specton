// GET /runs/{id}/view 의 items 한 건 모양 (구현 가이드 강의 06).
// openapi.json에는 items가 자유 형식(객체)으로만 있어, 실제 칸은 specton/contracts/ 클래스에서 옮겨 적는다.
// 계약은 동결돼 있다. contract-change PR이 병합되면 여기도 고친다.

/** 원문 위치 (specton/contracts/base.py SourceRef) */
export type SourceRef = {
  file_format: 'xlsx' | 'csv' | 'pdf' | 'hwpx'
  sheet?: string | null
  row?: number | null
  page?: number | null
  block?: number | null
  section?: number | null
  paragraph?: number | null
  table?: number | null
}

export type ExtractionStatus = 'pass' | 'review' | 'fail'

/** section=extraction 한 건 (specton/contracts/requirements.py SourceRequirement) */
export type ExtractionBlock = {
  document_id: string
  block_id: string
  source_id: string | null
  source_ref: SourceRef
  /** 요구사항명·상세 내용이 모두 빈 행(범례·각주 등)은 null. 이때 판정은 review다 */
  source_text: string | null
  source_acceptance_level: string | null
  source_related_requirements: string | null
  source_extra: Record<string, string>
  extraction_status: ExtractionStatus
  /** 판정 이유. 서버 문장 그대로 보인다 */
  notice: string | null
  user_decision: 'confirmed' | 'excluded' | null
  excluded_reason: string | null
}
