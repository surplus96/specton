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
| `POST /runs` | multipart `file`(.xlsx/.csv/.hwpx), `pack` | 202 `run_id`·`status`·`revision` | 413 한도 초과, 415 형식(.hwp는 HWPX 변환 안내, PDF는 이번 범위 밖), 422 팩/입력 |
| `GET /runs` | `status`·`limit` 선택 | 200 소유자 실행 목록 | 422 조회 조건 |
| `GET /runs/{id}` | — | 200 상태·revision·진행·interrupt·요약 오류 | 404 없음/접근 불가 |
| `GET /runs/{id}/events` | `Last-Event-ID` 선택 | 200 SSE 스트림 | 404, 409 이벤트 재조회 필요 |
| `GET /runs/{id}/view` | `section`, `revision` 선택 | 200 화면용 JSON (추출 블록·요구사항·설계 모델·지적·산출물 목록) | 404, 409 현재보다 큰 revision |
| `POST /runs/{id}/resume` | `interrupt_id`, `expected_revision`, `response` | 202 재개 상태 | 409 오래된/이미 응답한 interrupt, 422 잘못된 답변 |
| `POST /runs/{id}/cancel` | `expected_revision` | 202 취소 요청 상태 (`queued`·사람 확인 대기 중이면 바로 `cancelled`, ADR-0012) | 409 이미 완료/충돌 |
| `GET /runs/{id}/artifacts/{kind}` | `file_format`, `revision` | 200 파일 | 404, 409 미생성(PDF는 승인본만), 422 형식 불가 |
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
| `review` | `approve`/`revise`/`hold`, `feedback` | approve는 현재 revision과 차단 오류 유무 확인. hold는 SSE `status` 이벤트만 남기고 같은 확인 요청으로 계속 기다린다 (approval을 저장하지 않고 실행을 재개하지 않음) |

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
- 동시에 보낸 같은 응답은 하나만 적용한다. 중복·오래된 응답은 409를 돌려주며 두 번째 실행을 만들지 않는다. 클라이언트는 상태를 다시 조회한다.
- approve가 아니면 산출물을 완료본으로 승격하지 않는다.

## 화면용 조회

