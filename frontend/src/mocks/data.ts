// mock 서버가 돌려줄 예시 데이터 (재고관리 예시).
// 필드 모양은 백엔드 모델을 따른다: specton/contracts/requirements.py(SourceRequirement, Requirement),
// design.py(Function, Entity, Relationship), findings.py(Finding), state.py(ArtifactRef).
// view의 items는 계약에서 "객체"로만 정해져 있어 타입 검사를 받지 않으니, 모델이 바뀌면 여기도 맞춘다.

const ref = (row: number) => ({ file_format: 'xlsx', sheet: '요구사항', row })

/** section=extraction: 추출 블록 (pass 3, review 2, fail 1). B6은 원문 문장이 없는 행(계약상 review) */
export const extractionItems = [
  {
    document_id: 'doc-1',
    block_id: 'B1',
    source_id: 'SFR-001',
    source_ref: ref(2),
    source_text: '창고별로 품목 재고를 관리한다.',
    source_acceptance_level: '필수',
    source_related_requirements: null,
    source_extra: {},
    extraction_status: 'pass',
    notice: null,
    user_decision: null,
    excluded_reason: null,
  },
  {
    document_id: 'doc-1',
    block_id: 'B2',
    source_id: 'SFR-002',
    source_ref: ref(3),
    source_text: '입고 시 거래처와 입고 수량을 기록한다.',
    source_acceptance_level: '필수',
    source_related_requirements: 'SFR-001',
    source_extra: {},
    extraction_status: 'pass',
    notice: null,
    user_decision: null,
    excluded_reason: null,
  },
  {
    document_id: 'doc-1',
    block_id: 'B3',
    source_id: 'SFR-002',
    source_ref: ref(4),
    source_text: '입고 내역은 품목분류별로 조회할 수 있어야 한다.',
    source_acceptance_level: null,
    source_related_requirements: null,
    source_extra: {},
    extraction_status: 'review',
    notice: '같은 원문 ID(SFR-002)가 두 번 나옵니다. 따로 분석할 요구사항인지 확인해 주세요.',
    user_decision: null,
    excluded_reason: null,
  },
  {
    document_id: 'doc-1',
    block_id: 'B4',
    source_id: 'SFR-003',
    source_ref: ref(5),
    source_text: '재고 수량이 안전재고보다 적으면 담당자에게 알린다.',
    source_acceptance_level: '선택',
    source_related_requirements: 'SFR-002',
    source_extra: {},
    extraction_status: 'pass',
    notice: null,
    user_decision: null,
    excluded_reason: null,
  },
  {
    document_id: 'doc-1',
    block_id: 'B5',
    source_id: null,
    source_ref: ref(9),
    source_text: '※ 위 표의 응락수준은 2025년 기준입니다.',
    source_acceptance_level: null,
    source_related_requirements: null,
    source_extra: {},
    extraction_status: 'fail',
    notice: '요구사항이 아닌 각주로 보입니다. 제외해 주세요.',
    user_decision: null,
    excluded_reason: null,
  },
  {
    document_id: 'doc-1',
    block_id: 'B6',
    source_id: 'SFR-004',
    source_ref: ref(7),
    source_text: null,
    source_acceptance_level: null,
    source_related_requirements: null,
    source_extra: {},
    extraction_status: 'review',
    notice: '요구사항명과 요구사항 세부내용이 모두 비어 있음',
    user_decision: null,
    excluded_reason: null,
  },
]

