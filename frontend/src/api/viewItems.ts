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

/** 품질 경고와 확인 질문 (specton/contracts/requirements.py QualityIssue) */
export type QualityIssue = {
  kind: string
  message: string
  question: string | null
}

export type NfrCategory = 'security' | 'audit' | 'retention' | 'performance' | 'availability' | 'usability' | 'other'

/** section=requirements 한 건 (specton/contracts/requirements.py Requirement) */
export type AnalysedRequirement = {
  id: string
  source_id: string | null
  source_ref: SourceRef
  /** 분할로 생긴 요구사항이면 원래 요구사항 ID */
  parent_id: string | null
  /** 최종 문장 (사용자 확인 후) */
  text: string
  /** A01이 낸 문장 */
  draft_text: string
  source_text: string | null
  source_acceptance_level: string | null
  type: 'FR' | 'NFR'
  nfr_category: NfrCategory | null
  quality_issues: QualityIssue[]
  analysis_version: number
}

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

// ── section=design: type으로 구분 (specton/contracts/design.py) ─────────

export type Crud = 'C' | 'R' | 'U' | 'D'

export type DesignFunction = {
  type: 'function'
  id: string
  name: string
  description: string
  priority: 'Must' | 'Should' | 'Could' | "Won't" | null
  priority_source: 'explicit' | 'inferred' | 'unspecified'
  priority_rationale: string | null
  req_ids: string[]
  entity_ops: { entity_id: string; operations: Crud[] }[]
}

export type DesignAttribute = {
  id: string
  name: string
  description: string | null
  data_type: string
  length: number | null
  precision: number | null
  scale: number | null
  is_key: boolean
  is_unique: boolean
  nullable: boolean
  req_ids: string[]
}

export type DesignEntity = {
  type: 'entity'
  id: string
  pack: string
  name: string
  description: string
  attributes: DesignAttribute[]
  req_ids: string[]
  crud_exemptions: { operation: Crud; reason: string }[]
}

export type DesignRelationship = {
  type: 'relationship'
  id: string
  parent: string
  child: string
  cardinality: '1:1' | '1:N' | 'N:M'
  optional: boolean
  identifying: boolean
  rationale: string
  req_ids: string[]
}

export type DesignItem = DesignFunction | DesignEntity | DesignRelationship

// ── section=review (specton/contracts/findings.py Finding) ─────────────

export type Severity = 'critical' | 'major' | 'minor'

export type Finding = {
  id: string
  kind: string
  severity: Severity
  targets: { kind: 'requirement' | 'function' | 'entity' | 'attribute' | 'relationship'; id: string }[]
  evidence: { req_id: string | null; quote: string; source_ref?: SourceRef | null }[]
  suggestion: string
  target_stage: 'requirements' | 'functions' | 'data_model' | null
  /** rule: 규칙 검사(RULE·SC), llm: 리뷰어(A05~A08). critical은 rule만 (ADR-0010) */
  source: 'rule' | 'llm'
  reviewer_id: string | null
  rule_code: string | null
  fingerprint: string
  iteration: number
}

// ── view의 artifacts 한 건 (specton/contracts/state.py ArtifactRef) ─────────

/** 생성한 산출물 한 건. approved가 false면 초안이다 (docs/06 「산출물 형식」). */
export type ArtifactRef = {
  kind: 'requirements' | 'functions' | 'erd' | 'ddl' | 'rtm' | 'review'
  file_format: 'md' | 'pdf' | 'mmd' | 'sql' | 'xlsx' | 'csv'
  revision: number
  hash: string
  approved: boolean
  /** DDL/SQL에만 붙는 지금 기준 검증 상태 (docs/06 `/view`, #195). 기록이 없으면 unverified */
  validation?: { status: 'passed' | 'failed' | 'error' | 'unverified'; validated_at: string | null }
}
