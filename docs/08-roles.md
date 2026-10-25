# 역할·협업

> 상태: **역할 배정 확정** (ADR-0001, 백업 담당은 미정)

## 역할 배정

| 역할 | 하는 일 | 에이전트 | 담당 | 백업 |
|---|---|---|---|---|
| R1 실행 제어·통합 | 그래프 연결, HITL 멈춤·재개, 병렬 합류, 재작업 상한. 공통 LLM client·stub | A05, A09 | 최태영 (@surplus96) | 미정 |
| R2 입력·분석·평가 | 문서 파싱·원문 위치, 요구사항 분석, 평가 데이터·채점 | A01, A06 | 김희영 (@workbaselab-ops) | 미정 |
| R3 기능·API·저장 | 데이터 계약 주관, API·실행 상태 저장, 기능 명세·RTM | A02, A07 | 박성진 (@c189021) | 미정 |
| R4 데이터 모델·검증 | 엔티티·모델 정리·DDL, 규칙 검사, 격리 DB 검증 | A03, A08 | 김유경 (@yugyeong-k) | 미정 |
| R5 관계·시각화·웹 | 관계 설계, ERD·최종 PDF, React 화면, AWS 배포 | A04 | 김순재 (@kisoja24782-ux) | 미정 |

- 각 역할이 전체 흐름의 어느 단계를 맡는지는 [03 아키텍처의 실행 흐름도](03-architecture.md#실행-흐름)에 역할 색으로 표시했다.
- 추가 책임: AWS 배포는 R5. **평가 세트 수집·정답 작성은 R3 박성진**이 맡는다. 정답 작성자는 팩 작성자(R2)와 달라야 하기 때문이다 (ADR-0014).
- R2는 지표 계산·채점을 맡고, 평가 문서는 팩을 `approved`로 고정한 뒤에만 본다.
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
- `.github/CODEOWNERS`가 위 범위대로 PR 리뷰어를 자동 지정한다.

## 역할 간 인계

| 주는 쪽 → 받는 쪽 | 넘겨주는 것 | 시점 | 주는 이슈 → 받는 이슈 |
|---|---|---|---|
| R3 → 전원 | 데이터 계약 (`contracts/`) | 가장 먼저 | [#4](https://github.com/surplus96/specton/issues/4) → 에이전트·API·입력·평가 이슈 |
| R1 → 전원 | LLM client·stub | 가장 먼저 | [#3](https://github.com/surplus96/specton/issues/3) → [#5](https://github.com/surplus96/specton/issues/5)~[#9](https://github.com/surplus96/specton/issues/9), [#42](https://github.com/surplus96/specton/issues/42) |
| R1 → R1·R2·R3·R4 | 리뷰어 노드 틀 (관점 설정 형식) | 가장 먼저 | [#42](https://github.com/surplus96/specton/issues/42) → [#5](https://github.com/surplus96/specton/issues/5), [#6](https://github.com/surplus96/specton/issues/6), [#7](https://github.com/surplus96/specton/issues/7), [#9](https://github.com/surplus96/specton/issues/9) |
| R2 → R3 | 확인된 요구사항 | A01 완료 | [#5](https://github.com/surplus96/specton/issues/5) → [#6](https://github.com/surplus96/specton/issues/6) |
| R3 → R4 | 기능 목록 | A02 완료 | [#6](https://github.com/surplus96/specton/issues/6) → [#7](https://github.com/surplus96/specton/issues/7) |
| R4 → R5 | 엔티티·속성 | A03 완료 | [#7](https://github.com/surplus96/specton/issues/7) → [#8](https://github.com/surplus96/specton/issues/8) |
| R5 → R4 | 관계 | A04 완료 | [#8](https://github.com/surplus96/specton/issues/8) → [#12](https://github.com/surplus96/specton/issues/12) |
| R4 → R3·R5 | 고정된 모델 → RTM·ERD | 모델 정리 완료 | [#12](https://github.com/surplus96/specton/issues/12) → [#14](https://github.com/surplus96/specton/issues/14), [#13](https://github.com/surplus96/specton/issues/13) |
| R3 → R5 | API 명세 (OpenAPI) | 화면 연동 전 | [#16](https://github.com/surplus96/specton/issues/16) → [#19](https://github.com/surplus96/specton/issues/19) |
| R2 → R3·R2 | `approved`로 고정된 팩 | 평가 전 | [#11](https://github.com/surplus96/specton/issues/11) → [#40](https://github.com/surplus96/specton/issues/40), [#20](https://github.com/surplus96/specton/issues/20) |
| R3 → R2 | 승인된 평가 세트·정답 | 팩 고정 후 | [#40](https://github.com/surplus96/specton/issues/40) → [#20](https://github.com/surplus96/specton/issues/20) |

앞 단계가 늦어도 고정 응답(fixture)으로 먼저 구현하고, 계약이 동결되면 실제로 연결한다. 각 이슈의 "넘겨줄 것"·"받을 것" 섹션에 같은 내용이 있다. 실제로 기다려야 하는 관계는 이슈의 Blocked by로 연결했다.

## 작업 순서

전체 구현은 단계 0 → 4 순서로 진행한다. 같은 단계 안의 작업은 병렬로 한다.

| 단계 | 내용 | 이슈 |
|---|---|---|
| 0 기반 | 모두가 쓰는 계약·client·리뷰어 틀 | [#3](https://github.com/surplus96/specton/issues/3), [#4](https://github.com/surplus96/specton/issues/4), [#42](https://github.com/surplus96/specton/issues/42) |
| 1 에이전트 | 고정 응답으로 에이전트 9개 첫 구현 | [#5](https://github.com/surplus96/specton/issues/5)~[#9](https://github.com/surplus96/specton/issues/9) |
| 2 생성·입력 | 입력 처리, 팩 고정, 평가 세트, 모델 정리, ERD·RTM·DDL, API | [#10](https://github.com/surplus96/specton/issues/10), [#11](https://github.com/surplus96/specton/issues/11), [#40](https://github.com/surplus96/specton/issues/40), [#12](https://github.com/surplus96/specton/issues/12), [#13](https://github.com/surplus96/specton/issues/13), [#14](https://github.com/surplus96/specton/issues/14), [#15](https://github.com/surplus96/specton/issues/15), [#16](https://github.com/surplus96/specton/issues/16) |
| 3 통합 | 그래프·검토 병합·웹·보안 점검·HWPX | [#17](https://github.com/surplus96/specton/issues/17), [#18](https://github.com/surplus96/specton/issues/18), [#19](https://github.com/surplus96/specton/issues/19), [#21](https://github.com/surplus96/specton/issues/21), [#24](https://github.com/surplus96/specton/issues/24) |
| 4 평가·배포 | 평가, AWS 배포, 결함 수정, 시연 | [#20](https://github.com/surplus96/specton/issues/20), [#25](https://github.com/surplus96/specton/issues/25), [#22](https://github.com/surplus96/specton/issues/22), [#23](https://github.com/surplus96/specton/issues/23) |

| 담당 | 순서 |
|---|---|
| R1 최태영 | [#3](https://github.com/surplus96/specton/issues/3) client·stub → [#42](https://github.com/surplus96/specton/issues/42) 리뷰어 노드 틀 → [#9](https://github.com/surplus96/specton/issues/9) A05·A09 → [#18](https://github.com/surplus96/specton/issues/18) 검토 병합 → [#17](https://github.com/surplus96/specton/issues/17) 그래프 → [#22](https://github.com/surplus96/specton/issues/22) 결함 수정 → [#23](https://github.com/surplus96/specton/issues/23) 시연 |
| R2 김희영 | [#5](https://github.com/surplus96/specton/issues/5) A01·A06 → [#10](https://github.com/surplus96/specton/issues/10) 입력 → [#11](https://github.com/surplus96/specton/issues/11) 팩 고정 → [#24](https://github.com/surplus96/specton/issues/24) HWPX → [#20](https://github.com/surplus96/specton/issues/20) 평가 |
| R3 박성진 | [#4](https://github.com/surplus96/specton/issues/4) 계약 → [#6](https://github.com/surplus96/specton/issues/6) A02·A07 → [#16](https://github.com/surplus96/specton/issues/16) API → [#40](https://github.com/surplus96/specton/issues/40) 평가 세트·정답 → [#14](https://github.com/surplus96/specton/issues/14) RTM → [#21](https://github.com/surplus96/specton/issues/21) 접근·한도 |
| R4 김유경 | [#7](https://github.com/surplus96/specton/issues/7) A03·A08 → [#12](https://github.com/surplus96/specton/issues/12) 모델 정리 → [#15](https://github.com/surplus96/specton/issues/15) DDL·규칙 |
| R5 김순재 | [#8](https://github.com/surplus96/specton/issues/8) A04 → [#13](https://github.com/surplus96/specton/issues/13) ERD·PDF → [#19](https://github.com/surplus96/specton/issues/19) 웹 → [#25](https://github.com/surplus96/specton/issues/25) AWS |

프로젝트 보드의 **단계**·**순서** 필드에 같은 값이 들어 있다. "내 작업" 뷰를 순서로 정렬하면 위 표의 순서대로 보인다.

## 협업 도구

| 도구 | 용도 |
|---|---|
| GitHub 저장소 | 코드·문서의 기준. 결정은 `docs/adr/`에 기록 |
| GitHub Issues·[Projects](https://github.com/users/surplus96/projects/1) | 작업·결함. 초기 작업 23개는 이슈 #3~#25 (마일스톤별 목록은 [01 개요](01-overview.md#마일스톤)) |
| Notion | 읽기용 안내·결정 링크 |
| Slack | 알림·논의. 메시지만으로 계약을 바꾸지 않음 |

브랜치·커밋·PR·리뷰·병합 규칙과 보드 상태 흐름은 [CONTRIBUTING](../CONTRIBUTING.md)을 따른다. `main` 병합은 R1만 한다.

## 완료 기준

- 요구사항 연결, 정상/오류/경계 테스트, 타입·린트, 문서·예시, 관련 인터페이스 통합, 리뷰 반영을 모두 확인한다.
- 기대값·정답을 바꿔 테스트를 통과시키려면 별도 근거와 검토를 남긴다.
- 이슈는 PR 병합으로만 닫는다. 문서를 만들었다는 이유로 작업 이슈를 닫지 않는다.

## 일일 공유 양식

```text
완료: 이슈 #번호 / REQ / 에이전트 ID
변경한 계약:
테스트 증거:
다음 작업:
막힌 이유·필요한 결정:
리뷰 요청 대상:
```

기능을 넘길 때는 예시 입력·예상 출력·오류 사례·실행 명령·팩/프롬프트 버전·미정 사항을 함께 준다.
