# maintenance 팩 근거

> 상태: **초안** (조사일 2026-10-23, 웹 자료 기준. 유료 표준 원문은 확인하지 않았다)

설비관리 팩(`words.yaml`·`term_specs.yaml`·`patterns.yaml`)과 개발·평가 세트의 자료 선택 근거다.

## 자료 선택

| 대상 | 자료 | 이유 |
|---|---|---|
| 개발용 요구사항 | 설비 MNT-001~022 (개발용 세트, 비공개) | 재고 INV-001~016과 같은 출처. 재고-설비 통합 3건 포함 |
| 평가용 요구사항 | Odoo·ERPNext 보전 기능을 참고해 **팩 작성자가 아닌 사람이 별도 작성** (#40) | 개발용과 출처가 달라 정답 누출 위험이 낮다 (ADR-0014) |
| `common` 단어·도메인 | 공공데이터 공통표준 ([common 근거](../common/RATIONALE.md)) | 도메인과 무관한 공통 사전 |
| `maintenance` 단어·용어 | EN 13306 용어 구분 + 스마트공장 수준별 설비 요구사항 | 보전 유형·고장·작업 용어의 표준 구분 |
| `maintenance` 패턴 | CMMS 공통 객체 모델 + Odoo·ERPNext·openMAINT 구조 | 실제 제품에서 쓰는 모양 |
| 고장 분류 (선택) | ISO 14224의 고장 모드·원인 분리 원칙 | 고장 코드를 하나로 뭉치지 않는 근거 |

## MVP 범위

스마트공장 추진단 자료(v3.1, 2017)는 설비 기능을 수준별로 나눈다. **MVP는 중간1 수준**으로 잡는다.

| 수준 | 기능 | MVP |
|---|---|---|
| 중간1 | 설비 대장·계층, 예방보전 계획·작업, 고장 신고, 작업 이력, 부품 사용 | 포함 |
| 중간2 | 예지보전, 설비 상태 자동 모니터링 | 제외 (센서·시계열 데이터 필요) |

오래된 자료라 현행 기준과 대조가 필요하다.

## 용어: EN 13306

- 보전 기본 용어, 품목(설비), 고장·결함·상태, 보전 유형, 보전 활동을 정의하는 유럽 표준(2017판)이다.
- `words`·`terms`의 **분류 기준**으로만 쓴다. 예: 예방보전과 사후보전, 고장(failure)과 결함(fault)의 구분.
- 유료 표준이라 원문을 옮기지 않는다.

## 패턴: CMMS 공통 객체 모델

| 객체 | 설명 | 패턴 (`patterns.yaml`) |
|---|---|---|
| 설비(asset) | 사업장 → 구역 → 라인 → 설비 → 부품 계층 | `self_reference_hierarchy` |
| 예방보전 계획 | 주기·대상 설비·점검 항목 | `plan_generates_work_orders` |
| 보전 요청 | 고장 신고·작업 요청 | `request_to_work_orders` |
| 작업 지시 | 배정·수행·완료 상태 | `status_transition_with_history` |
| 계측값 | 가동 시간·카운터 | MVP 제외 후보 |
| 부품 사용 | 작업에 쓴 예비품 | 재고 팩과의 연결 지점 (통합 시나리오) |

참고 구현:

| 제품 | 확인한 구조 |
|---|---|
| Odoo Maintenance | 설비(이름·분류·소유 회사), 보전 요청(팀·담당자·예정일·예상 시간), 유형 Corrective/Preventive, 단계 New → In Progress → Repaired → Scrap |
| ERPNext Asset Maintenance | 설비별 보전 계획의 작업 목록(유형·주기·담당·기간), 주기로 다음 예정일 계산, 작업마다 Maintenance Log |
| openMAINT | CMDBuild 기반. 자산 대장, 예방·사후 보전, 작업 지시, 재고, 공간 관리 |

## 고장 분류: ISO 14224 (선택)

- 신뢰성·보전 데이터를 설비 데이터 / 고장 데이터 / 보전 데이터로 나눈다.
- 고장 **모드**(관찰된 증상), **원인**(설계·제작·설치·운전·보전), **메커니즘**을 따로 기록한다.
- 석유·가스 산업 표준이라 "모드와 원인을 다른 속성으로 둔다"는 원칙만 패턴에 반영한다.

## 쓰지 않는 자료

- KAMP 제조 AI 데이터셋 50종: 예지보전 모델 학습용 시계열 데이터라 요구사항 → 설계 산출물을 다루는 팩 자료로 맞지 않는다.

## 남은 작업 (#11)

1. `words`·`terms`: MNT-001~022에 나오는 용어를 EN 13306 구분에 맞춰 정리한다.
2. `patterns`: 위 객체 패턴과 개발용 세트 가정(`development set assumption Axx`) 패턴을 확정한다.
3. 평가용 세트는 팩 작성자가 아닌 사람이 Odoo·ERPNext 기능을 참고해 쓴다 (#40).

## 출처

- [openMAINT 개요 (FitGap)](https://us.fitgap.com/products/012056/openmaint) · [CMMS data model (Fabrico)](https://www.fabrico.io/blog/cmms-data-model/)
- [EN 13306 (BSI)](https://knowledge.bsigroup.com/products/maintenance-maintenance-terminology) · [SN EN 13306:2018 개요](https://insights.snv.ch/en/page/overview-of-sn-en-133062018-maintenance-terminolog-en)
- [ISO 14224 신뢰성 데이터 발표자료](https://standard.no/globalassets/fagomrader-sektorer/petroleum/rio_de_janeiro/4-collection_and_exchange_of_reliability_data-j_t_selvik.pdf) · [ISO 14224 failure taxonomy (Fabrico)](https://www.fabrico.io/blog/iso-14224-failure-taxonomy-codes/)
- [Odoo 16 Maintenance (Cybrosys)](https://www.cybrosys.com/odoo/odoo-books/odoo-book-v16/maintenance/maintenance-request/) · [ERPNext Asset Maintenance](https://docs.frappe.io/erpnext/user/manual/en/asset-maintenance)
- [스마트공장 추진단 자료 v3.1 (2017)](https://www.goesan.go.kr/DATA/bbs/42/C98451DB-2EBD-F3C8-5E5D-478B966EF36F.pdf) · [KAMP 제조AI 데이터셋 50종](https://www.data.go.kr/data/15089213/fileData.do)
