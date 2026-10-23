# API

> 상태: **골격 (회의 전)** · 회의 결정 반영 후 작성한다.
> 목적: 실행 제어 API의 엔드포인트와 오류 규칙.
> 원본: 상위 기획 폴더 `docs/개발착수_문서/06_API_명세서.md`, `관리표/openapi.json`

## 엔드포인트

- [ ] POST /runs
- [ ] GET /runs, /runs/{id}, /runs/{id}/view
- [ ] GET /runs/{id}/events (SSE)
- [ ] POST /runs/{id}/resume, /cancel
- [ ] GET /runs/{id}/artifacts/{kind}

## 산출물 형식

- [ ] kind별 허용 형식 (중간 md, 최종 pdf)

## 오류·인증

- [ ] 오류 형식 code/message/run_id/retryable
- [ ] 세션·접근 범위 (ADR-0011)

## OpenAPI

- [ ] `openapi.json` 저장 위치와 갱신 방법
