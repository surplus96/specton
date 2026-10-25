# 개요·범위

> 상태: **초안** (회의 결정 전)

## 목표

고객 요구사항 문서를 읽어 **기능 명세서·ERD·DDL·RTM** 초안을 만들고, 누락·모순을 검토한 뒤 사람의 승인을 거쳐 내보내는 설계 에이전트 서비스를 만든다.

| 항목 | 내용 |
|---|---|
| 대상 사용자 | PM/PL·컨설턴트(요구사항 입력·해석 확정), 아키텍트(SWA/AA, 설계 검토·최종 승인) |
| 기준 시나리오 | 제조 MES 구축 사업의 분석·설계 단계 |
| 도메인 | 재고·자재(`inventory`)를 먼저 완성하고 설비(`maintenance`)를 이어 적용. 공통 코드는 바꾸지 않고 팩만 교체 |
| 기간·팀 | 2026-10-29~11-11, 팀 설계로 5인 (팀장 최태영) |

## 기본 흐름

입력(정형 → 비정형) → 원문 확인 → 요구사항 분석·HITL 1 → 기능·모델 설계 → ERD·DDL·RTM 생성 → 규칙·LLM 검토 → 재작업 또는 HITL 2 승인 → 다운로드.
자세한 흐름은 [03 아키텍처](03-architecture.md).

## MVP 범위

| 영역 | 범위 | 비고 |
|---|---|---|
| 입력 | Excel·CSV(정형) → PDF(비정형) 순서로 구현 | HWPX·HWP는 stretch 제안 (미정, ADR-0002) |
| 입력 양식 | 기준 5열 + 선택 "관련 요구사항" 열 제안 | 미정 (ADR-0003) |
| 산출물 | 중간: Markdown. 최종: 기능 명세서(Markdown·PDF), ERD(Mermaid·PDF), DDL(SQL), RTM(Excel·CSV), 검토 보고서(Markdown) | PDF는 승인 시점에 1회 생성 (확정) |
| 웹 | React. 업로드 → 확인·승인 → 결과 보기 화면 3개 제안 | 화면 라이브러리 미정 (ADR-0005) |
| 배포 | 로컬 Docker PostgreSQL 개발, AWS Docker 컨테이너 배포 | 구성 미정 (ADR-0013) |

축소 후보: REQ-19 웹(화면 3개), REQ-25 한도(타임아웃만), REQ-27 HWPX·HWP(stretch). 범위를 줄이면 [02 요구사항](02-requirements.md)과 RTM에 바로 반영한다.

## 제외 범위 (후속 확장)

10/29~11/11 인수 범위에 넣지 않는다.

| ID | 확장 | MVP와의 연결 |
|---|---|---|
| EXT-01 | 외부 리서치 기반 미지원 도메인 설계 | 미지원 팩 안내 후 별도 조사·사용자 승인으로 진입 |
| EXT-02 | 승인된 산출물로 업무 API·DB 구현, 오픈소스 재고/설비 시스템 연동 | 생성 DDL을 외부 제품 내부 DB에 직접 적용하지 않음 |
| EXT-03 | 승인 이후 요구사항 변경 영향 분석·버전 갱신 | MVP의 revision·model_snapshot·RTM 추적 재사용 |

그 밖에 업무 DB 영구 배포, 재고 업무 실행, UI의 범용 모델 편집기는 범위 밖이다.

## 완료 기준

- 두 도메인의 승인된 대표 입력으로 네 산출물과 검토 보고서가 생성된다.
- 원문 연결·수정/재개·다운로드를 시연한다.
- DDL 실행 성공은 승인 평가 집합에서 확인한다. 샘플 하나의 성공을 일반 성능으로 표현하지 않는다.
- 측정 지표: 분류·설계 정확도, 결함 탐지율, DDL 실행 성공률, 처리 시간. 목표값은 첫 기준 실행 후 결정 (미정, ADR-0014).
- 실패·미실행·남은 결함을 명시한다.

## 마일스톤

| 마일스톤 | 범위 | 이슈 |
|---|---|---|
| M1 계약·환경 | 데이터 계약·대표 입력·개발 환경, 전원 첫 에이전트 구현 | [#3](https://github.com/surplus96/specton/issues/3), [#4](https://github.com/surplus96/specton/issues/4), [#5](https://github.com/surplus96/specton/issues/5), [#6](https://github.com/surplus96/specton/issues/6), [#7](https://github.com/surplus96/specton/issues/7), [#8](https://github.com/surplus96/specton/issues/8), [#9](https://github.com/surplus96/specton/issues/9), [#42](https://github.com/surplus96/specton/issues/42) |
| M2 설계 파이프라인 | 분석→설계→생성 연결, 코드 생성·DB 검증 | [#11](https://github.com/surplus96/specton/issues/11), [#12](https://github.com/surplus96/specton/issues/12), [#14](https://github.com/surplus96/specton/issues/14), [#15](https://github.com/surplus96/specton/issues/15) |
| M3 문서 입출력·웹 | PDF 입출력, HWPX/HWP 연결, React 웹 뼈대 | [#10](https://github.com/surplus96/specton/issues/10), [#13](https://github.com/surplus96/specton/issues/13), [#19](https://github.com/surplus96/specton/issues/19), [#24](https://github.com/surplus96/specton/issues/24) |
| M4 검토·재작업 통합 | 4관점 검토·재작업·HITL·지속성, 1차 E2E | [#16](https://github.com/surplus96/specton/issues/16), [#17](https://github.com/surplus96/specton/issues/17), [#18](https://github.com/surplus96/specton/issues/18), [#21](https://github.com/surplus96/specton/issues/21) |
| M5 평가·배포·인수 | 품질 평가·결함 수정·문서 동결·AWS 배포·릴리스 | [#20](https://github.com/surplus96/specton/issues/20), [#22](https://github.com/surplus96/specton/issues/22), [#23](https://github.com/surplus96/specton/issues/23), [#25](https://github.com/surplus96/specton/issues/25) |

작업은 GitHub Issues(#3~#25)와 [Projects 보드](https://github.com/users/surplus96/projects/1)에서 관리한다.