/** section=requirements: 분석된 요구사항 (REQ-02에 답이 필요한 질문) */
export const requirementItems = [
  {
    id: 'REQ-01',
    source_id: 'SFR-001',
    source_ref: ref(2),
    parent_id: null,
    text: '창고별로 품목 재고를 관리한다.',
    draft_text: '창고별로 품목 재고를 관리한다.',
    source_text: '창고별로 품목 재고를 관리한다.',
    source_acceptance_level: '필수',
    type: 'FR',
    nfr_category: null,
    quality_issues: [],
    analysis_version: 1,
  },
  {
    id: 'REQ-02',
    source_id: 'SFR-002',
    source_ref: ref(3),
    parent_id: null,
    text: '입고 시 거래처와 입고 수량을 기록한다.',
    draft_text: '입고 시 거래처와 입고 수량을 기록한다.',
    source_text: '입고 시 거래처와 입고 수량을 기록한다.',
    source_acceptance_level: '필수',
    type: 'FR',
    nfr_category: null,
    quality_issues: [
      {
        kind: 'ambiguous',
        message: '입고 수량의 단위가 정해져 있지 않습니다.',
        question: '입고 수량은 어떤 단위(개·박스 등)로 기록하나요?',
      },
    ],
    analysis_version: 1,
  },
  {
    id: 'REQ-03',
    source_id: 'SFR-002',
    source_ref: ref(4),
    parent_id: null,
    text: '입고 내역은 품목분류별로 조회할 수 있어야 한다.',
    draft_text: '입고 내역은 품목분류별로 조회할 수 있어야 한다.',
    source_text: '입고 내역은 품목분류별로 조회할 수 있어야 한다.',
    source_acceptance_level: null,
    type: 'FR',
    nfr_category: null,
    quality_issues: [],
    analysis_version: 1,
  },
  {
    id: 'REQ-04',
    source_id: 'SFR-003',
    source_ref: ref(5),
    parent_id: null,
    text: '재고 수량이 안전재고보다 적으면 담당자에게 알린다.',
    draft_text: '재고 수량이 안전재고보다 적으면 담당자에게 알린다.',
    source_text: '재고 수량이 안전재고보다 적으면 담당자에게 알린다.',
    source_acceptance_level: '선택',
    type: 'FR',
    nfr_category: null,
    quality_issues: [],
    analysis_version: 1,
  },
]

const attr = (id: string, name: string, data_type: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  description: null,
  data_type,
  length: data_type === 'varchar' ? 20 : null,
  precision: null,
  scale: null,
  is_key: false,
  is_unique: false,
  nullable: true,
  ...extra,
})

/** section=design: 기능·엔티티·관계 (type으로 구분) */
export const designItems = [
  {
    type: 'function',
    id: 'FN-01',
    name: '입고 등록',
    description: '거래처에서 들어온 품목과 수량을 창고에 기록한다.',
    priority: 'Must',
    priority_source: 'explicit',
    priority_rationale: null,
    req_ids: ['REQ-02'],
    entity_ops: [
      { entity_id: 'ENT-03', operations: ['C'] },
      { entity_id: 'ENT-02', operations: ['R'] },
    ],
  },
  {
    type: 'function',
    id: 'FN-02',
    name: '재고 조회',
    description: '창고별·품목분류별 재고를 조회한다.',
    priority: 'Must',
    priority_source: 'explicit',
    priority_rationale: null,
    req_ids: ['REQ-01', 'REQ-03'],
    entity_ops: [{ entity_id: 'ENT-02', operations: ['R'] }],
  },
  {
    type: 'entity',
    id: 'ENT-01',
    pack: 'inventory',
    name: '창고',
    description: '품목을 보관하는 장소',
    attributes: [
      attr('ATTR-01', '창고코드', 'varchar', { is_key: true, nullable: false }),
      attr('ATTR-02', '창고명', 'varchar', { nullable: false }),
    ],
    req_ids: ['REQ-01'],
    crud_exemptions: [],
  },
  {
    type: 'entity',
    id: 'ENT-02',
    pack: 'inventory',
    name: '품목',
    description: '관리하는 물품',
    attributes: [
      attr('ATTR-03', '품목코드', 'varchar', { is_key: true, nullable: false }),
      attr('ATTR-04', '품목명', 'varchar', { nullable: false }),
      attr('ATTR-05', '안전재고', 'integer'),
    ],
    req_ids: ['REQ-01', 'REQ-04'],
    crud_exemptions: [],
  },
  {
    type: 'entity',
    id: 'ENT-03',
    pack: 'inventory',
    name: '입고',
    description: '품목이 창고에 들어온 기록',
    attributes: [
      attr('ATTR-06', '입고번호', 'varchar', { is_key: true, nullable: false }),
      attr('ATTR-07', '입고일자', 'date', { nullable: false }),
      attr('ATTR-08', '입고수량', 'integer', { nullable: false }),
    ],
    req_ids: ['REQ-02'],
    crud_exemptions: [],
  },
  {
    type: 'relationship',
    id: 'REL-01',
    parent: 'ENT-01',
    child: 'ENT-03',
    cardinality: '1:N',
    optional: false,
    identifying: false,
    rationale: '"창고별로 품목 재고를 관리한다"에 따라 입고는 한 창고에 속한다.',
    req_ids: ['REQ-01', 'REQ-02'],
  },
  {
    type: 'relationship',
    id: 'REL-02',
    parent: 'ENT-02',
    child: 'ENT-03',
    cardinality: '1:N',
    optional: false,
    identifying: false,
    rationale: '"입고 시 거래처와 입고 수량을 기록한다"에 따라 입고마다 품목이 하나 있다.',
    req_ids: ['REQ-02'],
  },
]

