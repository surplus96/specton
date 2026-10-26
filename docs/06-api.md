# API

> 상태: **초안** (구현 전)

Specton 실행 제어용 API다. 후속 확장에서 생성하는 재고·설비 업무 API와 다르다. 웹은 이 API만 호출한다.

## 기본 규칙

- 응답은 UTF-8 JSON, 파일은 해당 MIME 타입, 진행 이벤트는 `text/event-stream`.
- 장기 실행 요청은 **202**와 `run_id`를 반환한다. 202는 설계 성공을 뜻하지 않는다.
- 서버 세션의 소유자 컨텍스트로 실행 접근을 검사한다. 세션 발급 방식은 미정 (ADR-0011).
- 상태를 바꾸는 요청은 `expected_revision`을 받아 낙관적 잠금으로 처리한다.
- 저장소 파일 경로·비밀값·내부 예외를 응답에 넣지 않는다.

## 엔드포인트

| 메서드·경로 | 입력 | 정상 결과 | 주요 오류 |
|---|---|---|---|
| `POST /runs` | multipart `file`(.xlsx/.csv/.pdf/.hwpx/.hwp), `pack` | 202 `run_id`·`status`·`revision` | 413 한도 초과, 415 형식, 422 팩/입력 |
| `GET /runs` | `status`·`limit` 선택 | 200 소유자 실행 목록 | 422 조회 조건 |
| `GET /runs/{id}` | — | 200 상태·revision·진행·interrupt·요약 오류 | 404 없음/접근 불가 |
| `GET /runs/{id}/events` | `Last-Event-ID` 선택 | 200 SSE 스트림 | 404, 409 이벤트 재조회 필요 |
| `GET /runs/{id}/view` | `section`, `revision` 선택 | 200 화면용 JSON (추출 블록·요구사항·설계 모델·지적·산출물 목록) | 404, 409 다른 revision |
| `POST /runs/{id}/resume` | `interrupt_id`, `expected_revision`, `response` | 202 재개 상태 | 409 오래된/이미 응답한 interrupt, 422 잘못된 답변 |
| `POST /runs/{id}/cancel` | `expected_revision` | 202 취소 요청 상태 | 409 이미 완료/충돌 |
| `GET /runs/{id}/artifacts/{kind}` | `format`, `revision` | 200 파일 | 404, 409 미생성/다른 버전, 422 형식 불가 |
| `GET /health` | — | 200 기동 상태 (구현됨) | — |

계약 초안: [api/openapi.json](api/openapi.json) (OpenAPI 3.1.1). Pydantic 구현은 `specton/contracts/api.py`이며 `tests/unit/test_contracts_api.py`가 필드·필수 항목·열거값이 같은지 대조한다. 스키마는 `Error`, `ErrorCode`, `SseEvent`, `SseEventData`, `Interrupt`, `RunStatus`, `RunSummary`, `RunView`, `ResumeRequest`, `ExtractionResponse`, `RequirementsResponse`, `ReviewResponse`.

- 초안은 계약 동결(ADR-0009) 때 확정한다. 바꿀 때는 이 문서와 같은 PR에서 고친다.
- 구현 후에는 FastAPI가 생성하는 `/openapi.json`과 초안을 대조해 차이를 없앤다.

## 사용자 확인 응답 (`resume`)

`response.kind`로 3종을 구분한다.

| kind | 내용 | 규칙 |
|---|---|---|
| `extraction` | `block_id`별 수정 텍스트, `confirmed` | 수정본은 원문과 분리 저장 |
| `requirements` | `req_id`별 `keep`/`edit`/`split`, `texts` | split의 새 ID는 서버가 부여 |
| `review` | `approve`/`revise`/`hold`, `feedback` | approve는 현재 revision과 차단 오류 유무 확인 |

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

- 동시에 보낸 같은 응답은 하나만 적용한다. 중복·오래된 응답은 409와 현재 revision을 돌려주며 두 번째 실행을 만들지 않는다.
- approve가 아니면 산출물을 완료본으로 승격하지 않는다.

## SSE

- 이벤트 ID는 run 안에서 단조 증가한다.
- `event`: `status` / `interrupt` / `artifact` / `error` / `completed` / `cancelled`
- `data`: `run_id`, `revision`, `stage`, `message`, 필요한 `payload`
- 원문 전체와 비밀값은 넣지 않는다. 연결 종료는 실행 취소가 아니다.
- 재접속하면 `Last-Event-ID` 이후를 재생한다. 보존 범위를 벗어나면 409와 상태 조회 경로를 안내한다.

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

- `code`/`message`/`run_id`/`retryable`로 통일한다. 코드 값 후보는 `ErrorCode`: `RUN_NOT_FOUND`, `RUN_REVISION_CONFLICT`, `INTERRUPT_STALE`, `EVENT_REPLAY_EXPIRED`, `ARTIFACT_NOT_READY`, `ARTIFACT_FORMAT_UNSUPPORTED`, `UPLOAD_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE`, `PACK_UNSUPPORTED`, `INVALID_RESPONSE`, `INTERNAL`. 목록은 계약 동결 때 확정한다.
- 비동기 실행 중 오류는 `GET /runs/{id}`와 SSE `error` 이벤트로 전달한다.

## 산출물 형식

| kind | 허용 format | 비고 |
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
