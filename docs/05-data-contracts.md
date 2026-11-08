# 데이터 계약

> 상태: **동결** (2026-10-26, #48). 이후 변경은 `contract-change`로 하고 재동결 절차는 없다
> 구현: `specton/contracts/` (`base`·`requirements`·`design`·`findings`·`normalized`·`state`·`api`·`validation`)
> 변경 규칙: `specton/contracts/` 변경은 `contract-change` 라벨과 2인 승인. R1 작성 PR의 예외는 [CONTRIBUTING](../CONTRIBUTING.md)

## 계약 현황

| 구분 | 내용 |
|---|---|
| 주관 | R3: 계약 모델·문서 유지 |
| 변경 확인 | R2: `contract-change` PR의 의미·문서·테스트를 확인해 코멘트 |
| 승인 | R1 + 계약 영향을 받는 담당 1명. R1이 작성한 변경은 CONTRIBUTING의 예외 절차 |
| 변경 요청 | 해당 이슈에 코멘트 |

동결 이후 변경

| PR | 내용 |
|---|---|
| #73 | `critical` 심각도는 규칙 지적만 (ADR-0010) |
| #87 | 표준 준수 검사 규칙 코드 `SC-01~06` |
| #94 | 이름 규칙 `source_`·`draft_` 통일, 원문 위치 `kind` → `file_format` |
| #98 | `DesignState.source_requirements`, 근거 인용에 `source_text` 허용 |
| #110 | `ErrorCode.INVALID_REQUEST` (resume 밖 요청의 형식 오류) |
| #119 | 추출 확인은 확인·제외만 (ADR-0015): `ExtractionResponse.edits` → `excluded_blocks`, `SourceRequirement`에 `notice`·`user_decision`·`excluded_reason`, `source_text` null 허용(`review`만), `extraction_status` 기본값 없음 |
| #120 | `SourceRequirement.excluded_reason` 빈 문자열 금지, `analysable`이 결정 전 `fail` 블록도 뺀다 |
| #136 | `RequirementsResponse.answers_for`로 저장된 요구사항 ID·중복 답·문장 수·빈 문장을 검사하고, 잘못된 답은 resume API에서 422로 거절한다 |
| #140 | `SourceRequirement`: `review`·`fail` 블록은 `notice` 필수 |
| #143 | 정리 결과 모델을 계약으로 이전하고 `DesignState.normalized` 추가. 정리 결과가 있으면 스냅샷 저장·해시에 포함하고 체크포인트 허용 타입에 등록 |
| #176 | SQL 검증 결과 공용 계약 `SqlValidation`·`ValidationStep`·`ValidationIssue` 추가 (#167). 저장·승인 검사는 후속 |
| 이번 변경 (#17) | `ArtifactRef.kind`에 `manifest`, `file_format`에 `json` 추가. manifest JSON은 승인 전 비공개 후보로 저장하고 승인 근거와 같은 바이트를 공개 |

남은 작업: requirements·추적 검사 설명 (#107), FK 파생·참조 키 (#12), 값 범위 제약 (#15)

- #128로 표 파서의 `review` 블록은 `notice`를 채운다. #139부터 계약도 `review`·`fail` 블록의 `notice`를 필수로 검사한다.

### 모델별 `kind` 뜻

| 필드 | 값 | 뜻 |
|---|---|---|
| `ArtifactRef.kind` | `requirements`·`functions`·`erd`·`ddl`·`rtm`·`review`·`manifest` | 산출물 종류. 파일 형식은 `file_format` |
| `TraceIssue.kind` | `missing_req_ids`·`unknown_req_id`·`unknown_entity_ref`·`duplicate_id` | 추적 무결성 위반 종류. 대상 객체 종류는 `object_kind` |
| `FindingTarget.kind` | `requirement`·`function`·`entity`·`attribute`·`relationship` | 지적 대상 객체 종류 |
| `FindingDraft.kind` | 자유 문자열 | 지적 유형 (리뷰어가 붙인 이름) |
| `QualityIssue.kind` | 자유 문자열 | A01 품질 경고 유형 (모호 표현 등) |
| `Interrupt.kind` | `extraction`·`requirements`·`review` | HITL 멈춤 지점 |
| `ExtractionResponse`·`RequirementsResponse`·`ReviewResponse`의 `kind` | 각 지점 이름 하나 | resume 응답 판별자. `Interrupt.kind`와 같은 값이어야 하며, 다르면 422 `INVALID_RESPONSE` (#106) |

## 단계 간 모델

| 모델 | 핵심 필드 | 추가·정리 후보 |
|---|---|---|
| SourceRequirement | `document_id`, `block_id`, `source_id`, `source_ref`, `source_text`, `source_acceptance_level`, `source_related_requirements`, `source_extra`, `extraction_status`, `notice`, `user_decision`, `excluded_reason` | 문장은 고치지 않는다(ADR-0015). `source_text`는 원문 문장이 없는 행이면 null이고 이때 판정은 `review`. `extraction_status`는 기본값 없음. `review`·`fail`이면 판정 이유 `notice`가 필수다(화면에 확인 이유를 보여 준다). `user_decision`(`confirmed`·`excluded`)은 추출 확인 결정이며 `pass` 블록에는 두지 않고 `fail` 블록은 확인할 수 없다. 제외 사유는 `review`면 필수이고, 있으면 빈 문자열이 아니다. 노드는 제외했거나 원문이 없거나 `fail`인 블록을 분석하지 않는다(`analysable`) |
| Requirement | `id`, `source_id`, `source_ref`, `parent_id`, `text`, `draft_text`, `source_text`, `source_acceptance_level`, `type`, `nfr_category`, `quality_issues`, `analysis_version` | — |
| Function | `id`, `name`, `description`, `priority`, `req_ids`, `entity_ops` | `priority` nullable + 근거·확인 상태 (ADR-0006). A03 전까지 `entity_ops` 비움 |
| Entity / Attribute | `pack`, `name`, `description`, `attributes`, `req_ids`, `crud_exemptions` / 타입·길이·정밀도·키·NULL·제약 | 허용 타입 고정, 안정적 내부 참조 키. FK는 관계에서 파생 |
| Relationship | `id`, `parent`, `child`, `cardinality`, `optional`, `identifying`, `rationale`, `req_ids` | 참조 키 선택·복합 키 표현 |
| Finding | `id`, `severity`, `kind`, `source`, `targets`, `evidence`, `suggestion`, `target_stage`, `fingerprint`, `iteration` | `reviewer_id`, 근거 위치, 필터 결과 |
| NormalizedModel | `pack`, `pack_version`, `rules_version`, `lexicon_digest`, `tables`(`Table`: 컬럼·PK·UNIQUE), `foreign_keys`(`ForeignKey`) | 모델 정리(#12) 성공 결과(`specton/contracts/normalized.py`). PK·FK·UNIQUE는 컬럼 ID 묶음(순서 있음). 실패는 `NormalizeFailed`(`problems`)로 따로 돌려주며 상태에 두지 않는다. ID 기준은 ADR-0016 |
| SqlValidation | `status`, `artifact_hash`, `validator_version`, `policy_version`, `postgres_version`, `steps`(`ValidationStep`: `name`·`status`·`issues`) | SQL 파일 하나의 검증 결과(`specton/contracts/validation.py`, #167). 단계는 `parse` → `allowed_statements` → `execute` → `rollback` → `cleanup`이 순서대로 한 번씩 있고, 실행하지 않은 단계는 `not_run`이다. 단계 상태 `failed`는 SQL 결함, `error`는 검증 환경·정리 장애이며(`rollback`·`cleanup`에는 `failed`가 없다) 둘 다 `issues`(`ValidationIssue`: `code`·`message`·`statement_index`·`sqlstate`)가 1건 이상이다. 전체 `status`는 `error` > `failed` > `unverified`(실패 없이 `not_run`이 있음) > `passed` 순으로 단계에서 정해지고 계약이 일치를 검사한다. 파싱·허용 문장 검사를 통과하지 않으면 `execute`는 `not_run`이다. `postgres_version`은 대상 DB이며 DDL 생성기의 `DDL_TARGET`과 같은 값(`postgresql-18`)이다. `message`에는 보여도 되는 문장만 넣는다. run·revision·`model_hash`·검증 시도 ID는 검증기가 모르며 실행기·저장 쪽이 붙인다. 최종 승인 근거는 `passed`뿐이다 |
| DesignState | `source_requirements`, `requirements`, `functions`, `entities`, `relationships`, `normalized`, `artifacts`, `findings`, `iteration` | `normalized`는 모델 정리 성공 결과이며 설계가 바뀌면 비우고 다시 채운다(ADR-0016). `run_id`, `revision`, `status`, `interrupt_id`, 문서·팩·프롬프트·모델 버전, 병렬 가지 결과 |

- 추가 필드를 모두 LLM 출력에 넣지 않는다. 실행 메타데이터·버전·ID·필터 결과는 코드가 채운다.
- 계약 모델은 불변이다. 값을 바꿀 때는 `evolve(...)`로 새 객체를 만든다. `model_copy(update=...)`는 검증을 건너뛰므로 쓰지 않는다.
- 이름 규칙: `source_` = 원문에서 온 값(코드가 복사, 해석하지 않음. 추출 확인에서도 고치지 않고 확인·제외만 한다(ADR-0015). 앞뒤 공백까지 보존하는 칸은 `source_text`뿐이고, 나머지 `source_` 칸은 다른 텍스트 칸처럼 앞뒤 공백을 지운다) / `draft_` = LLM이 낸 값(사람 확인 전) / 접두어 없음 = 최종 또는 코드 계산값. 클래스는 맨 이름 = 저장 모델, `…Draft` = LLM 출력. 새 필드에는 `kind`를 단독 이름으로 쓰지 않는다 (예: `file_format`, `object_kind`). 기존 `kind`의 뜻은 [모델별 `kind` 뜻](#모델별-kind-뜻).
- 응락수준·중요도 같은 원문 값은 MoSCoW 등으로 바꾸지 않고 문자열 그대로 둔다. 요구사항을 분할하면 부모 값을 그대로 쓴다.
- 계약의 텍스트 필드는 앞뒤 공백을 지운다. 단, 추출한 원문(`SourceRequirement.source_text`)은 `SourceText` 타입으로 앞뒤 공백·줄바꿈까지 그대로 보존한다.
- LLM 출력 모델(예: FindingDraft)과 저장 모델(Finding)을 나눈다. `id`·`source`·`fingerprint`·`iteration`은 코드가 붙인다.
- `source_ref`는 **구조체**로 둔다 (ADR-0009). 문자열 인코딩은 파서마다 형식이 달라지고 비교·검증이 어렵다.

| kind | 필수 필드 | 선택 필드 | 번호 기준 |
|---|---|---|---|
| `xlsx` | `sheet`, `row` | | `sheet`는 시트 이름, `row`는 엑셀에 보이는 행 번호 (1부터, 머리글 행 포함) |
| `csv` | `row` | | 파일의 행 번호 (1부터, 머리글 행 포함) |
| `pdf` | `page`, `block` | | `page`는 1부터, `block`은 페이지 안 추출 순서로 0부터 |
| `hwpx` | `section`, `paragraph` | `table`+`cell` (표 안일 때 함께) | `section`·`paragraph`·`table`은 문서 순서로 0부터, `cell`은 엑셀 셀 주소 형식 (열 문자+행 번호) |

- 사람이 원본 파일에서 바로 찾는 번호(행·쪽)는 1부터, 파서가 매기는 순서(블록·구역·문단·표)는 0부터다.
- 화면 표기는 `SourceRef.display()`가 만든다. 저장·비교는 구조체로 한다.
- 엑셀·CSV는 **요구사항 1건 = 1행**을 전제로 한다. 한 요구사항이 여러 행에 걸치는 양식은 입력 양식 결정(ADR-0003)에서 다룬다.
- HWP 5.0 파일은 HWPX로 변환한 뒤 추출한다. 그래서 `file_format`에 `hwp`는 없고 위치는 `hwpx` 기준으로 기록한다. 변환 방법은 ADR-0004·#24에서 정한다.

### LLM 출력 모델과 저장 모델

| 단계 | LLM 출력 (`*Draft`) | 저장 모델 | 코드가 채우는 필드 |
|---|---|---|---|
| A01 | `RequirementDraft` (원문 블록 ID로 연결) | `Requirement` | `id`, `source_id`, `source_ref`, `parent_id`, `text`(처음에는 `draft_text`와 같은 값), `draft_text`, `source_text`, `source_acceptance_level`, `analysis_version` |
| A02 | `FunctionDraft` | `Function` | `id`, `entity_ops`(A03 전까지 비움) |
| A03 | `EntityDesignDraft` (`EntityDraft`·`AttributeDraft`·`EntityOpDraft`) | `Entity`, `Attribute`, `EntityOp` | `id`, `pack`, 엔티티 이름 → ID 해석 |
| A04 | `RelationshipDraft` (엔티티 이름으로 부모·자식 지정) | `Relationship` | `id`, 이름 → 엔티티 ID 해석 (FK 파생은 모델 정리 #12) |
| A05~A08 | `FindingDraft` | `Finding` | `id`, `source`, `reviewer_id`/`rule_code`, `fingerprint`, `iteration` |

- LLM 출력에는 ID·버전·FK 속성을 두지 않는다. 모든 Draft는 알 수 없는 필드를 거절한다.
- `FindingDraft.severity`는 `major`·`minor`만 받는다. `critical`은 규칙 지적(`source=rule`)의 `Finding`만 쓸 수 있다 (ADR-0010).
- `Attribute`도 `req_ids`가 필수다 (REQ-21).
- `Function.priority`가 null이면 `priority_source`는 `unspecified`, 값이 있으면 `explicit` 또는 `inferred`여야 한다 (ADR-0006).
- 추적 무결성은 `find_trace_issues(DesignState)`가 검사한다 (TC-N01). req_ids 누락, 없는 REQ·엔티티 참조, ID 중복을 모두 모아 돌려주며 최종 승인 전에 목록이 비어야 한다.

### 비기능 분류 (`NfrCategory`)

NFR이면 `nfr_category`를 반드시 채우고(애매하면 `other`), FR이면 `null`로 둔다. `Requirement`와 `RequirementDraft`의 검증이 둘 다 강제한다.

| 값 | 뜻 | 예 |
|---|---|---|
| `security` | 인증·권한·암호화·개인정보 접근 제어 | 관리자만 단가를 수정할 수 있다 |
| `audit` | 누가 언제 무엇을 바꿨는지 기록 | 재고 조정 시 변경자와 사유를 남긴다 |
| `retention` | 보관 기간·삭제·이력 유지 | 출고 기록은 5년간 보관한다 |
| `performance` | 응답 시간·처리량·동시 사용자 | 재고 조회는 3초 안에 응답한다 |
| `availability` | 가동 시간·백업·장애 복구 | 매일 백업하고 장애 시 4시간 안에 복구한다 |
| `usability` | 화면 사용 편의·접근성·표시 언어 | 모든 화면은 한국어로 표시한다 |
| `other` | 위 6개에 들지 않는 비기능 (호환성·법규 준수 등) | 기존 ERP의 CSV 내보내기 파일을 읽을 수 있다 |

- **데이터 정합성은 FR로 분류한다.** 값 범위·필수 입력·중복 금지·참조 관계("재고 수량은 0 이상", "품목 코드는 중복될 수 없다")는 데이터 모델의 제약으로 구현되므로 A03·A04가 처리한다. 필수 입력은 `nullable=false`, 중복 금지는 `is_unique`, 참조 관계는 `Relationship`으로 표현하고, 값 범위는 #15에서 표현 방식을 정한다.
- 한 문장에 기능과 비기능이 섞이면 A01이 분할한다.

### 우선순위 표현 (제안, ADR-0006)

```text
priority: Must | Should | Could | Won't | null
priority_source: explicit | inferred | unspecified
```

- 입력에 명시된 값은 `explicit`로 보존한다.
- LLM이 추정한 값은 `inferred`로 표시하고 HITL에서 확정한다. 평가에서는 따로 집계한다.
- MoSCoW 열거형에 임의 문자열(예: Unknown)을 넣지 않는다.

## ID·추적

| 구분 | 예 | 부여 주체 |
|---|---|---|
| 원문 ID | 고객 문서의 `SFR-001` 등 | 원문 그대로 `source_id`에 보존 |
| 내부 요구사항 ID | `REQ-01` | 코드 |
| 기능·엔티티·관계 ID | 코드 규칙에 따름 | 코드 (LLM 금지) |

- 재작업 때 같은 의미의 객체는 ID를 유지하고, 신규·삭제를 기록한다.
- ID는 종류별로 실행 안에서 고유하다. 속성 ID는 엔티티가 달라도 겹치면 안 된다 (`find_trace_issues`가 검사).
- Function·Entity·Attribute·Relationship의 `req_ids`는 필수이며 현재 revision에 실재하는 REQ만 허용한다.
- N:M 분해로 생긴 테이블·속성은 원래 관계의 `req_ids`와 파생 근거를 이어받는다.

## 타입

- 허용 SQL 타입: `char`, `varchar`, `text`, `numeric`, `integer`, `bigint`, `boolean`, `date`, `time`, `timestamp`, `timestamptz` (`SqlType`). 팩 생성기가 이 목록으로 `domain_packs/common/domains.yaml`의 `allowed_sql_types`를 만들고, 테스트가 둘이 같은지 대조한다.
- 도메인 → PostgreSQL 매핑은 공통표준 도메인 기준이며, 타입 프로필 `strict`(표준 저장 형식)와 `pg_native`(PostgreSQL 고유 타입) 중 선택한다. 현재 초안은 `strict` (ADR-0009).
- 미지원 타입을 조용히 `text`로 바꾸지 않는다.
- 중복 금지는 `is_unique`로 표시한다 (PK는 `is_key`). 값 범위 등 그 밖의 제약 표현(`check`)은 계약에 두지 않는다. LLM 출력에는 넣지 않고, 허용 범위(AST·연산)는 규칙 검사(#15)에서 정한 뒤 저장 모델에 추가한다. 그때까지 값 범위 요구는 속성의 `req_ids`로만 연결된다.

## 플랫폼 저장 모델

DDL은 `specton/persistence/schema.sql`이고 이 표와 같아야 한다. 보존 기간은 시연 계획(#23)에서 정한다.

| 객체 | 주요 필드 | 관계·제약 |
|---|---|---|
| run | `run_id`, `owner_ref`, `status`, `revision`, `iteration`, `stage`, `interrupt`, `error`, `pack`, `pack_version`, `model_config`, `last_event_id`, 시각 | revision 낙관적 잠금, 상태 전이 검사. `owner_ref`는 세션 값 (ADR-0011). `interrupt`는 사람 확인 대기에서만, `error`는 `failed`에서만 값이 있고 `GET /runs/{id}`는 run 행만 읽는다 |
| document | `document_id`, `run_id`, `file_name`, `file_format`, `file_hash`, `storage_ref` | run 1:N (초기 API는 1파일), 파일 경로 노출 금지. MIME은 저장하지 않고 `file_format`에서 정한다 |
| source_block | `block_id`, `document_id`, `source_ref`, `source_text`(null 허용), `extraction_status`, `notice`, `user_decision`, `excluded_reason`, `payload`(SourceRequirement) | document 1:N. 판정 이유·추출 확인 결정·제외 사유를 계약과 같은 칸으로 둔다 (ADR-0015). 확인한 사람·시각은 approval, 확인한 `review` 블록 목록은 `run_event` |
| model_snapshot | `snapshot_id`, `run_id`, `revision`, `normalized_model`, `model_hash` | UNIQUE(run_id, revision), 승인 후 불변 (같은 모델을 다시 저장하면 그대로 두고, 다른 모델이면 거절). `normalized_model`은 `requirements`·`functions`·`entities`·`relationships` 칸이고, 모델 정리 결과가 있으면 `normalized` 칸도 둔다. 모두 `model_hash`에 들어간다 (`save_model`, #142) |
| finding | `finding_id`, `snapshot_id`, `source`, `reviewer_or_rule`, `fingerprint`, `iteration`, `payload` | 모델 버전 연결, 과거 지적 보존 |
| approval | `approval_id`, `run_id`, `snapshot_id`, `interrupt_id`, `actor_ref`, `decision`, `feedback`, `response`, `answered_at` | UNIQUE(run_id, interrupt_id): 같은 interrupt 응답 1회. 추출·분석 확인은 모델 전이라 `snapshot_id`가 비어 있다 |
| artifact | `artifact_id`, `snapshot_id`, `kind`, `file_format`, `hash`, `storage_ref`, `approval_status` | UNIQUE(snapshot_id, kind, file_format), 초안/승인본 구분. 승인본은 같은 해시·경로·승인 상태로 다시 저장하는 것만 허용 |
| artifact_validation | `validation_id`, `artifact_id`, `artifact_hash`, `model_hash`, `status`, `steps`, `validator_version`, `policy_version`, `postgres_version`, `validated_at`, `saved_order` | SQL 검증 시도 기록(#167, #194). `validation_id`는 실행기가 붙이는 검증 시도 ID(PK)이고 시도마다 한 행이며 지우지 않는다. 같은 SQL·버전이어도 새로 검증하면 새 행이라 조회 칸 묶음에 UNIQUE를 두지 않는다. 같은 ID의 재저장은 결과가 같으면 그대로 두고 다르면 거절한다(검증 시각·순서를 바꾸지 않고, 그 뒤 SQL이 다시 생성됐어도 내용만 비교). 새 시도는 `artifact_hash` = 지금 artifact `hash`, `model_hash` = 스냅샷 `model_hash`여야 한다(`save_validation`). 조회는 지금 SQL 해시·스냅샷 `model_hash`·세 버전이 맞는 기록 중 `validated_at`이 가장 늦은 시도 하나이고, 시각이 같으면 처음 저장한 순서(`saved_order`, 재저장으로 바뀌지 않음)가 늦은 시도다(`latest_validation`). SQL이 다시 생성되면 이전 기록은 해시가 달라 쓰이지 않는다 |
| approval_basis | `approval_id`, `artifact_id`, `artifact_hash`, `validation_id` | 최종 승인 근거(#167, #195). approve 때 그 revision의 산출물마다 승인한 파일 해시를 남긴다(PK approval_id+artifact_id). `validation_id`는 SQL 검증 확인을 켠 승인에서 통과한 검증 시도를 가리키고, 그 외 산출물과 확인을 끈 승인은 NULL이다. export·승인본 게시는 이 해시와 비교한다. 과거 승인에는 근거를 만들어 넣지 않는다 |
| run_event | `run_id`, `event_id`, `event_type`, `revision`, `payload`, `created_at` | UNIQUE(run_id, event_id), SSE 재생 기준 |
| job_lease | `run_id`, `holder`, `lease_until`, `last_checkpoint` | run당 활성 실행자 1개. 반납은 행을 지우지 않고 만료시켜 `last_checkpoint`를 남긴다 (ADR-0012) |

- LangGraph 체크포인트 스키마는 라이브러리 관리 영역이다. 복제하지 않는다.
- 문서·모델 본문 접근 권한은 `owner_ref`로 연결한다.

## 일관성·삭제

- 업로드가 끝나기 전 임시 파일은 document에 연결하지 않는다.
- run과 event 저장은 같은 트랜잭션이거나 다시 재생할 수 있어야 한다.
- 모델을 수정하면 기존 승인·산출물은 과거 버전으로 남기고 새로 생성한다.
- 상태 저장과 파일 생성 사이에 장애가 나면 manifest로 누락 파일을 다시 만든다.

`manifest/json`은 현재 revision의 모델·원문·팩·프롬프트·생성기 버전과 파일별 해시를 담는다.
`files`에는 manifest 자신을 제외한다. JSON의 `approved=true`는 승인 후 공개할 최종본 내용이며,
승인 전 후보의 `ArtifactRef.approved`와 DB `approval_status`는 false·draft다. 실제 사용자 승인
여부는 이 메타데이터와 `approval`·`approval_basis`가 결정한다. 승인 전 JSON 다운로드는 409이고,
승인 시 후보 해시를 근거에 포함한 뒤 같은 바이트만 공개한다. 실행 중 오류나 정리 실패에는
가짜 manifest를 만들지 않는다. 기존 승인 기록과 이미 최종 검토에 도달한 체크포인트에는
manifest를 소급 추가하지 않는다. 기존 DB는 artifact의 종류·형식 CHECK만 넓히며 기록을 보존한다.
- 실행 삭제는 DB 레코드·파일·체크포인트를 함께 처리하고, 정리 실패는 기록 후 재시도한다. 보존 기간은 미정 (ADR-0011).
