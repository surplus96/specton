# 데이터 계약

> 상태: **초안** (착수 문서 v0.1 기준, 계약 동결 전)
> 원본: 상위 기획 폴더 `docs/개발착수_문서/05_데이터_계약_DB설계.md`
> 변경 규칙: `specton/contracts/` 변경은 `contract-change` 라벨과 2인 승인 ([CONTRIBUTING](../CONTRIBUTING.md))

## 단계 간 모델

| 모델 | 핵심 필드 | 추가·정리 후보 |
|---|---|---|
| RawRequirement | 원문·원문 ID·출처 | `document_id`, `source_ref`(시트/행 또는 페이지/블록), `extraction_status` |
| Requirement | `id`, `source_id`, `source_ref`, `parent_id`, `text`, `type`, `nfr_category`, `quality_issues` | 원문과 사용자 수정본 구분, 분석 버전 |
| Function | `id`, `name`, `description`, `priority`, `req_ids`, `entity_ops` | `priority` nullable + 근거·확인 상태 (ADR-0006). A03 전까지 `entity_ops` 비움 |
| Entity / Attribute | `pack`, `name`, `description`, `attributes`, `req_ids`, `crud_exemptions` / 타입·길이·정밀도·키·NULL·제약 | 허용 타입 고정, 안정적 내부 참조 키. FK는 관계에서 파생 |
| Relationship | `id`, `parent`, `child`, `cardinality`, `optional`, `identifying`, `rationale`, `req_ids` | 참조 키 선택·복합 키 표현 |
| Finding | `id`, `severity`, `kind`, `source`, `targets`, `evidence`, `suggestion`, `target_stage`, `fingerprint`, `iteration` | `reviewer_id`, 근거 위치, 필터 결과 |
| DesignState | `requirements`, `functions`, `entities`, `relationships`, `artifacts`, `findings`, `iteration` | `run_id`, `revision`, `status`, `interrupt_id`, 문서·팩·프롬프트·모델 버전, 병렬 가지 결과 |

- 추가 필드를 모두 LLM 출력에 넣지 않는다. 실행 메타데이터·버전·ID·필터 결과는 코드가 채운다.
- LLM 출력 모델(예: FindingDraft)과 저장 모델(Finding)을 나눈다. `id`·`source`·`fingerprint`·`iteration`은 코드가 붙인다.
- `source_ref`를 문자열로 인코딩할지 구조체로 바꿀지는 계약 검토에서 정한다 (ADR-0009).

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
- Function·Entity·Attribute·Relationship의 `req_ids`는 필수이며 현재 revision에 실재하는 REQ만 허용한다.
- N:M 분해로 생긴 테이블·속성은 원래 관계의 `req_ids`와 파생 근거를 이어받는다.

## 타입

- 허용 SQL 타입: `char`, `varchar`, `text`, `numeric`, `integer`, `bigint`, `boolean`, `date`, `time`, `timestamp`, `timestamptz` (`domain_packs/common/domains.yaml`의 `allowed_sql_types`).
- 도메인 → PostgreSQL 매핑은 공통표준 도메인 기준이며, 타입 프로필 `strict`(표준 저장 형식)와 `pg_native`(PostgreSQL 고유 타입) 중 선택한다. 현재 초안은 `strict` (ADR-0009).
- 미지원 타입을 조용히 `text`로 바꾸지 않는다.
- `Attribute.check`의 자유 SQL은 문법 검사만으로 허용하지 않는다. AST·연산 허용 범위를 정한다.

## 플랫폼 저장 모델 (후보)

저장 대상 정의이며 DDL 확정본이 아니다. 컬럼·인덱스·보존 기간은 ADR-0009·0011·0012에서 정한다.

| 객체 | 주요 필드 | 관계·제약 |
|---|---|---|
| run | `run_id`, `owner_ref`, `status`, `revision`, `iteration`, `pack_version`, `model_config`, 시각 | revision 낙관적 잠금, 상태 전이 검사 |
| document | `document_id`, `run_id`, `file_hash`, `media_type`, `storage_ref`, `original_name` | run 1:N (초기 API는 1파일), 파일 경로 노출 금지 |
| source_block | `block_id`, `document_id`, `source_ref`, `text`, `extraction_status` | document 1:N, 원문·수정본 버전 보존 |
| model_snapshot | `snapshot_id`, `run_id`, `revision`, `normalized_model`, `model_hash` | UNIQUE(run_id, revision), 승인 후 불변 |
| finding | `finding_id`, `snapshot_id`, `source`, `reviewer_or_rule`, `fingerprint`, `iteration`, `payload` | 모델 버전 연결, 과거 지적 보존 |
| approval | `approval_id`, `snapshot_id`, `interrupt_id`, `actor_ref`, `decision`, `feedback`, `answered_at` | 같은 interrupt 응답 1회 |
| artifact | `artifact_id`, `snapshot_id`, `kind`, `format`, `hash`, `storage_ref`, `approval_status` | UNIQUE(snapshot_id, kind, format), 초안/승인본 구분 |
| run_event | `run_id`, `event_id`, `event_type`, `revision`, `payload`, `created_at` | UNIQUE(run_id, event_id), SSE 재생 기준 |
| job_lease | `run_id`, `holder`, `lease_until`, `last_checkpoint` | run당 활성 실행자 1개 |

- LangGraph 체크포인트 스키마는 라이브러리 관리 영역이다. 복제하지 않는다.
- 문서·모델 본문 접근 권한은 `owner_ref`로 연결한다.

## 일관성·삭제

- 업로드가 끝나기 전 임시 파일은 document에 연결하지 않는다.
- run과 event 저장은 같은 트랜잭션이거나 다시 재생할 수 있어야 한다.
- 모델을 수정하면 기존 승인·산출물은 과거 버전으로 남기고 새로 생성한다.
- 상태 저장과 파일 생성 사이에 장애가 나면 manifest로 누락 파일을 다시 만든다.
- 실행 삭제는 DB 레코드·파일·체크포인트를 함께 처리하고, 정리 실패는 기록 후 재시도한다. 보존 기간은 미정 (ADR-0011).
