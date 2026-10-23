# 역할·협업

> 상태: **초안** (역할 구성은 제안, 사람 배정은 회의 결정 전)

## 역할 배정

| 역할 | 하는 일 | 에이전트 | 담당 | 백업 |
|---|---|---|---|---|
| R1 실행 제어·통합 | 그래프 연결, HITL 멈춤·재개, 병렬 합류, 재작업 상한. 공통 LLM client·stub | A05, A09 | 미정 | 미정 |
| R2 입력·분석·평가 | 문서 파싱·원문 위치, 요구사항 분석, 평가 데이터·채점 | A01, A06 | 미정 | 미정 |
| R3 기능·API·저장 | 데이터 계약 주관, API·실행 상태 저장, 기능 명세·RTM | A02, A07 | 미정 | 미정 |
| R4 데이터 모델·검증 | 엔티티·모델 정리·DDL, 규칙 검사, 격리 DB 검증 | A03, A08 | 미정 | 미정 |
| R5 관계·시각화·웹 | 관계 설계, ERD·최종 PDF, React 화면, AWS 배포 | A04 | 미정 | 미정 |

- 각 역할이 전체 흐름의 어느 단계를 맡는지는 [03 아키텍처의 실행 흐름도](03-architecture.md#실행-흐름)에 역할 색으로 표시했다.
- 추가 책임: 평가 정답 제작(R2 제안, 혼자 승인하지 않음), AWS 배포(R5 제안). 둘 다 담당을 명시한다 (ADR-0001).
- R5는 웹·PDF·배포가 몰려 있다. R3이 API 연동을 지원하는 백업을 권장한다.
- 프론트·문서·QA만 맡는 사람은 없다. 모든 역할이 에이전트 1~2개와 주변 코드를 맡는다.

## 코드 소유 범위

| 역할 | 폴더 |
|---|---|
| R1 | `specton/llm/`, `specton/graph.py`, `specton/review/`(리뷰어 노드 틀·병합), `.github/workflows/`, `tests/integration/` |
| R2 | `specton/ingest/`, `specton/packs/`, `domain_packs/`, `eval/` |
| R3 | `specton/contracts/`, `specton/api/`, `specton/persistence/`, `specton/export/`(기능 명세·RTM) |
| R4 | `specton/codegen/`(모델 정리·DDL), `specton/validate/`, `specton/review/`(규칙), `docker/postgres/` |
| R5 | `specton/codegen/`(Mermaid), `specton/export/`(PDF), `frontend/`, 배포 구성 |

- 에이전트 노드와 few-shot(`domain_packs/<pack>/examples/A0x.yaml`)은 해당 에이전트 담당이 소유한다.
- `.github/CODEOWNERS`에 경로별 매핑이 주석으로 준비되어 있다. 배정 후 아이디를 넣어 활성화한다.

## 역할 간 인계

| 주는 쪽 → 받는 쪽 | 넘겨주는 것 | 시점 |
|---|---|---|
| R3 → 전원 | 데이터 계약 (`contracts/`) | 가장 먼저 |
| R1 → 전원 | LLM client·stub, 리뷰어 노드 틀 | 가장 먼저 |
| R2 → R3 | 확인된 요구사항 | A01 완료 |
| R3 → R4 | 기능 목록 | A02 완료 |
| R4 → R5 | 엔티티·속성 | A03 완료 |
| R4·R5 → R3 | 고정된 모델 → RTM | 모델 정리 완료 |
| R3 → R5 | API 명세 (OpenAPI) | 화면 연동 전 |

앞 단계가 늦어도 고정 응답(fixture)으로 먼저 구현하고, 계약이 동결되면 실제로 연결한다.

## 협업 도구

| 도구 | 용도 |
|---|---|
| GitHub 저장소 | 코드·문서의 기준. 결정은 `docs/adr/`에 기록 |
| GitHub Issues·[Projects](https://github.com/users/surplus96/projects/1) | 작업·결함. 초기 작업 23개는 이슈 #3~#25 (마일스톤별 목록은 [01 개요](01-overview.md#마일스톤)) |
| Notion | 읽기용 안내·결정 링크 |
| Slack | 알림·논의. 메시지만으로 계약을 바꾸지 않음 |

브랜치·커밋·PR·리뷰 규칙은 [CONTRIBUTING](../CONTRIBUTING.md)을 따른다.

## 완료 기준

- 요구사항 연결, 정상/오류/경계 테스트, 타입·린트, 문서·예시, 관련 인터페이스 통합, 리뷰 반영을 모두 확인한다.
- 기대값·정답을 바꿔 테스트를 통과시키려면 별도 근거와 검토를 남긴다.
- 문서를 만들었다는 이유로 WBS 이슈를 닫지 않는다.

## 일일 공유 양식

```text
완료: REQ / WBS / 에이전트 ID
변경한 계약:
테스트 증거:
다음 작업:
막힌 이유·필요한 결정:
리뷰 요청 대상:
```

기능을 넘길 때는 예시 입력·예상 출력·오류 사례·실행 명령·팩/프롬프트 버전·미정 사항을 함께 준다.