/** 차단 오류: 규칙 검사만 critical을 낼 수 있다 (ADR-0010). mock 시나리오 critical에서만 쓴다 */
export const CRITICAL_FINDING = {
  id: 'FND-00',
  kind: 'missing_primary_key',
  severity: 'critical',
  targets: [{ kind: 'entity', id: 'ENT-03' }],
  evidence: [{ req_id: 'REQ-02', quote: '입고 시 거래처와 입고 수량을 기록한다' }],
  suggestion: '입고 엔티티의 식별자가 정해지지 않았습니다. 입고번호를 주 식별자로 두세요.',
  target_stage: 'data_model',
  source: 'rule',
  reviewer_id: null,
  rule_code: 'RULE-03',
  fingerprint: 'fp-00',
  iteration: 0,
}

/** section=review: 검토 지적 (차단 오류 없음) */
export const findingItems = [
  {
    id: 'FND-01',
    kind: 'missing_crud',
    severity: 'major',
    targets: [{ kind: 'entity', id: 'ENT-01' }],
    evidence: [{ req_id: 'REQ-01', quote: '창고별로 품목 재고를 관리한다' }],
    suggestion: '창고를 등록·수정하는 기능이 없습니다. 창고 관리 기능을 추가하세요.',
    target_stage: 'functions',
    source: 'llm',
    reviewer_id: 'A06',
    rule_code: null,
    fingerprint: 'fp-01',
    iteration: 0,
  },
  {
    id: 'FND-02',
    kind: 'naming',
    severity: 'minor',
    targets: [{ kind: 'attribute', id: 'ATTR-05' }],
    evidence: [{ req_id: 'REQ-04', quote: '안전재고보다 적으면' }],
    suggestion: '안전재고의 단위를 설명에 적으세요.',
    target_stage: 'data_model',
    source: 'rule',
    reviewer_id: null,
    rule_code: 'SC-03',
    fingerprint: 'fp-02',
    iteration: 0,
  },
]

/** 산출물 종류와 형식 (docs/06 「산출물 형식」). PDF는 승인한 revision에서만 만든다. */
export const ARTIFACT_FORMATS = {
  requirements: ['md'],
  functions: ['md', 'pdf'],
  erd: ['mmd', 'pdf'],
  ddl: ['sql'],
  rtm: ['xlsx', 'csv'],
  review: ['md'],
  manifest: ['json'],
} as const

/** ERD 원문 예시: 실제 ERD 생성 코드(specton/codegen/erd.py, #177)가 시험 모델로 낸 그대로 (A안 표기) */
export const ERD_SAMPLE = `erDiagram
    %% Specton ERD · inventory 0.1.7
    item_clsf["품목분류"] {
        varchar(20) 분류코드 PK "clsf_cd"
        varchar(20) 상위분류코드 FK "up_clsf_cd"
    }
    item["품목"] {
        varchar(20) 품목코드 PK "item_cd"
        numeric 단가 "untprc · numeric(12,2)"
        char(1) 입_출고구분 "io_se · 입·출고구분"
        integer _1차_단가 "frst_untprc · 1차 단가"
        varchar(20) 바코드 UK "brcd"
    }
    item_phto["품목사진"] {
        varchar(20) 사진번호 PK "phto_no"
        varchar(20) 품목코드 FK,UK "item_cd"
    }
    wrhsg["입고"] {
        varchar(20) 입고번호 PK "wrhsg_no"
        timestamp(3) 입고일시 "wrhsg_dt"
        varchar(20) 창고코드 FK "wrhus_cd"
    }
    wrhsg_dtl["입고내역"] {
        varchar(20) 입고번호 PK,FK "wrhsg_no"
        integer 순번 PK "sn"
    }
    bzpt["거래처"] {
        varchar(20) 거래처코드 PK "bzpt_cd"
    }
    wrhus["창고"] {
        varchar(20) 창고코드 PK "wrhus_cd"
    }
    item_bzpt["품목거래처"] {
        varchar(20) 품목코드 PK,FK "item_cd"
        varchar(20) 거래처코드 PK,FK "bzpt_cd"
    }
    wrhus ||..o{ wrhsg : "REL-01"
    wrhsg ||--o{ wrhsg_dtl : "REL-02"
    item_clsf |o..o{ item_clsf : "REL-03"
    item ||--o{ item_bzpt : "REL-04"
    bzpt ||--o{ item_bzpt : "REL-04"
    item |o..o| item_phto : "REL-05"
`