`GET /runs/{id}/view`는 실행기(#17)가 노드 뒤 저장한 DB 표만 읽는다. 체크포인트는 읽지 않는다 (ADR-0012).

| section | `items` 한 건 | 읽는 곳 |
|---|---|---|
| `extraction` | `SourceRequirement` | `source_block` (run의 문서 전체, revision 무관) |
| `requirements` | `Requirement` | `model_snapshot.normalized_model.requirements` |
| `design` | `type`(`function`·`entity`·`relationship`) + `Function`·`Entity`·`Relationship` 칸 | `normalized_model`의 `functions`·`entities`·`relationships` |
| `review` | `Finding` | 그 revision 모델의 `finding` |

- `revision`을 생략하면 현재 revision이다. 현재보다 크면 409 `RUN_REVISION_CONFLICT`.
- 그 단계 결과가 아직 없으면 `items`는 빈 목록이다. `artifacts`는 그 revision의 `ArtifactRef` 목록이다.

## SSE

- 이벤트 ID는 run 안에서 단조 증가한다.
- `event`: `status` / `interrupt` / `artifact` / `error` / `completed` / `cancelled`
- `data`: `run_id`, `revision`, `stage`, `message`, 필요한 `payload`
- `interrupt` 이벤트 `payload`: `interrupt_id`, `kind`. 최종 검토(`review`)는 `failed_branches`(실패하거나 빠진 리뷰 관점, 비어 있지 않으면 불완전 검토, TC-F14)와 자동 루프를 멈춘 사유 `hitl_reason`(있을 때)을 더한다.
- `error` 이벤트 `payload`: `code`, `retryable`. `EXTRACTION_FAILED`면 `detail`(「자세히 보기」에 펼칠 문장)도 넣는다.
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
{"code": "RUN_REVISION_CONFLICT", "message": "다른 revision입니다.", "run_id": "…", "retryable": false}
```

- `code`/`message`/`run_id`/`retryable`로 통일한다. 코드 값은 `ErrorCode`(ADR-0009)다.

| 코드 | 언제 | HTTP | 다시 시도 |
|---|---|---|---|
| `RUN_NOT_FOUND` | 없는 실행이거나 접근 권한 없음 | 404 | 아니오 |
| `RUN_REVISION_CONFLICT` | 다른 revision 기준 요청, 지금 상태에서 할 수 없는 요청 (끝난 실행 취소 등) | 409 | 최신 상태 조회 후 |
| `INTERRUPT_STALE` | 이미 응답했거나 오래된 확인 요청에 답함 | 409 | 최신 상태 조회 후 |
| `EVENT_REPLAY_EXPIRED` | SSE 재연결 시 이벤트 보존 범위를 벗어남 | 409 | 상태 조회 후 |
| `ARTIFACT_NOT_READY` | 산출물이 아직 생성되지 않음 | 409 | 예 |
| `ARTIFACT_FORMAT_UNSUPPORTED` | 허용하지 않는 kind·file_format 조합 | 422 | 아니오 |
| `UPLOAD_TOO_LARGE` | 파일 크기 한도 초과 | 413 | 아니오 |
| `UNSUPPORTED_MEDIA_TYPE` | 지원하지 않는 파일 형식 | 415 | 아니오 |
| `PACK_UNSUPPORTED` | 없는 도메인 팩 선택 | 422 | 아니오 |
| `INVALID_RESPONSE` | resume 답변 형식이 틀림, 확인 요청과 응답 종류가 다름, 차단 오류가 남은 채 approve | 422 | 아니오 |
| `INVALID_REQUEST` | 그 밖의 요청 형식이 틀림 (조회 조건·취소 본문 등). 없는 경로는 404, 허용하지 않는 메서드는 405 | 422 / 404 / 405 | 아니오 |
| `LLM_REFUSED` | 실행 실패: 모델이 응답을 거절함 (`LLMRefusalError`) | 실행 상태 | 아니오, 입력 확인 |
| `LLM_OUTPUT_INVALID` | 실행 실패: 재요청 후에도 출력 형식 위반 (`LLMContractError`) | 실행 상태 | 예 |
| `LLM_UNAVAILABLE` | 실행 실패: LLM 타임아웃·API 오류 (`LLMTimeoutError`, `LLMAPIError`) | 실행 상태 | 예, 잠시 후 |
| `BUDGET_EXCEEDED` | 실행 실패: 토큰·시간 예산 초과 (`LLMBudgetExceededError`) | 실행 상태 | 아니오, 입력 축소 |
| `EXTRACTION_FAILED` | 실행 실패: 파일 단위로 읽지 못함(손상, 시트를 읽지 못함, 요구사항 표를 찾지 못함, 파일 전체가 빈 양식 등) 또는 추출 확인에서 제외한 뒤 남은 원문이 0건 | 실행 상태 | 아니오, 다른 파일 |
| `INTERNAL` | 그 밖의 서버 오류 | 500 / 실행 상태 | 경우에 따라 |

- "실행 상태"는 HTTP 오류가 아니라 실패한 실행의 `GET /runs/{id}` 응답 `error` 필드와 SSE `error` 이벤트로 전달된다는 뜻이다.
- `EXTRACTION_FAILED`의 `message`는 파서·추출 확인이 만든 짧은 안내(`notice`)다. 「자세히 보기」 문장은 SSE `error` 이벤트 `payload.detail`에 있다. 다른 실행 실패는 내부 내용을 숨기고 코드별 고정 문구를 쓴다.
- 비동기 실행 중 오류는 `GET /runs/{id}`와 SSE `error` 이벤트로 전달한다.

## 산출물 형식

| kind | 허용 file_format | 비고 |
|---|---|---|
| `requirements` | md | 중간 |
| `functions` | md, pdf | PDF는 승인된 revision에서만 |
| `erd` | mmd, pdf | PDF는 승인된 revision에서만 |
| `ddl` | sql | |
| `rtm` | xlsx, csv | |
| `review` | md | |

- 다른 조합은 422.
- 승인 전 파일은 draft 표식·메타데이터를 포함한다.
- 요청 revision의 객체 존재·접근 권한을 확인한 뒤 `Content-Disposition`으로 안전한 파일명을 지정한다.
- 파일명은 `specton-<kind>-r<revision>.<file_format>`, 승인 전이면 `-draft`를 붙인다. `ETag`는 산출물 해시다.
- 쿼리 이름은 `ArtifactRef`와 같은 `file_format`이다 (#94 이름 정리, #16).
