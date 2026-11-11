# API

> 상태: **구현됨** (#16). 재개 뒤 제외 결정을 블록에 남기는 일은 실행기(#17)

Specton 실행 제어용 API다. 후속 확장에서 생성하는 재고·설비 업무 API와 다르다. 웹은 이 API만 호출한다.

## 기본 규칙

- 응답은 UTF-8 JSON, 파일은 해당 MIME 타입, 진행 이벤트는 `text/event-stream`.
- 장기 실행 요청은 **202**와 `run_id`를 반환한다. 202는 설계 성공을 뜻하지 않는다.
- 서버 세션의 소유자 컨텍스트로 실행 접근을 검사한다. 쿠키가 없으면 서버가 무작위 값을 발급해 `specton_session` 쿠키로 주고 그 값을 `owner_ref`로 쓴다. 다른 소유자의 run은 404다 (ADR-0011).
- 상태를 바꾸는 요청은 `expected_revision`을 받아 낙관적 잠금으로 처리한다.
- 저장소 파일 경로·비밀값·내부 예외를 응답에 넣지 않는다.

## 엔드포인트

| 메서드·경로 | 입력 | 정상 결과 | 주요 오류 |
|---|---|---|---|
| `POST /runs` | multipart `file`(.xlsx/.csv/.hwpx/.hwp), `pack` | 202 `run_id`·`status`·`revision` | 413 한도 초과(xlsx·hwpx는 압축을 푼 크기 포함), 415 형식(PDF는 이번 범위 밖)·내용이 확장자와 다름, 422 팩/입력 |
| `GET /runs` | `status`·`limit` 선택 | 200 소유자 실행 목록 | 422 조회 조건 |
| `GET /runs/{id}` | — | 200 상태·revision·진행·interrupt·요약 오류 | 404 없음/접근 불가 |
| `GET /runs/{id}/events` | `Last-Event-ID` 선택 | 200 SSE 스트림 | 404, 409 이벤트 재조회 필요 |
| `GET /runs/{id}/view` | `section`, `revision` 선택 | 200 화면용 JSON (추출 블록·요구사항·설계 모델·지적·산출물 목록) | 404, 409 현재보다 큰 revision |
| `POST /runs/{id}/resume` | `interrupt_id`, `expected_revision`, `response` | 202 재개 상태 | 409 오래된/이미 응답한 interrupt, 422 잘못된 답변, 500 분석 확인 모델 누락 |
| `POST /runs/{id}/cancel` | `expected_revision` | 202 취소 요청 상태 (`queued`·사람 확인 대기 중이면 바로 `cancelled`, ADR-0012) | 409 이미 완료/충돌 |
| `GET /runs/{id}/artifacts/{kind}` | `file_format`, `revision` | 200 파일 | 404, 409 미생성(PDF·manifest는 승인본만), 422 형식 불가 |
| `GET /health` | — | 200 기동 상태 (구현됨) | — |

계약: [api/openapi.json](api/openapi.json) (OpenAPI 3.1.1). Pydantic 구현은 `specton/contracts/api.py`이며 `tests/unit/test_contracts_api.py`가 필드·필수 항목·열거값이 같은지 대조한다. 스키마는 `Error`, `ErrorCode`, `SseEvent`, `SseEventData`, `Interrupt`, `RunStatus`, `RunSummary`, `RunView`, `ResumeRequest`, `ExtractionResponse`, `RequirementsResponse`, `ReviewResponse`.

- 계약은 동결됐다 (2026-10-26, #48, ADR-0009). 바꿀 때는 `contract-change`로 이 문서와 같은 PR에서 고친다 ([05 계약 현황](05-data-contracts.md#계약-현황)).
- 구현 후에는 FastAPI가 생성하는 `/openapi.json`과 초안을 대조해 차이를 없앤다.

## 사용자 확인 응답 (`resume`)

`response.kind`로 3종을 구분한다.

| kind | 내용 | 규칙 |
|---|---|---|
| `extraction` | `confirmed`, `excluded_blocks`(`block_id`, `reason` 선택) | 문장은 고치지 않고 확인 또는 제외만 한다 (ADR-0015). `confirmed=false`는 중단(`cancelled`). 제외 결정은 `source_block`과 `SourceRequirement.user_decision`에, 확인한 사람·시각은 approval에 남긴다. 제외 후 남은 블록이 0건이면 `EXTRACTION_FAILED` |
| `requirements` | `req_id`별 `keep`/`edit`/`split`, `texts` | 답이 없는 요구사항은 `keep`. `edit`은 문장 1개로 `text`를 바꾸고 `draft_text`는 둔다. `split`은 문장 2개 이상이며 첫 조각은 원래 ID, 나머지는 서버가 이어지는 새 ID를 부여한다. 조각은 원문 연결·분류를 부모와 같게 둔다 |
| `review` | `approve`/`revise`/`hold`, `feedback` | approve는 현재 revision과 차단 오류 유무 확인. 설정 `SPECTON_REQUIRE_SQL_VALIDATION`을 켜면 SQL 검증 통과도 확인한다(아래). hold는 SSE `status` 이벤트만 남기고 같은 확인 요청으로 계속 기다린다 (approval을 저장하지 않고 실행을 재개하지 않음) |

```json
{
  "interrupt_id": "int-example",
  "expected_revision": 2,
  "response": {
    "kind": "review",
    "decision": "revise",
    "feedback": "취소 사유 저장 근거를 확인해주세요."
  }
}
```

- `extraction` 응답이 아래에 해당하면 422 `INVALID_RESPONSE`다. 메시지에 해당 `block_id`를 넣는다.
  - `confirmed=false`인데 `excluded_blocks`가 있다
  - `confirmed=true`인데 제외 목록에 없는 `fail` 블록이 있다
  - 없는 `block_id`, 또는 `pass` 블록을 제외한다
  - `review` 블록을 제외하면서 사유가 비었다 (공백만 있는 사유도 빈 것으로 본다)
  - 같은 `block_id`를 두 번 제외한다
- `requirements` 응답이 아래에 해당하면 422 `INVALID_RESPONSE`다. 메시지 앞에 해당 `req_id`를 넣는다. 대조 기준은 실행기가 분석 확인에서 멈추며 저장한 그 revision 모델(`model_snapshot`)이다 (#130).
  - 없는 `req_id`
  - 같은 `req_id`에 두 번 답한다
  - 문장 수가 맞지 않는다: `keep` 0개, `edit` 1개, `split` 2개 이상
  - 빈 문장이 있다 (공백만 있는 문장도 빈 것으로 본다)
- 422로 거절한 답은 기록하지 않는다. 실행은 같은 확인 요청으로 계속 기다리고, 사용자는 고쳐서 다시 보낼 수 있다.
- 분석 확인에서 현재 revision의 `model_snapshot` 행이나 그 안의 `requirements` 필드가 없거나 null이면 500 `INTERNAL`이다. 빈 답변도 같으며, approval·실행 상태·이벤트는 바꾸지 않고 같은 확인 요청으로 계속 기다린다. 모델을 복구하면 같은 답변을 다시 보낼 수 있다. `requirements: []`가 저장된 경우는 모델 누락과 구분하여 빈 답변을 수락한다 (#144·#146).
- 동시에 보낸 같은 응답은 하나만 적용한다. 중복·오래된 응답은 409를 돌려주며 두 번째 실행을 만들지 않는다. 클라이언트는 상태를 다시 조회한다.
- approve가 아니면 산출물을 완료본으로 승격하지 않는다.
- **SQL 검증 확인 (#167, #195):** 설정 `SPECTON_REQUIRE_SQL_VALIDATION`은 실제 DDL 연결(#17)에 맞춰 기본으로 켜며, approve 때 현재 revision에 DDL/SQL 산출물이 있고, 그 SQL 해시·스냅샷 `model_hash`·지금 요구하는 검증기·정책·PostgreSQL 버전이 맞는 **가장 최근 검증 시도**가 `passed`여야 한다. 아니면 422 `INVALID_RESPONSE`(「승인할 SQL 산출물이 없습니다.」 또는 「검증을 통과하지 않은 SQL이 있어 승인할 수 없습니다.」)이고 승인·상태·승인 근거는 바뀌지 않는다. 새 시도가 `failed`·`error`·`unverified`면 이전 `passed`로 돌아가지 않고, 지금 버전의 시도가 없으면 이전 버전 성공도 쓰지 않는다. 요구 버전은 검증기 상수(`specton/validate/allowed_sql.py`)를 따른다. 명시적으로 끈 호환 모드에서는 SQL 검사를 생략하지만 승인 근거는 남긴다.
- approve는 그 revision의 산출물마다 승인한 파일 해시를 `approval_basis`에 남긴다. 검사를 켠 경우 SQL 근거에는 통과한 검증 시도가 연결된다.

## 화면용 조회

`GET /runs/{id}/view`는 실행기(#17)가 노드 뒤 저장한 DB 표만 읽는다. 체크포인트는 읽지 않는다 (ADR-0012).

설계 항목에서 Entity의 선택적 `unique_keys`는 속성 ID 묶음이고 Relationship의 `fk_bindings`는
`parent_attribute_id`·`child_attribute_id` 쌍이다(#290). 없는 옛 항목은 기존 의미를 유지한다.
LLM 초안의 이름은 저장 전에 코드가 ID로 바꾸며, API의 설계 항목은 이름 기반 선언이 아니다.
누락된 업무 제약의 의미는 검토·HITL에서 확인한다. 이 계약 검증이 업무 요구의 완전성을 증명하지는 않는다.

| section | `items` 한 건 | 읽는 곳 |
|---|---|---|
| `extraction` | `SourceRequirement` | `source_block` (run의 문서 전체, revision 무관) |
| `requirements` | `Requirement` | `model_snapshot.normalized_model.requirements` |
| `design` | `type`(`function`·`entity`·`relationship`) + `Function`·`Entity`·`Relationship` 칸 | `normalized_model`의 `functions`·`entities`·`relationships` |
| `review` | `Finding` | 그 revision 모델의 `finding` |

- `revision`을 생략하면 현재 revision이다. 현재보다 크면 409 `RUN_REVISION_CONFLICT`.
- 그 단계 결과가 아직 없으면 `items`는 빈 목록이다. `artifacts`는 그 revision의 `ArtifactRef` 목록이다. DDL/SQL 항목에는 `validation: {status, validated_at}`을 더한다: 지금 요구하는 버전 기준의 가장 최근 검증 시도의 상태(`passed`·`failed`·`error`·`unverified`)와 시각이고, 맞는 기록이 없으면 `{"status": "unverified", "validated_at": null}`이다. 단계별 내부 메시지는 넣지 않는다 (#195).

## SSE

### 노드 진행 메타데이터 (#289)

기존 `status` 이벤트의 선택적 `payload`로 `node`, `task_id`, `phase`(`started`/`finished`),
`at`(서버 UTC ISO 시각)를 보낸다. `finished`에는 `duration_ms`, `outcome`(`ok`/`error`/`cancelled`),
`result_saved`, `calls`가 있다. `calls`의 각 항목은 `stage`, `prompt_version`, `model`, `attempt`
(1=최초, 2 이상=재요청), `outcome`, `input_tokens`, `output_tokens`, `duration_ms`다.
SDK 내부 HTTP 재시도 횟수는 이 값으로 추정하지 않는다. 호출 원문·응답·내부 예외는 내보내지 않는다.
노드 시각·소요는 실행기가 task 신호를 관측한 기준이다. pending write 복구로 시작을 다시 관측하지
못한 종료는 `recovered=true`이며 노드 소요를 생략한다. 호출별 소요는 보존한 CallRecord 값이다.
combined 검토의 호출은 A05 이벤트에 한 번 기록하고 `reviewers`에 포함된 관점을 적는다.

시작은 실행기가 즉시 기록하며 run 상태·last_checkpoint를 바꾸지 않는다. 정상 종료는 모델·산출물
체크포인트와 같은 트랜잭션에서 게시한다. 취소로 폐기한 결과는 `result_saved=false`다.
`task_id`·`phase` 중복은 run 잠금 안에서 제거하며, 재생은 기존 SSE ID 규칙을 따른다.
노드 메타데이터가 없는 옛 이벤트는 단계 묶음에 의한 추정으로 표시한다. 노드 이벤트를 모든
상태 전환으로 해석하지 않으며, 실행 상태는 GET /runs 응답을 기준으로 한다.

정리 종료 이벤트는 `normalization_failed`, `problem_kinds`(정리 문제 종류만)를 추가한다.
view의 선택적 `normalization`은 성공한 정리 결과의 `tables`, `columns`, `foreign_keys`,
`pack_id`, `pack_version`, `common_version`이다. 결과가 없으면 null이며 성공을 뜻하지 않는다.
요약·호출 시각은 모델 해시·승인 근거에 넣지 않는다. 원문·프롬프트·파일 경로는 포함하지 않는다.

- 이벤트 ID는 run 안에서 단조 증가한다.
- `event`: `status` / `interrupt` / `artifact` / `error` / `completed` / `cancelled`
- `data`: `run_id`, `revision`, `stage`, `message`, 필요한 `payload`
- `artifact` 이벤트 `payload`는 저장한 `ArtifactRef`(`kind`, `file_format`, `revision`, 파일 `hash`, `approved`)다. 실행·모델·산출물 메타데이터와 함께 커밋하고, 같은 결과를 다시 저장할 때는 이벤트를 추가하지 않는다. 내부 경로와 모델 해시는 응답에 넣지 않는다.
- `interrupt` 이벤트 `payload`: `interrupt_id`, `kind`. 최종 검토(`review`)는 `failed_branches`(실패하거나 빠진 리뷰 관점, 비어 있지 않으면 불완전 검토, TC-F14)와 자동 루프를 멈춘 사유 `hitl_reason`(있을 때)을 더한다.
- 정리 문제에 사람의 조치가 필요하면 `hitl_reason=manual_review`로 알린다. 이때 생성과 LLM 검토를 건너뛰며, 실행하지 않은 리뷰 관점은 `failed_branches`에 넣지 않는다 (#17·#15).
- `error` 이벤트 `payload`: `code`, `retryable`. `EXTRACTION_FAILED`에 상세 안내가 있으면
  `error.detail`과 같은 문장을 `payload.detail`에도 넣는다. 상세 안내가 없거나 공백뿐이면
  상태 조회의 `error.detail`은 null이고 SSE의 `payload.detail`은 생략한다.
- 엑셀에서 요구사항 표가 없거나 빈 표인 시트는 `stage: parsing`인 `status` 이벤트로 안내한다. `message`는 「요구사항을 읽지 않은 시트가 있습니다」, `payload`는 `info: "skipped_sheets"`, `document_id`, `sheets`(시트 이름 목록)다. 문서마다 한 번 기록하며 이 안내만으로 추출 확인을 멈추지 않는다 (docs/09 UI-02).
- 추출 확인 답(`confirmed=true`)을 수락하면 「답변을 받아 다시 진행합니다」 `status` 이벤트 `payload`에 `kind: "extraction"`, `interrupt_id`, `confirmed_block_ids`를 넣는다. `confirmed_block_ids`는 제외하지 않은 `review` 블록 ID를 정렬한 목록이다(원문 문장이 없는 블록 포함, 없으면 `[]`). `pass`·`fail`·제외한 블록은 넣지 않는다. 이 이벤트는 `approval`·상태 전이와 같은 트랜잭션에서 API가 저장하고, 중단·422·409 응답에는 남기지 않는다 (#95 결론, #130).
- 추출 확인 답을 반영할 때, 제외한 원문의 `source_id`가 남은 원문의 「관련 요구사항」에 나오면 `status` 이벤트로 경고를 남긴다. `payload`는 `warning: "excluded_related"`, `block_id`, `source_id`, `related_block_ids`다. 제외는 막지 않는다 (ADR-0015 결정 5).
- 분석 확인(HITL 1)에서 멈추지 않으면 `analysing` 다음 `status` 이벤트가 `stage: designing`이고 `message`는 「확인할 항목이 없어 분석 확인을 생략했습니다」다. UI-04는 이 전환으로 「분석 확인 생략」을 표시한다 (ADR-0015).
- 원문 전체와 비밀값은 넣지 않는다. 연결 종료는 실행 취소가 아니다.
- 재접속하면 `Last-Event-ID` 이후를 재생한다. 아직 없는 이벤트 ID거나 숫자가 아니면 409 `EVENT_REPLAY_EXPIRED`로, 상태를 조회한 뒤 다시 연결한다.
- 서버는 새 이벤트를 짧은 간격(`SPECTON_SSE_POLL_SECONDS`)으로 확인하며, 확인할 때만 DB 연결을 빌린다 (ADR-0012). 오래 조용하면 `: keep-alive` 주석 줄을 보낸다.
- 끝난 실행(`completed`·`failed`·`cancelled`)은 남은 이벤트를 모두 보낸 뒤 스트림을 닫는다.

```text
id: 12
event: interrupt
data: {"run_id":"example","revision":2,"stage":"review","message":"최종 검토 대기","payload":{"interrupt_id":"int-example"}}
```

## 상태 응답 예시

`GET /runs/{id}` — 최종 검토 대기:

```json
{
  "run_id": "6f1c2d1e-8a3b-4f6e-9a47-2b5d0c7e1a90",
  "status": "awaiting_review",
  "revision": 2,
  "stage": "review",
  "interrupt": {"interrupt_id": "int-example", "kind": "review", "message": "최종 검토 대기"},
  "error": null
}
```

`GET /runs/{id}` — 실패 (`error.code`는 `ErrorCode` 값):

```json
{
  "run_id": "6f1c2d1e-8a3b-4f6e-9a47-2b5d0c7e1a90",
  "status": "failed",
  "revision": 1,
  "stage": "analysing",
  "interrupt": null,
  "error": {"code": "INTERNAL", "message": "분석 단계에서 실행 오류가 발생했습니다.", "run_id": "6f1c2d1e-8a3b-4f6e-9a47-2b5d0c7e1a90", "retryable": true}
}
```

요구사항 확인 `resume` 본문:

```json
{
  "interrupt_id": "int-req-1",
  "expected_revision": 1,
  "response": {
    "kind": "requirements",
    "answers": [{"req_id": "REQ-03", "action": "split", "texts": ["주문을 취소한다", "취소 사유를 저장한다"]}]
  }
}
```

## 오류 형식

```json
{"code": "RUN_REVISION_CONFLICT", "message": "다른 revision입니다.", "detail": null, "run_id": "…", "retryable": false}
```

- `code`/`message`/`detail`/`run_id`/`retryable`로 통일한다. 코드 값은 `ErrorCode`(ADR-0009)다.
- `message`는 짧은 안내이고, `detail`은 화면의 「자세히 보기」에 펼칠 문장이다. 없으면 null이며 화면은 `message`만 보여 준다 (#19). 실행 상태 조회의 `error`에도 같은 칸이 있어 실패 뒤 다시 열어도 「자세히 보기」를 보여 줄 수 있다. SSE `error` 이벤트는 지금처럼 `payload.detail`에도 담는다.

| 코드 | 언제 | HTTP | 다시 시도 |
|---|---|---|---|
| `RUN_NOT_FOUND` | 없는 실행이거나 접근 권한 없음 | 404 | 아니오 |
| `RUN_REVISION_CONFLICT` | 다른 revision 기준 요청, 지금 상태에서 할 수 없는 요청 (끝난 실행 취소 등) | 409 | 최신 상태 조회 후 |
| `INTERRUPT_STALE` | 이미 응답했거나 오래된 확인 요청에 답함 | 409 | 최신 상태 조회 후 |
| `EVENT_REPLAY_EXPIRED` | SSE 재연결 시 이벤트 보존 범위를 벗어남 | 409 | 상태 조회 후 |
| `ARTIFACT_NOT_READY` | 산출물이 아직 생성되지 않음 | 409 | 예 |
| `ARTIFACT_FORMAT_UNSUPPORTED` | 허용하지 않는 kind·file_format 조합 | 422 | 아니오 |
| `UPLOAD_TOO_LARGE` | 파일 크기 한도 초과, xlsx·hwpx 압축을 푼 크기 한도 초과 (#21) | 413 | 아니오 |
| `UNSUPPORTED_MEDIA_TYPE` | 지원하지 않는 파일 형식, 내용이 확장자와 다름: xlsx·hwpx는 zip 구조 손상·선언 크기와 실제 크기 불일치·지원하지 않는 압축 방식·파일명 인코딩·해제 버전, hwp는 OLE 복합 문서 서명 없음(#24), csv는 NUL 바이트(BOM 있는 UTF-16은 해독되면 통과) (#21, docs/11 「업로드 내용 검사」) | 415 | 아니오 |
| `PACK_UNSUPPORTED` | 없는 도메인 팩 선택 | 422 | 아니오 |
| `INVALID_RESPONSE` | resume 답변 형식이 틀림, 확인 요청과 응답 종류가 다름, 차단 오류가 남은 채 approve, SQL 검증을 통과하지 않은 채 approve(설정을 켠 경우) | 422 | 아니오 |
| `INVALID_REQUEST` | 그 밖의 요청 형식이 틀림 (조회 조건·취소 본문 등). 없는 경로는 404, 허용하지 않는 메서드는 405 | 422 / 404 / 405 | 아니오 |
| `LLM_REFUSED` | 실행 실패: 모델이 응답을 거절함 (`LLMRefusalError`) | 실행 상태 | 아니오, 입력 확인 |
| `LLM_OUTPUT_INVALID` | 실행 실패: 재요청 후에도 출력 형식 위반 (`LLMContractError`) | 실행 상태 | 예 |
| `LLM_UNAVAILABLE` | 실행 실패: LLM 타임아웃·API 오류 (`LLMTimeoutError`, `LLMAPIError`) | 실행 상태 | 예, 잠시 후 |
| `BUDGET_EXCEEDED` | 실행 실패: 토큰·시간 예산 초과 (`LLMBudgetExceededError`) | 실행 상태 | 아니오, 입력 축소 |
| `EXTRACTION_FAILED` | 실행 실패: 파일 단위로 읽지 못함(손상, 시트를 읽지 못함, 요구사항 표를 찾지 못함, 파일 전체가 빈 양식 등) 또는 추출 확인에서 제외한 뒤 남은 원문이 0건, 파싱 후 원문 블록 수가 설정 상한을 초과함 | 실행 상태 | 아니오, 다른 파일 |
| `INTERNAL` | 그 밖의 서버 오류 | 500 / 실행 상태 | 경우에 따라 |

- "실행 상태"는 HTTP 오류가 아니라 실패한 실행의 `GET /runs/{id}` 응답 `error` 필드와 SSE `error` 이벤트로 전달된다는 뜻이다.
- `EXTRACTION_FAILED`의 `message`는 파서·추출 확인이 만든 짧은 안내(`notice`)다. 「자세히 보기」 문장은 실행 상태 조회 `error.detail`과 SSE `error` 이벤트 `payload.detail` 둘 다에 담는다(실행기가 채움, #19·#204). 다른 실행 실패는 내부 내용을 숨기고 코드별 고정 문구를 쓴다.
- 비동기 실행 중 오류는 `GET /runs/{id}`와 SSE `error` 이벤트로 전달한다.

## 산출물 형식

| kind | 허용 file_format | 비고 |
|---|---|---|
| `requirements` | md | 중간 |
| `functions` | md, pdf | PDF는 승인된 revision에서만 |
| `erd` | mmd, pdf | PDF는 승인된 revision에서만 |
| `ddl` | sql | |
| `rtm` | xlsx, csv | |
| `review` | md | 기존 API·저장 호환 목록. 현재 생성하지 않으며 파일이 없으면 409. 검토는 최종 HITL 및 `view?section=review`로 조회 |
| `manifest` | json | 승인 후에만 다운로드 |

- 다른 조합은 422.
- 승인 전 파일은 초안 파일명(`-draft`)·메타데이터(`approved=false`)로 구분한다.
- 기능 명세 Markdown과 RTM Excel·CSV는 생성 단계에서 같은 모델·revision으로 저장한다.
  승인 때 각 파일 해시를 `approval_basis`에 기록하고, 내보내기는 재생성 없이 같은 바이트를
  승인본으로 게시한다. 원문 제외·원문 없음 행도 RTM에 남는다. 기능 명세 PDF도 설정
  (`SPECTON_ENABLE_FUNCTION_SPEC_PDF`)을 켜면 같은 단계에서 비공개 후보로 만들고 같은 방식으로 승인·게시한다
  (끄면 `functions` `pdf`는 409 미생성).
- manifest JSON도 최종본 바이트를 승인 전 비공개 후보(`approved=false`)로 저장한다.
  JSON의 `approved=true`는 공개할 최종본의 내용이며, 실제 승인은 DB 메타데이터와 승인 기록으로 판단한다.
  JSON을 읽는 쪽도 본문의 `approved`가 아니라 `ArtifactRef.approved`로 승인 여부를 판단한다.
  승인 전 다운로드는 409다. 승인 시 manifest 자신의 해시도 근거에 고정하고, 승인 후 재생성하지 않는다.
  `files`에는 같은 모델·revision의 출력 해시만 있고 manifest 자신의 해시는 제외한다.
  `generator_versions.common_version`·`policy_digest`는 정리 때 기록한 공통 팩 버전·팩/표준 정책 해시다.
  이전 실행에는 두 값이 null일 수 있으며 다운로드 때 현재 값으로 소급해서 채우지 않는다.
  내부 `NormalizedModel`의 선택 필드 추가이며 기존 RunView·다운로드 응답 형식은 유지한다.
- ERD PDF 기능을 켜면
  승인본용 PDF 바이트를 미리 비공개 후보로 저장하되 `approved=false`이며, 승인 전 PDF
  다운로드는 계속 409다. 승인 근거가 기록한 후보 해시와 같은 바이트만 승인 후 공개한다.
- 요청 revision의 객체 존재·접근 권한을 확인한 뒤 `Content-Disposition`으로 안전한 파일명을 지정한다.
- 파일명은 `specton-<kind>-r<revision>.<file_format>`, 승인 전이면 `-draft`를 붙인다. `ETag`는 산출물 해시다.
- 쿼리 이름은 `ArtifactRef`와 같은 `file_format`이다 (#94 이름 정리, #16).
