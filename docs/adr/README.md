# 결정 기록 (ADR)

회의에서 승인된 결정만 기록한다. 초안은 상위 기획 폴더 `docs/회의준비/04_ADR_초안.md`에 있다.

| ADR | 제목 | 상태 | 날짜 |
|---|---|---|---|

새 결정은 [template.md](template.md)를 복사해 `NNNN-제목.md`로 만든다. 바뀐 결정은 새 번호로 기록하고 이전 ADR에 "대체됨: ADR-NNNN"을 적는다.

## 결정 대기 목록

개발 문서의 `제안 (ADR-xxxx)`·`미정 (ADR-xxxx)`은 아래 번호를 가리킨다. 승인되면 위 표로 옮기고 해당 문서를 갱신한다.

| ADR | 안건 | 열린 결정 | 제안 | 영향 문서 |
|---|---|---|---|---|
| 0001 | 역할 배정 | O-07 | 회의에서 즉시 배정, 통합은 경험자, 역할마다 백업, 평가 정답·AWS 배포 담당 명시 | 08 |
| 0002 | MVP 범위 | — | HWPX·HWP stretch, PDF는 최종 산출물만(확정), 웹 화면 3개, 한도는 타임아웃만 | 01, 02, 09 |
| 0003 | 입력 양식 | D-004 | 기준 5열 + 선택 "관련 요구사항", 7칸·11칸은 매핑 YAML | 10 |
| 0004 | 문서 엔진 | O-02, O-12 | PDF 추출 Docling(보조 pdfplumber), PDF 출력 WeasyPrint + mermaid-cli, HWPX python-hwpx | 10 |
| 0005 | 화면 라이브러리 | O-01 | Ant Design + mermaid JS | 09 |
| 0006 | 우선순위 미정값 | O-04 | `priority: null` + `priority_source`(explicit/inferred/unspecified), HITL에서 확정 | 04, 05 |
| 0007 | LLM 사용 조건 | — | 합성 데이터만, 역할별 모델 2단계, 예산 상한 숫자 확정, 동시 실행 수 제한 | 04, 11 |
| 0008 | 리뷰어 구성 | — | 설정형 리뷰어 노드 1종, `parallel`/`combined`는 평가로 결정 | 04, 07 |
| 0009 | 계약·API·팩 형식 | O-03 | 착수 문서 05·06 + OpenAPI 초안으로 동결, 팩 `strict`·Pydantic 고정, 평가 자료 `eval/` | 05, 06, 10 |
| 0010 | 검토 심각도 | O-05 | 규칙 위반 critical, LLM major/minor, 자동 재작업은 critical·major | 04 |
| 0011 | 인증·보존 | O-08 | 로컬 단일 세션, 업로드 파일은 시연 후 삭제 | 05, 06, 11 |
| 0012 | 실행기 | O-09 | API 프로세스 안 백그라운드 작업 + LangGraph Postgres 체크포인터 | 03 |
| 0013 | AWS 배포 | O-10 | EC2 또는 Lightsail 1대 + Docker Compose, IP 제한, 예산 알림 | 11 |
| 0014 | 평가 목표 | O-06 | 재고 5건·설비 3건, 개발용/평가용 세트 분리, 정답 작성자 ≠ 팩 작성자 | 07 |

후속 확장 안건 O-11(오픈소스 연동 대상)은 MVP 범위 밖이라 번호를 두지 않는다.