/** DDL 예시: 실제 DDL 생성 코드(#165·#173)가 재고 팩 설계로 낸 결과의 앞부분 */
export const DDL_SAMPLE = `-- postgresql 18 / pack inventory 0.1.14 / rules normalize-v0 / lexicon f1eae74da934ede1a46f467fba5fabdd1b000d8330262f71b9ce40a3855d2e20 / generator ddl-v0 / validation unverified

CREATE TABLE "mvmn_drctn" (
  "mvmn_drctn_no" varchar(20) NOT NULL,
  "drctn_dt" timestamp,
  "altmnt_no" varchar(20) NOT NULL,
  PRIMARY KEY ("mvmn_drctn_no")
);

CREATE TABLE "dlvrpl" (
  "dlvrpl_cd" varchar(10) NOT NULL,
  PRIMARY KEY ("dlvrpl_cd")
);

CREATE TABLE "cnpt" (
  "cnpt_cd" varchar(10) NOT NULL,
  "cnpt_nm" varchar(100),
  "brno" char(10),
  PRIMARY KEY ("cnpt_cd")
);

ALTER TABLE "invt_acinsp" ADD FOREIGN KEY ("wrhus_cd") REFERENCES "wrhus" ("wrhus_cd");
`

/**
 * 웹 ERD 보안 시험용 원문 (#190 R1 리뷰). 지시문으로 화면 CSS를 바꾸려는 원문이다.
 * 실제 ERD 생성 코드는 이름의 지시문 기호를 걸러 내지만, 웹도 따로 막는다(그리지 않음).
 */
export const ERD_ATTACK_SAMPLE = `erDiagram
    %%{init: {"themeCSS": "body { background: red !important; }"}}%%
    wrhus["창고%%{init: {'themeCSS': 'body{display:none}'}}%%"] {
        varchar(10) 창고코드 PK "wrhus_cd"
    }
`

/**
 * 큰 설계 (AI Workspace 성능 확인, #281): 파일 이름에 `large`가 들어 있으면 쓴다.
 * 엔티티 50개(속성 2~7개) · 관계 60개 · 기능 8개. 요구사항은 기본 mock의 REQ-01~04를 가리킨다.
 */
export const LARGE_DESIGN_ITEMS = (() => {
  const entities = Array.from({ length: 50 }, (_, i) => ({
    type: 'entity',
    id: `ENT-${String(i + 1).padStart(3, '0')}`,
    pack: 'inventory',
    name: `시험엔티티${i + 1}`,
    description: `성능 확인용 엔티티 ${i + 1}`,
    attributes: Array.from({ length: 2 + (i % 6) }, (__, j) => ({
      id: `ATTR-${i + 1}-${j + 1}`,
      name: j === 0 ? `엔티티${i + 1}코드` : `속성${j}`,
      description: null,
      data_type: j === 0 ? 'varchar' : j % 2 ? 'integer' : 'date',
      length: j === 0 ? 20 : null,
      precision: null,
      scale: null,
      is_key: j === 0,
      is_unique: j === 1 && i % 4 === 0,
      nullable: j > 1,
      req_ids: [`REQ-0${(i % 4) + 1}`],
    })),
    req_ids: [`REQ-0${(i % 4) + 1}`],
    crud_exemptions: [],
  }))
  const relationships = Array.from({ length: 60 }, (_, i) => ({
    type: 'relationship',
    id: `REL-${String(i + 1).padStart(3, '0')}`,
    // 부모 25개 × 한 부모당 자식 2~3개. i와 i+25는 자식을 7칸 밀어 60개가 모두 다른 부모·자식 쌍이 된다
    parent: entities[i % 25].id,
    child: entities[25 + (((i % 25) + 7 * Math.floor(i / 25) + 3) % 25)].id,
    cardinality: i % 10 === 0 ? 'N:M' : '1:N',
    optional: i % 3 === 0,
    identifying: i % 5 === 0,
    rationale: '"재고를 관리한다." 성능 확인용 관계',
    req_ids: ['REQ-01'],
  }))
  const functions = Array.from({ length: 8 }, (_, i) => ({
    type: 'function',
    id: `FUNC-${String(i + 1).padStart(2, '0')}`,
    name: `시험 기능 ${i + 1}`,
    description: '성능 확인용 기능',
    priority: null,
    priority_source: 'unspecified',
    priority_rationale: null,
    req_ids: [`REQ-0${(i % 4) + 1}`],
    entity_ops: entities.slice(i * 6, i * 6 + 6).map((e) => ({ entity_id: e.id, operations: ['C', 'R', 'U'] })),
  }))
  return [...functions, ...entities, ...relationships]
})()
