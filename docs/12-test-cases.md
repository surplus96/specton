# 테스트 케이스

2026-11-10 #289 추가 검증(TC-F19·F20): 기본 1,926 passed·6 skipped(336 DB 항목 제외),
실행기·고정 LLM API·소유자 격리 DB 103 passed, 실제 두 PDF·8종 통합 4 passed.
노드 task ID·phase 중복 억제, 기존 체크포인트 위치 유지, HITL 재시작 뒤 이벤트·호출 수치 보존,
취소 결과 미저장·종료 이벤트 순서, 서버 정리 요약·SSE 호출 메타데이터를 확인했다.
웹 216 passed·lint·build·check:api 통과. Chrome을 실제 로컬 API·DB(고정 LLM)에 연결해
업로드→추출·분석 확인→최종 검토와 A03 호출 정보·정리 요약(4테이블·11컬럼·3FK)·SQL 미리보기를
확인했다. 실제 API 수정 요청으로 revision 1을 만든 뒤 revision 0 선택 시 재작업 0회·이벤트 격리도 확인했다. 기존 mock의 단계 추정과 서버 노드 이벤트 표시는 구분한다. 유료 LLM 호출과 OS 강제 종료
시험은 이 추가 검증에 포함하지 않는다. 기존 실제 LLM 인수·평가 기록을 대체하지 않는다.

> 상태: **초안** (실행 결과는 각 행의 「상태」 칸에 적는다. 담당·검토자는 역할 배정 후 지정)

요구사항 27개와 에이전트 9개에 대응하는 시나리오 37개다(TC-F22는 ADR-0015 조건부 확인의 멈추지 않는 경로). 요구사항별 대응은 [02 요구사항](02-requirements.md), 층위·실행 명령은 [07 테스트·평가](07-testing-eval.md)를 따른다.

## 공통 조건

| 구분 | 사전 조건 | 확인 방법 |
|---|---|---|
| 기능·비기능 (TC-F, TC-N) | 승인된 입력·설계 또는 결함 픽스처 | 수용 기준에 따라 결과·DB·로그를 확인. 작성자 외 교차 검토자가 증거를 확인 |
| 에이전트 (TC-A) | 고정 응답(fixture)과 원문·허용 참조 목록 | 정상 응답·계약 오류·근거 부족 사례를 각각 실행. 실제 LLM 호출 없음 |

- 실행하지 않은 케이스를 통과로 표시하지 않는다. 결과는 PR 본문과 평가 보고서에 남긴다.
- 실패는 재현 입력·예상/실제·로그·환경과 TC ID를 담아 이슈(`type:bug`)로 등록한다.

## 기능 (TC-F)

| TC | 요구사항 | 대상 | 시나리오·기대 결과 | 층위 | 상태 |
|---|---|---|---|---|---|
| TC-F01 | REQ-01 | Excel·CSV 요구사항 입력 | 정상·필수 열 누락·중복 ID Excel·CSV를 입력한다. 정상 행은 값과 위치가 보존되고 오류 행을 조용히 버리지 않는다. | unit/integration | 단위 통과 (#10) |
| TC-F02 | REQ-02 | PDF 입력·추출 확인 | 향후 입력 지원 시 텍스트형·표형 PDF의 원문 대조·오류 처리를 시험한다. 현재는 PDF 업로드 415 거절을 유지한다. | unit/integration | 범위 밖(후속): REQ-02 제외, 10/29 결정 2·11/2 #10 공지 및 2026-11-10 R1 재확인. 이번 필수 인수·평가 대상 아님 |
| TC-F03 | REQ-03 | 도메인 팩 적용 | 같은 요구를 두 팩 조건으로 실행해 지정 팩 버전이 기록되는지 확인한다. 미지원 팩 요청은 자동 검색하지 않는다. | unit/integration | 단위·DB 일부 통과 (2026-11-10): 재고·설비 두 팩으로 각각 실행해 지정한 팩 ID·버전이 설계 상태와 기능 명세에 기록 (`test_runner.py` 새 실행의 팩, `test_document_pipeline.py` 두 팩 parametrize), 미지원 팩은 검색 없이 422 `PACK_UNSUPPORTED` (`test_api_runs.py`), 팩 manifest·이름 검사 (`test_pack_loader.py`). 같은 요구 문장을 두 팩으로 돌리는 시험은 아님(팩마다 입력이 다름) |
| TC-F04 | REQ-04 | 요구사항 분석 | 복합 요구·모호 표현·NFR가 있는 승인 픽스처를 분석한다. 원문 연결과 분할 관계를 확인하고 분류는 기준 라벨과 비교한다. | integration/eval | 미실행 |
| TC-F05 | REQ-05 | 요구사항 사용자 확인 | 분석 후 대기 상태에서 프로세스를 재시작하고 답변한다. 같은 실행에서 재개되고 오래된 revision 답변은 거절된다. | unit/integration | API·DB 통과 (2026-11-10): 분석 확인 대기에서 API·그래프·실행기를 재생성해 요구사항·interrupt를 복원하고 A01 재호출 없이 재개. 이전 revision 답변 409 확인 (`test_dual_pdf_pipeline.py`). OS 프로세스 종료·재기동 자체는 미실행 |
| TC-F06 | REQ-06 | 기능 명세 도출 | 명시 우선순위와 미지정 요구를 함께 입력한다. 명시값은 보존하고 미지정 값은 근거 없이 확정하지 않으며 CRUD는 아직 채우지 않는다. | integration/eval | 미실행 |
| TC-F07 | REQ-07 | 엔티티·속성·CRUD | 기준 엔티티/속성과 기능을 입력한다. req_ids와 기능별 CRUD가 연결되고 존재하지 않는 기능/엔티티 참조는 거절된다. | integration/eval | 미실행 |
| TC-F08 | REQ-08 | 관계 도출 | N:M·선택 관계·자기참조 사례를 검토한다. 출력 참조가 유효하며 임의 FK 속성을 LLM 출력에 추가하지 않는다. | integration/eval | 미실행 |
| TC-F09 | REQ-09 | 공통 모델 정규화 | 같은 모델을 두 번 정규화한다. 중복 연결 테이블이 생기지 않고 ID/이름과 원문 추적이 유지된다. | unit/integration | 단위·DB 통과 (#12). 단위: 같은 입력을 두 번 정리해도 결과·ID·물리명이 같고 입력은 그대로, 목록 순서만 바꿔도 같음, N:M을 두 번 정리해도 연결 테이블은 하나이고 파생 테이블·칸·FK가 원래 관계의 req_ids를 물려받음 (`test_normalize.py`). DB: 같은 상태를 다시 저장해도 스냅샷 하나, 정리 모델을 설계와 함께 저장·해시, 승인된 모델은 바뀌지 않음 (`test_snapshots.py`, PostgreSQL 18). 재작업 전후 기능·관계는 짝을 맞추지 않음(ADR-0016) |
| TC-F10 | REQ-10 | ERD 생성 | 관계/키/선택 여부가 포함된 ERD를 렌더링한다. 원본 모델과 관계 수·참조가 일치하며 문법 오류가 없다. | unit/integration | 단위 통과 (#13 `test_erd.py`: FK마다 관계선 1개·모든 관계 표시·참조 테이블 일치·카디널리티·선택·식별 표기·자기참조, `test_erd_areas.py`: 영역별 상세 ERD의 관계선 합 = 전체 ERD. Mermaid 문법은 11.15.0·11.17.2 실측(ADR-0004, #223), 실제 mermaid-cli 테스트는 mmdc가 있는 환경만(CI 생략)). 실제 LLM 실행 통과 (#19 E2E, 아래 TC-F19와 같은 실행): 그 실행의 정리 모델 관계 6개(REL-01~06) = ERD `mmd` 관계선 6개 = DDL FK 6개, 테이블 5개 일치. ERD PDF 6쪽(개요·영역 상세·테이블 정의서) 생성; 2026-11-10 고정 LLM 응답·두 PDF 동시 활성화 API 통합도 통과 (`test_dual_pdf_pipeline.py`, 아래 #17 기록) |
| TC-F11 | REQ-11 | DDL 생성·실행 검사 | 정상 SQL과 잘못된 FK/비허용 문장을 검사한다. 오류를 구분하고 성공·실패 뒤 검증 객체가 남지 않는다. | unit/integration | 단위·DB 통과 (#15 생성·허용 SQL·격리 DB 실행·롤백·잔여 확인, 로컬 PostgreSQL 18). RULE-07 지적 변환: 실제 생성기 SQL의 문장별 대상 연결(실패 결과 주입) 단위 통과, 실제 격리 DB 실행 실패(표 2개 설계의 생성 SQL에서 두 번째 표의 첫 타입만 결함으로 변경) → RULE-07 지적·HITL 2 DB 통과. 2026-11-10 두 PDF 동시 활성화 상태에서 실제 SQL 실행 실패 → 승인 차단 → 수정·재검증·승인도 통과 |
| TC-F12 | REQ-12 | RTM 생성 | 의도적으로 기능 연결 하나를 제거한다. RTM에서 미연결로 표시되고 LLM이 링크를 추정하여 메우지 않는다. | unit/integration | RTM 생성·원문 추적은 통합 통과 (#17 실제 API로 RTM 생성·승인·다운로드: `test_document_pipeline.py`, `test_scripted_flow.py`, db 마커). 기능 연결을 뺐을 때의 미연결 표시는 단위·API DB 통과: `test_removed_function_link_shows_unlinked_without_guessing`, `test_design_rules_pipeline.py::test_unlinked_rtm_survives_hold_restart_and_only_repaired_revision_is_approved`. 재고에서 기능 연결 하나를 뺀 FR이 CSV·Excel 다운로드에 미연결·빈 기능으로 남고 미연결 건수 1임을 확인. 보류·API/그래프/실행기 재생성 뒤 같은 바이트 유지, RULE-02 critical 승인 422·상태 불변, 사용자 수정 후 새 revision에서 연결·미연결 0건·동일 바이트 승인 다운로드, 이전 revision RTM은 초안 유지. LLM 판단은 고정 응답이며 생성·SQL·저장·API는 실제 구현 |
| TC-F13 | REQ-13 | 규칙 기반 검사 | 각 규칙의 정상·결함·허용 예외 픽스처를 실행한다. 삭제 면제 엔티티를 CRUD 오류로 오판하지 않는다. | unit/integration | RULE-01~05 정리 실패 지적 변환 단위 42개 통과 (`test_normalization_findings.py`: 실제 정리 문제별 규칙 지적, 사람 확인 우선, 입력 추적 세부 유형, FK 충돌·지원하지 않는 관계 구분). RULE-02·06 단위 12개 통과: 미연결 FR, 미사용 엔티티의 기능/데이터 설계/A09 복귀, 미등록·허용 밖·실사용 CRUD 면제, 조회 전용·삭제 면제·원장 면제. R1 그래프·API DB 통과 (`test_design_rules_pipeline.py`): 재고·설비 자동 재작업, 반복·상한·판단 불가의 HITL 2, critical 승인 422·기록 불변, 보류·재시작·수정 후 새 revision 승인·동일 SQL 해시 다운로드. LLM 판단은 고정 응답이며 정리·SQL 검증·생성·저장·승인 API는 실제 구현을 사용. SC-01~06 단위 49개 통과 (`test_standard_compliance.py`, 시험 함수 29개): SC별 정상·결함, 팩 용어·FK 칸 제외, strict·pg_native 타입 비교와 SC-03·06 한쪽만, 팩 등록 낱말(장부) 통과, SC-04 이음동의어 minor 참고·공식 단어·금칙어 제외(#260), 미진단 집계·준수율, 실제 공통표준 원본 sha256 고정·폐기 줄 제외·겹치는 이름 미진단, 「수작업여부」 공식 약어 충돌(SC-05), 재고 A03 예시 설계 → 정리 → SC 0건, 이름 나누기(끝에서부터 긴 단어, 공식 용어는 약어 경계로 앞 조각부터 긴 낱말 — 공식 용어 전체가 나뉘고 분류어 아닌 끝 단어 0건), SC에 critical 거절. SC 그래프·실제 API DB 회귀: minor 참고·major 데이터 설계 재작업·major 사람 조치, 사람 조치 우선과 critical 승인 422 유지, 검토·수정 후 승인·다운로드 (#11 R1 인계) |
| TC-F14 | REQ-14 | 4관점 병렬 검토 | 한 리뷰어를 지연·실패시키고 다른 결과를 반환한다. 결과 유실 없이 불완전 검토 상태를 표시하며 전체 성공으로 처리하지 않는다. | integration/eval | stub 그래프 통합 통과 (#18: 실제 4가지 동시 진입·A08 지연 후 타임아웃·A06 정상 지적과 3가지 결과 보존·불완전 표시). 실제 API 정상 비교 12조건 완료. 실제 API 장애 주입·브라우저 실패 표시는 미실행 |
| TC-F15 | REQ-15 | 지적 검증·병합 | 존재하지 않는 대상·허위 인용·동일 지적을 넣는다. 잘못된 근거를 분리하고 중복·반복 지적을 식별한다. | unit/integration | 단위 통과 (2026-11-10, `test_review_merge.py`): 없는 대상·종류가 다른 대상·없는 근거 요구사항·원문에 없는 인용은 버리고(인용 글은 로그에 남기지 않음), 같은 지문은 근거를 모두 보존해 합치며 규칙 지적과 LLM 지적은 따로 둠. 반복 지적은 지문으로 식별해 major 이상이면 자동 루프를 멈춤 (`test_rework.py`). 통합은 TC-F16·F17의 API 회귀 경로에 포함 |
| TC-F16 | REQ-16 | 재작업 제어 | 명확한 대상이면 LLM 라우터 호출0회, 미매핑이면 허용 단계만 반환한다. 반복·상한에서 자동 루프가 중단된다. | unit/integration | 단위·DB 회귀 통과 (2026-11-10): 명확한 단계의 A09 미호출, 허용 단계 제한, 반복·상한의 HITL 전환 (`test_rework.py`, `test_a09_rework_router.py`, `test_design_rules_pipeline.py`, `test_normalization_pipeline.py`). 두 PDF 동시 생성 중 SQL critical도 A09 호출 0회 확인 |
| TC-F17 | REQ-17 | 최종 승인·보류 | 정상 설계를 승인·수정 요청·보류한다. 실패 SQL이 있는 경우 완료 승인 대신 수정/보류를 선택한다. | unit/integration | API·DB 통과 (2026-11-10): 두 PDF 동시 활성화·8종 후보 생성 → 보류·재개·승인, 수정 후 새 revision만 승인. 실제 SQL 실행 실패 → RULE-07 critical·승인 422·상태 불변, 수정 후 승인 성공 (`test_dual_pdf_pipeline.py`) |
| TC-F18 | REQ-18 | 문서 내보내기 | 한 실행에서 파일을 내려받아 ID·버전을 대조한다. PDF 한글·표·ERD가 잘리지 않고 초안은 승인본과 구분된다. | unit/integration | 단위·DB 일부 통과 (#13 PDF 엔진 `test_pdf_engine.py`: CI 리눅스 통과 — 열 분할·넓은 ERD 배율·외부 리소스 차단·글리프 누락. 한글 폰트·긴 표 머리글 반복·초안/승인본 표식·실제 mermaid-cli는 한글 폰트·mmdc가 있는 실행 이미지에서 통과(#226 `docker build --target check`, 130 passed·0 skipped), CI·Windows는 생략. #217 `test_pdf_pipeline.py`: 승인 전 PDF 비공개·승인 뒤 같은 바이트 공개, 격리 DB). 실제 LLM 실행 통과 (#19 E2E, 아래 TC-F19와 같은 실행): 승인본 8개(기능 명세 md·pdf, ERD mmd·pdf, DDL sql, RTM xlsx·csv, manifest json)를 내려받아 8개 모두 sha256 = 산출물 목록 해시, manifest json을 뺀 7개는 manifest 해시와도 일치(manifest는 자기 해시를 담지 않음), manifest·기능 명세서·ERD PDF 머리말의 run_id·revision·`model_hash`·팩 버전 일치, RTM에 REQ-01~07 전부. PDF는 Noto Sans CJK 한글, 표·CRUD 매트릭스·ERD 그림이 쪽 안에 들어가고 「승인본 · revision」 표식. 관찰: 개요 ERD에서 REL-01 글자가 REL-02와 겹쳐 가려짐(관계선은 있음, #261). #269에서 개요의 관계 이름을 뺐고, 후속으로 이름을 되살려 개요를 ELK로 배치함: 교차 개요 이름 겹침 0, 20테이블 개요 이름 25개·겹침 0·7.9pt를 실제 mermaid-cli 시험으로 확인(실행 이미지). 실제 LLM E2E는 다시 돌리지 않음. 초안 PDF 구분은 위 단위 시험만. 2026-11-10 고정 LLM 응답·두 PDF 동시 활성화·8종 전체 버전/해시/승인 근거/동일 바이트 다운로드 통합도 통과 (`test_dual_pdf_pipeline.py`). 신규 4테이블 픽스처의 PDF 육안 확인은 아래 #17 기록과 같음 |
| TC-F19 | REQ-19 | 웹 진행·결과 확인 | 업로드부터 승인·다운로드까지 시연한다. 새로고침·SSE 재연결 후 현재 상태를 복구하고 중복 재개를 막는다. | unit/integration | 기본 흐름 DB 통과 (#19 `test_scripted_flow.py`: 고정 규칙 LLM + 실제 노드로 업로드 → 추출 확인 → 분석 확인 → 최종 검토 승인 → 승인본 내려받기(ERD·DDL·RTM·기능 명세), 같은 확인 요청 두 번째 답 409, 상태 다시 조회, 수정 요청 → 새 revision 승인). 화면 표시는 웹 시험(mock). 실제 LLM E2E 통과 (#19, 2026-11-10, main `9c619e0`, `compose.deploy.yml` 로컬 기동 — 실행 이미지·PDF 켬·웹(Caddy) 경유 HTTP, Windows 11 Docker Desktop, `gpt-6.1-sol`·`gpt-6-luna`, 재고 팩 0.1.20, 입력 `재고_quick.xlsx` 6행): 업로드 → 추출 확인(확인 필요 4행: 중복 ID·ID 없음·세부내용 없음) → 분석 확인(요구사항 7개, 모호 지적 1개를 문장 수정) → 최종 검토(minor 1, critical 0) 승인 → 완료까지 80초, 산출물 8개 내려받기(TC-F10·F18). SSE: 이벤트 3개마다 끊고 `Last-Event-ID`로 10번 재연결 → 31개를 빠짐·중복 없이 받았고 처음부터 다시 받은 목록과 같음. 재기동(`down` → `up`) 뒤 실행 상태·ERD PDF 같은 바이트. 위 기록은 LLM까지 간 세 번째 실행이다(같은 날 같은 입력·팩·모델). ① 로컬 API(PDF 끔)에서 분석 확인 답 문장에 「차이」를 넣자 A03이 「차이수량」을 만들어 RULE-05 critical(팩 사전에 없는 낱말) → 설계대로 승인 차단. 이어 보낸 수정 요청은 오래된 로컬 개발 DB 볼륨에 격리 DB가 없어 SQL 검증 `error`로 실행 실패(환경 문제, 배포 compose 실행에서는 없음). ② 같은 로컬 API에서 답 문장을 위 기록과 같게 바꾸자 자동 재작업 1회 뒤 revision 1·지적 0으로 완료(PDF 없음). ③ 위 기록(revision 0·minor 1). ②와 ③은 입력·답이 같아도 재작업 횟수·지적이 달랐다. 브라우저 화면으로 한 시연은 미실행 |
| TC-F20 | REQ-20 | 실행 이력·재개 | HITL 대기에서 서버 재시작 후 조회·재개한다. 문서 해시·승인 revision·산출물 버전이 일치한다. | unit/integration | API·DB 통과 (2026-11-10): 분석 확인·최종 검토 대기에서 API·그래프·실행기 재생성 후 복원. 두 PDF 재렌더링 없이 승인하고 8종의 모델·문서·팩·정책 해시와 승인 revision·다운로드 바이트 일치 확인 (`test_dual_pdf_pipeline.py`). OS 프로세스 종료·재기동 자체는 미실행 |
| TC-F21 | REQ-27 | HWPX·HWP 입력·추출 확인 | 표형·서술형 HWPX와 HWP를 입력해 원문과 대조한다. 원문 기호(①·• 등)와 위치가 보존되고, 미지원 버전·손상·추출 실패는 오류/확인 상태로 전환되며 정상 분석으로 진행하지 않는다. | unit/integration | 단위·DB 일부 통과 (#24: 표형 상세표 읽기·원문 위치·손상 파일 안내(파서), 최소 HWPX를 실제 엔진과 parse 노드로 읽기·원문 기호(①·•·가.) 보존(`test_hangul_input.py`), .hwp 업로드 저장·OLE 서명 검사·기존 DB 형식 CHECK 확장(DB). 실제 RFP 파일을 화면부터 끝까지 넣는 시험·배포용 문서는 미실행(#253). 서술형은 구현 범위 밖) |
| TC-F22 | REQ-01, REQ-05 | 조건부 확인 (멈추지 않는 경로) | 모든 원문이 `pass`이고 분석 결과에 품질 경고·질문·분할(같은 원문에서 요구사항 2건 이상)이 없는 실행을 돌린다. 추출 확인(UI-02)과 분석 확인(UI-03)에서 멈추지 않고 `parsing → analysing → designing`으로 가며, 「분석 확인 생략」 상태 이벤트를 남긴다. `review`·`fail` 블록이나 품질 경고·질문·분할이 하나라도 있으면 멈춘다 (ADR-0015). | unit/integration | 단위·통합 통과 (#17) |

## 비기능 (TC-N)

| TC | 요구사항 | 대상 | 시나리오·기대 결과 | 층위 | 상태 |
|---|---|---|---|---|---|
| TC-N01 | REQ-21 | 추적 무결성 | 설계 요소별 누락·없는 REQ 참조를 주입한다. 모두 검출되고 최종 승인 상태로 넘어가지 않는다. | unit/integration | 단위·DB 통과 (#12). 단위: 기능·엔티티·속성·관계의 req_ids 누락·없는 REQ 참조·ID 중복을 모두 검출 (`test_contracts.py`). 정리 입력 추적 오류는 RULE-02(req_ids 없음)·RULE-01(없는 REQ·엔티티 참조) critical 지적이 되고 세부 유형을 유지 (`test_normalization_findings.py`). 정리에 실패한 실행은 그래프에서 직접 승인해도 내보내지 않음 (`test_normalization_routing.py`). DB: 정리 실패 지적이 재시작 뒤에도 승인을 막음 (`test_normalization_pipeline.py`, 물리명 실패 사례. 추적 오류 주입은 단위만) |
| TC-N02 | REQ-22 | 출력 형식·오류 통제 | 고정 응답으로 잘못된 타입·거절·반복 오류를 재현한다. 초기 호출+재요청 최대2회 후 명시 실패한다. | unit/integration | 단위 통과 (2026-11-10, `test_llm_client.py`): 잘못된 출력은 오류를 붙여 재요청하고, 기본 재요청 2회(`max_structured_retries`)를 다 쓰면 호출 3회 기록과 함께 `LLMContractError`, 거절은 재요청하지 않고 `LLMRefusalError`, 시간 초과·API 오류는 종류를 유지, 예산을 넘기면 다음 호출 전에 멈춤, 오류별 API 오류 코드 대응 |
| TC-N03 | REQ-23 | 문서·비밀 보호 | 다른 실행의 파일 접근·경로 조작·문서 내 지시·비허용 SQL을 입력한다. 접근/실행이 차단되고 비밀이 로그에 나오지 않는다. | unit/integration | 단위·통합 통과 (#21 점검: 다른 세션의 조회·목록·재개·취소·SSE·화면·다운로드 404, 저장 경로 이탈 차단, 확장자만 바꾼 파일 415, 문서는 `<data>` 블록으로만 전달, 비허용 SQL 거절(#169·#171), 로그 점검). 실제 LLM에 문서 내 지시를 넣는 시험은 미실행(`llm`) |
| TC-N04 | REQ-24 | 재현성·평가 기록 | 승인된 평가 집합으로 지표를 계산한다. 분모·미완료·실패·입력 버전이 보고서에 명시되고 정답이 생성 결과로 덮어써지지 않는다. | integration/eval | 평가 자료 준비·승인 완료 (#40, 2026-11-10): R1이 출처·해시 및 A05/A08 고정 설계·기대 결함 자료를 포함한 R3 전체 승인을 확인. 실제 1차 실행·A01 단계 진단·미완료 보고는 docs/07의 #20·#50 기록을 따르며 전체 시나리오 검증은 #20에서 계속 진행 |
| TC-N05 | REQ-25 | 자원·취소 | 한도 초과 파일·긴 LLM 호출·취소 요청을 재현한다. 명시 오류/취소 상태가 되고 취소 뒤 산출물이 완료본으로 승격되지 않는다. | unit/integration | 단위·통합 통과 (#21 점검: 크기·압축을 푼 크기 초과 413, LLM 타임아웃·재시도 설정, 노드 경계 취소·취소/lease 상실 뒤 늦은 산출물·검증 결과 미게시(#17)). 2026-11-10 두 PDF 포함 8종 후보를 만든 후 취소해도 초안 유지·PDF와 manifest 비공개 확인. 원문 블록 수 제한 단위·API 통과: 한도까지 진행, 초과 시 A01 호출 0회·부분 분석 없음·EXTRACTION_FAILED·상한/실제 건수 안내 (`test_parse_node.py`, `test_input_block_limit.py`) |
| TC-N06 | REQ-26 | 팩·공통 코드 분리 | 공통 코드를 바꾸지 않고 두 승인 팩을 실행한다. 사용 팩·공유 용어 버전을 기록하고 도메인 상수 하드코딩을 검토한다. | unit/integration | 단위·DB 일부 통과 (#12 모델 정리). 같은 정리 코드로 재고·설비 팩을 실행해 공통 `naming.yaml`의 이름 규칙과 팩별 사전을 읽고, 결과 모델에 팩 버전(`pack_version`)과 사전 내용 해시(`lexicon_digest`)를 기록 (`test_codegen_naming.py`·`test_normalize.py`). 실행에 기록된 팩 버전이 바뀌면 지적이 아닌 실행 오류 (`test_normalization_node.py`, DB `test_normalization_pipeline.py`). 하드코딩 검토: `codegen/normalize.py`·`naming.py`·`normalize_step.py`의 한글 문자열은 오류 문구뿐이고 도메인 용어 상수는 없음. 현재 공통 0.1.5·재고 0.1.21은 approved. 설비는 draft로 유지하며 이번 재고 통합·평가 범위에서는 제외. 두 승인 도메인 팩 실행은 미실행 |

## 에이전트 (TC-A)

| TC | 요구사항 | 대상 | 시나리오·기대 결과 | 층위 | 상태 |
|---|---|---|---|---|---|
| TC-A01 | REQ-04 | A01 요구사항 분석 | 복합 문장 분해, FR/NFR 판단, 불명확 조건 질문의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 정답 기준 라벨 비교; 원문 없는 조건 추가·분할 원문 누락 검출 | unit | 단위 통과 (#5) |
| TC-A02 | REQ-06 | A02 기능 설계 | 기능 분해/묶음; 미정 우선순위 질문; CRUD는 제외의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 존재하는 REQ만 참조; 우선순위로 기능 자동 삭제 금지 | unit | 단위 통과 (#6 `test_a02_functions.py` stub: 없는 REQ 참조 재시도·실패, 낮은·없는 우선순위로 기능 삭제 안 함, 계약 위반·근거 인용 오류 거절). 실제 모델 품질은 #49 뒤 |
| TC-A03 | REQ-07 | A03 엔티티·속성·CRUD | 저장 대상·타입/제약·CRUD 판단; 이력 삭제 면제 근거의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 기능/REQ 참조·타입 검증; FK는 관계에서 코드 파생 | unit | 단위 통과 (#7). #255: NFC·NFD로만 다른 엔티티·속성 이름, 기능·엔티티 쌍, 면제 모순을 같은 이름으로 보고 재요청(ID 충돌로 멈추지 않음), NFD `entity_name`도 NFC 엔티티 ID로 연결, PostgreSQL 상한(numeric precision 1000, char·varchar length 10485760) 통과·초과 재요청(메시지에 엔티티.속성), 팩 용어 상한 초과 거절 |
| TC-A04 | REQ-08 | A04 관계 설계 | 자기참조·N:M·필수/선택 판단의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 없는 엔티티 거절; 인용 실재; 관계 모델에서 FK 생성 가능 | unit | 단위 통과 (#8) |
| TC-A05 | REQ-14 | A05 관계 모순 검토 | 카디널리티·방향·필수 조건 모순 검토의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 정상 대안은 허용; 원문/targets 실재를 후속 코드 검증 | unit | 단위 통과 (#9) |
| TC-A06 | REQ-14 | A06 데이터 누락 검토 | 필요 데이터·기능 누락; 연결된 다른 테이블의 충족도 고려의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 실제 누락과 동등 대안을 구분; 전달 문맥 부족이면 불확실성 표시 | unit | 단위 통과 (#5) |
| TC-A07 | REQ-14 | A07 비기능 요구 검토 | 권한·감사·보존 반영 여부와 DB 밖 처리 경계의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 권한 컬럼 존재만으로 보안 충족 판정 금지 | unit | 단위 통과 (#6 `test_review_a07.py` stub: 권한 컬럼만으로 충족 판정 안 함, DB 밖 처리 구분, 근거 없는 지적 거절, 계약 위반 재시도). 실제 모델 품질은 #49 뒤 |
| TC-A08 | REQ-14 | A08 정규화 검토 | 반복/다중값·중복 설계·수정 이상 후보의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 업무 근거 있는 스냅샷·이력 중복을 무조건 오류로 보지 않음 | unit | 단위 통과 (#7) |
| TC-A09 | REQ-16 | A09 조건부 재작업 판단 | 요구사항/기능/데이터 모델 중 복귀 단계 판단의 정상 응답, 계약 오류, 근거 부족 사례를 실행한다. **기대:** 명확한 단계는 호출하지 않음; 불가/모호시 HITL | unit | 단위 통과 (#9) |

## #17 재고 통합 검증 (2026-11-10)

기준 코드는 main `cf8ee80`(#267), 공통 팩 `0.1.5`, 재고 팩 `0.1.21`이다. 실제 PostgreSQL·Mermaid CLI 11.17.2·WeasyPrint·한글 폰트 환경에서 ERD PDF와 기능 명세 PDF를 동시에 활성화했다. LLM 전송만 기존 고정 응답으로 대체하고, API·그래프·정리·생성·SQL 검증·저장·승인·다운로드는 실제 구현을 사용했다. 개발용·평가용 데이터셋 파일은 사용하지 않았다.

| 완료 조건 | 확인 결과·근거 | 대응 TC |
|---|---|---|
| 한 실행의 8종 산출물 연결 | DDL SQL, ERD Mermaid·PDF, 기능 명세 Markdown·PDF, RTM CSV·XLSX, manifest JSON. 동일 run·revision·모델 해시, 팩·공통 버전·정책 해시와 manifest의 7개 파일 해시 확인 | TC-F10·11·18 |
| 승인 근거와 다운로드 | 승인 전 초안 5종 표시, 두 PDF·manifest 비공개. 승인 후 8개 승인 근거와 파일 해시 일치, SQL 검증 근거 연결, 8종 다운로드가 생성 바이트와 일치 | TC-F17·18 |
| 대기·복원 | 분석 확인에서 API·그래프·실행기를 재생성해 복원·재개. 최종 검토에서도 보류·재생성 후 두 PDF 재렌더링 없이 승인 | TC-F05·20 |
| 수정·오래된 응답 | 새 revision만 승인하고 이전 revision 후보는 초안 유지. 이전 응답은 409이며 현재 상태 불변 | TC-F05·17·20 |
| 실패·승인 차단 | 실제 SQL 타입 결함의 실행 실패가 RULE-07 critical로 전달되고 승인 422·상태 불변. A09 호출 없이 사람 확인, 수정·재검증 후 승인 | TC-F11·16·17 |
| 취소·재작업·lease | 8종 후보 생성 후 취소 시 승격 없음. 기존 회귀로 노드 경계 취소·lease 경쟁·반복 지적·재작업 상한 확인 | TC-F16·N05 |

신규 `test_dual_pdf_pipeline.py` 4개 통과(스킵 0), 관련 실행기·API·설계 규칙·정리·lease·재작업 회귀 178개 통과(스킵 0). 신규 시험은 실제 PDF 환경이 필요하므로 `SPECTON_TEST_NATIVE_PDF=1`을 지정하며, 환경을 지정하지 않은 기본 실행에서는 생략한다.

```bash
SPECTON_TEST_NATIVE_PDF=1 python -m pytest -q -m db tests/integration/test_dual_pdf_pipeline.py
python -m pytest -q -m 'not llm' tests/integration/test_runner.py tests/integration/test_api_runs.py tests/integration/test_design_rules_pipeline.py tests/integration/test_normalization_pipeline.py tests/integration/test_lease_race.py tests/unit/test_rework.py tests/unit/test_a09_rework_router.py tests/unit/test_normalize_graph.py tests/unit/test_normalization_routing.py
```

실제 PDF 육안 확인은 4테이블·3기능 픽스처 범위다. 대규모 ERD 실측(#236)을 대체하지 않는다. API·실행기 재생성은 같은 시험 프로세스 안에서 수행했으며 OS 프로세스 강제 종료·배포 재기동 시험과 구분한다. 실제 LLM 평가(#20·#49), 브라우저 E2E(TC-F19), 실제 HWP·HWPX RFP 입력과 배포 문서(#253)는 별도 검증으로 남긴다.

## 최종 HITL 검토·승인 기록 제공 (2026-11-10 R1 확정)

검토 보고서 Markdown을 별도 생성하지 않고 최종 HITL에서 지적·설계·SQL 검증 상태를 확인해 승인한다. 승인 후에는 결과 작업공간의 검토 탭에서 같은 revision의 지적을 조회한다. 없는 보고서 다운로드 행은 숨기며 실제 과거 파일이 있으면 기존 다운로드는 보존한다.

- 웹 회귀 173개 통과: SQL 통과·실패·실행 오류·미검증·미생성 표시, 다른 revision/알 수 없는 검증 값을 통과로 보이지 않음, 빈 검토 파일 행 숨김·기존 파일 유지, 승인 전후 지적 조회 유지.
- 실제 API·DB 승인/조회 회귀 11개 통과: critical·최신 SQL 필수 검증의 승인 차단, 통과 SQL의 승인 근거 저장, 현재 SQL 검증 조회, SQL 검증을 선택적으로 끈 기존 설정 호환.
- mock API 모드의 실제 Chrome에서 업로드 → 최종 HITL의 SQL 검증 표시 → 사람 승인 → 검토 보고서 빈 다운로드 행 없음 → 완료 후 결과 작업공간 검토 탭의 지적 조회를 확인했다. 실제 LLM·실제 백엔드를 연결한 브라우저 E2E와 구분한다.
- 웹 lint·build·check:api, 문서·API 계약 검사 46개 통과. 새 계약 필드나 보고서 파일은 추가하지 않는다.

이 기록은 실제 LLM 품질이나 운영 환경의 브라우저 E2E 완료를 뜻하지 않는다.

## #17 인수 잔여: 원문 수 제한·RTM 보류 (2026-11-10)

- `max_source_blocks` 기본 1,000(환경 변수 `SPECTON_MAX_SOURCE_BLOCKS`). 파싱 후 실행 전체의 원문 블록을 합산하고 한도 초과면 A01 호출 전에 멈춘다. 원문 없는 review 블록도 세며 일부를 잘라 통과시키지 않는다. unit은 네 파서의 공통 후처리와 여러 문서 합산·경계·잘못된 설정을 확인한다. 실제 CSV API는 상한 초과 시 A01 0회·저장된 부분 분석 없음, 경계값이면 추출 확인 후 A01 1회를 확인한다.
- RTM의 네 행 상태는 유지한다. NFR 미연결과 HITL 대기 때문에 행을 보류로 바꾸지 않으며 CSV·Excel 바이트가 실행 대기 상태만으로 달라지지 않는 것을 `test_nfr_and_final_review_wait_do_not_create_a_deferred_rtm_row`로 확인한다. 행별 보류 계약은 이번 필수 범위에 추가하지 않는다.
- 전체 기본 회귀: 1,859 passed·6 skipped·DB 330개 별도. 실제 API/실행기·기본 흐름·오류 상세 관련 DB 회귀 39개 통과(스킵 0). 실제 LLM·평가 자료는 사용하지 않았다.
- 린트·포맷·타입 검사 및 배포 compose의 사용자 지정 상한 전달 확인. compose 검증은 설정 해석만 수행하며 배포·컨테이너 기동은 하지 않았다.

### #290 계약·정리 보완 검증 (#292)

- TC-A03: 복합 unique_keys 속성 이름→ID 변환, 없는 속성·중복 묶음 거절.
- TC-A04·TC-F09: 명시적 fk_bindings만 재사용하고 미선언 D13·잘못된 PK/타입/NULL은 차단. 식별 관계의 PK 중복 방지, 원래 속성 출처·FK 쌍 보존.
- PostgreSQL 18·API: 같은 부모 아래 업무 조합 중복 거절, 다른 부모 아래 같은 구성 값 허용, 없는 부모 참조 거절, 두 revision 보존·승인·ERD 다운로드. DB/API·실제 두 PDF/8종 통합 17개 통과.
- 새 필드 없는 설계의 기존 해시 유지와 선언 추가 시 해시 변경 검증. 전체 기본 1,926개 통과·6개 스킵. 실제 LLM 평가 결과가 아니다.
