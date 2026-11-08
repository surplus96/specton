# ADR-0004: 문서 엔진

- 날짜: 2026-10-23 (PDF 출력 승인 2026-11-08, HWP·HWPX 엔진 채택 2026-11-08)
- 상태: PDF 출력 승인, HWP 5.0·HWPX 읽기·위치 추출 엔진 채택(2026-11-08), PDF 추출·OCR 제안
- 결정자: 팀 설계로 (PDF 출력은 #13 실측과 PR 리뷰에서 R1 승인, 추출은 회의에서 결정). HWP·HWPX 엔진은 #188 댓글(2026-11-08 15:27 KST, R1)에 「HWP 5.0·HWPX의 읽기·위치 추출 엔진으로 `rhwp-python==0.8.1`을 채택하겠습니다」로 적힘

## 배경

초기 제안(2026-10-23)에서는 PDF 입력·추출, 최종 PDF 출력, HWPX/HWP 추출 후보를 공개 자료로 비교했다. PDF 출력은 아래 R5 실측과 R1 결정을 바탕으로 승인하고, HWP·HWPX 엔진은 아래 「HWP·HWPX 채택」에서 채택하며, PDF 추출 엔진은 제안 상태로 남긴다.

## 결정

- PDF 추출: Docling(표 구조 인식·OCR 내장). 텍스트형이 느리면 pdfplumber로 보조.
- PDF 출력 (승인, #13 실측 2026-11-05·11-08): 공용 엔진 하나로 기능 명세서(Markdown, #14)와 ERD(Mermaid, #13)를 PDF로 바꾼다.
  - 엔진: WeasyPrint(HTML/CSS → PDF) + `mermaid-cli`로 ERD를 SVG로 그려 넣는다. Mermaid는 웹과 같은 11.15.0으로 고정한다(#13, #190). ERD가 깨지면 Playwright 인쇄로 전환한다.
  - 한글 폰트: Noto Sans CJK KR(`fonts-noto-cjk`)을 실행 이미지에 넣고 PDF에 내장한다.
  - 렌더러는 외부 경로·URL 리소스를 가져오지 않는다. 엔진이 만든 SVG·스타일만 쓴다 (docs/10).
  - Mermaid 설정 보안 (#190 R1 리뷰): 설정은 개발자가 정한 값만 넘기고, `secure` 목록에 `themeCSS`·`fontFamily`·`altFontFamily`·`themeVariables` 등을 넣어 원문 지시문으로 바꾸지 못하게 한다. 이름 안 지시문이 렌더 설정으로 실행되지 않도록 처리하고, ERD 외 다이어그램과 임의 원문은 그리지 않는다. 설정 변경 차단·지시문 처리·외부 리소스 차단은 PDF 엔진 PR에서 구현하고 회귀 시험한다.
  - ERD 구성: 전체 관계 개요(속성 없음) + 업무 영역별 상세도 + 테이블 정의서(전체 속성). 상세도에는 키 속성(PK·FK·UK)만 그리고 `direction LR`로 배치한다. 상세도 글자가 인쇄 용지에서 6pt보다 작으면 그 영역을 더 나누도록 경고한다. 다른 영역의 참조 상자를 포함한 상자 약 13개는 실측 참고값이며, 실제 인쇄 글자 크기로 판단한다.
  - 쪽: 용지 크기는 297×210mm. 표지·긴 표는 세로, ERD·넓은 표는 가로. 긴 표는 쪽마다 머리글을 반복한다.
  - 넓은 표(예: CRUD): 기능 ID 1열 + 엔티티 20열까지 가로 한 장에 둔다. 넘으면 엔티티 열을 20개씩 나누고 각 표에 기능 ID를 반복한다. 글자를 줄여 맞추지 않는다.
  - 초안: 시험·내부 렌더링 검증용 초안 PDF에는 쪽마다 「초안 · 승인 전 · revision N」과 배경 표식을 넣는다. 최종 PDF는 승인한 revision에서만 만들고, 공개 PDF 다운로드도 승인본만 허용한다 (docs/06).
  - 구현 순서·분담: 이 결정 PR(#197) 병합 → R5 의존성 단독 PR → R5 공용 PDF 엔진·키 표시 옵션·영역별 출력·표 분할·보안 및 재현 시험 → R1 #17의 생성 호출·저장·산출물 인계·다운로드/내보내기 연결과 통합 검증.
- HWP 5.0·HWPX 읽기·위치 추출: `rhwp-python==0.8.1`(MIT)로 채택한다(2026-11-08). .hwp를 HWPX로 바꾸지 않고 바로 읽고, 문단마다 구역·문단 번호, 표 칸마다 행·열·병합 범위를 준다. 같은 문서의 .hwp와 .hwpx에서 구역·문단 번호가 같았다(공공 과업지시서 1건에서 확인).
  - 쪽 번호는 렌더링으로 계산한 값이라 긴 문서에서 한글 프로그램과 달라진다. 원문 위치는 구역·문단·표·셀로 적고, 렌더링 쪽 번호를 원문 쪽 번호로 쓰지 않는다. 사람용 위치 표기에는 원문 고유번호와 표 위치를 쓴다.
  - 처음 제안한 `python-hwpx`(HWPX만)와 `hwp-hwpx-parser`·`hwpkit`(HWP 5.0 표 비교)는 이번 채택 대상이 아니다. 이유는 「HWP·HWPX 채택」.
- 스캔 PDF OCR 포함 여부는 회의에서 정한다.
- 채택 전 대표 문서 2~3건으로 1시간 실측한다.

## 검토한 대안

| 대안 | 장점 | 단점 | 기각 이유 |
|---|---|---|---|
| PyMuPDF 단독 | 매우 빠름 | 복잡한 표·병합 셀에 약함 | 요구사항 정의서는 표가 많음 |
| Playwright 인쇄 단독 | 화면과 같은 렌더링 | 이미지 용량 큼, 브라우저 의존 | WeasyPrint 실패 시 대체로 유지 |

## 검토 근거

초기 조사일은 2026-10-23이며 패키지 설명·공개 비교 자료를 기준으로 했다. 이후 확인한 내용은 아래 항목별 실측에 구분해 적는다.

**HWPX·HWP 추출**

| 후보 | 지원 | 라이선스 | 메모 |
|---|---|---|---|
| python-hwpx | HWPX | Apache-2.0 | 활발히 유지. HWP 5.0 바이너리 미지원 |
| hwpkit | HWP·HWPX | MIT | 순수 Python, 텍스트 추출 중심. 신생 |
| hwp-hwpx-parser | HWP·HWPX | Apache-2.0 (README) | 텍스트·표 추출. 저장소 LICENSE 재확인 필요 |
| jakal-hwpx | HWP·HWPX | MIT | Python 3.11+, 매우 신생, 표 추출 미확인 |
| pyhwpxlib | HWPX 생성·편집 | 상업 유료(BSL 혼합) | 추출용이 아니라 제외 |
| rhwp-python | HWP·HWPX | MIT | 매우 신생: PyPI 0.8.1 `Development Status :: 3 - Alpha`, GitHub 스타 16개(2026-11-01 확인). Rust 엔진 rhwp의 파이썬 바인딩, Java 불필요. 문단 `section_idx`·`para_idx`, 표 칸 `row`·`col`·`row_span`·`col_span`. 쪽 수는 렌더링 계산. 2026-11-08 재조회: GitHub 스타 16·포크 6·마지막 푸시 2026-09-24·릴리스 13개, PyPI 배포 12개(0.8.1 Alpha). 엔진 rhwp는 GitHub 스타 4,081·최신 v0.8.7 |

**PDF 추출**

| 후보 | 장점 | 단점 |
|---|---|---|
| Docling | AI 표 구조 인식, OCR 내장(스캔본 대응) | 느리고 모델 다운로드 필요 |
| pdfplumber | 문자 좌표 기반이라 표가 정확 | 느림, OCR 없음 |
| PyMuPDF | 매우 빠름 | 복잡한 표·병합 셀에 약함 |

한글 PDF 벤치마크 자료가 없어 대표 PDF로 실측한 뒤 확정한다.

**HWP 실측 (2026-11-01, rhwp-python 0.8.1)**

| 문서 | 확인한 것 | 결과 |
|---|---|---|
| 공공 과업지시서 1건(.hwp·.hwpx) | 요구사항 표 위치 | 목록표·상세표 문단 번호가 .hwp·.hwpx 모두 347·359로 같음. 쪽 수는 .hwp 48 / .hwpx 53 |
| 요구사항 명세서 1건(8쪽) | 같은 이름 PDF와 쪽별 글자 대조 | 8쪽 모두 같음 |
| 공공 제안요청서 2건(한글 2018로 만든 PDF) | 쪽별 글자 대조 | 각각 44쪽·16쪽까지 같고, 그 뒤 1쪽씩 밀림 |

- 표 추출 비교: `hwp-hwpx-parser`는 표 내용만 주고 위치(문단·쪽)는 주지 않는다. `hwpkit`은 표 안 문단까지 한 줄로 이어 세어 같은 상세표가 567번이 된다.

**PDF 출력**

| 후보 | 메모 |
|---|---|
| WeasyPrint | HTML/CSS → PDF. 한글 폰트 설치 필요. Mermaid는 SVG로 먼저 렌더링 |
| Playwright(Chromium) 인쇄 | 화면과 같은 렌더링, Mermaid 직접 렌더. 결과 용량이 큼 |

**PDF 출력 실측 (2026-11-08, R5, #13)**

아래 수치는 R5의 실측 보고다. 동일 조건을 재현하는 스크립트·테스트는 후속 PDF 엔진 PR에 포함한다.

환경: Docker의 WeasyPrint 70.0(Python 3.12-slim, Pango, `fonts-noto-cjk`)과 `minlag/mermaid-cli:11.15.0`(안의 mermaid도 11.15.0). ERD 원문은 main의 실제 코드(`normalize_design` → `render_erd`·`render_area_erd`, #177·#182)로 만들었다. 시험 모델은 재고 팩 용어로 만든 설계를 실제 정리 코드에 통과시킨 테이블 20 · 컬럼 86 · FK 25 · 관계 24(N:M 1)이고, 영역은 기준정보 7 · 수불 7 · 재고 이력 6이다. 2026-11-05에 샘플 모델로 한 사전 실측(한글 폰트, 긴 표, 초안 표시 통과, #13 댓글)을 실제 코드 출력으로 다시 확인했다.

| 항목 | 결과 |
|---|---|
| 한글 | Noto Sans CJK KR 일반·굵게 서브셋 내장, 글자 추출 정상 |
| ERD SVG | 15개 모두 오류 없음. 다른 영역 상자 `창고 (→ 기준정보)` 정상 |
| 긴 표 | 258행 테이블 정의서가 8쪽으로 넘어가며 모든 쪽에 머리글 반복 |
| 쪽 방향 | 세로(표지·긴 표)와 가로(ERD·CRUD 표)가 한 PDF 안에서 섞임 |
| 초안 표시 | 초안 PDF는 21쪽 모두 머리 표식과 배경 「초안」, 승인본 PDF에는 없음 |
| 시간·크기 | 21쪽: HTML 배치 2.4초 + PDF 쓰기 1.7초, 약 470KB. Mermaid SVG는 그림당 약 1.5초(컨테이너 시작 포함) |

ERD 글자 크기 (297×210mm 가로 용지, 여백 12mm, 제목 자리 14mm, 원래 크기보다 키우지 않음, Mermaid 기본 글자 16px 기준. B안은 위아래·좌우 배치 중 큰 값):

| 그림 | 상자 수 | 지금 표기(A안, 전체 속성) | B안(한글만) | 키 속성만 + `direction LR` |
|---|---|---|---|---|
| 전체 관계 개요(속성 없음) | 20 | 7.0pt | — | — |
| 나누지 않은 전체 상세 | 20 | 3.1pt | — | 3.9pt |
| 영역 상세 · 기준정보 | 15 (자기 7 + 다른 영역 8) | 3.4pt | 3.7pt | 3.6pt |
| 영역 상세 · 수불 | 13 (7 + 6) | 5.0pt | 5.2pt | 6.8pt |
| 영역 상세 · 재고 이력 | 10 (6 + 4) | 5.7pt | 6.2pt | 7.4pt |

- B안(물리명 빼기)은 폭만 줄고 높이(속성 줄 수)는 그대로라 효과가 작다(+0.2~0.5pt).
- 키 속성만 그리면 높이가 줄어 상자 13개 이하 영역은 6pt를 넘는다. 나머지 속성은 같은 PDF의 테이블 정의서에 있다.
- 다른 영역과 많이 이어진 영역(상자 15개)은 어떤 표기로도 3~4pt라 영역을 더 나눠야 한다.
- 개요(속성 없음)는 테이블 12개 9.3pt · 20개 5.6pt · 30개 4.0pt · 45개 2.7pt · 60개 2.1pt (크기 시험 모델).

넓은 표 (297×210mm 가로 용지, 7.5pt, 기능 15행): 열 21개(기능 ID 1 + 엔티티 20)는 한 쪽에 들어가고, 열 41개는 넘치지는 않지만 머리글이 한 글자씩 꺾여 읽기 어렵다. 엔티티 열을 20개씩 나누고 기능 ID를 반복하면 2쪽으로 읽을 수 있다.

출처:
- HWP: [python-hwpx](https://github.com/airmang/python-hwpx) · [hwpkit](https://github.com/psychofict/hwpkit) · [hwp-hwpx-parser](https://libraries.io/pypi/hwp-hwpx-parser) · [jakal-hwpx](https://pypi.org/project/jakal-hwpx/1.0/) · [pyhwpxlib](https://pypi.org/project/pyhwpxlib/0.18.0/) · [rhwp-python](https://github.com/DanMeon/rhwp-python) · [rhwp](https://github.com/edwardkim/rhwp)
- PDF: [PyTorch KR 레이아웃 벤치마크](https://discuss.pytorch.kr/t/llm-1-gpu-pdf-10/9808) · [docling vs pdfplumber](https://www.file2markdown.ai/blog/docling-vs-pdfplumber) · [pdfplumber vs pymupdf](https://www.file2markdown.ai/blog/pdfplumber-vs-pymupdf) · [Docling 지원 형식](https://docling-project.github.io/docling/usage/supported_formats/) · [WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)

## HWP·HWPX 채택 (2026-11-08)

- 결정: HWP 5.0·HWPX의 읽기·위치 추출 엔진으로 `rhwp-python==0.8.1`을 쓴다. 의존성은 #188, 파서는 #24에서 연결한다.
- 근거:
  - 한 엔진으로 .hwp와 .hwpx를 모두 읽고, 원문 위치(구역·문단·표·칸 행·열·병합 범위)를 준다. 위치 추출까지 실측한 후보는 rhwp-python뿐이다. `hwp-hwpx-parser`는 위치를 주지 않았고, `hwpkit`은 표 안 문단까지 이어 세어 문단 번호가 달라졌다(위 「HWP 실측」). `python-hwpx`는 HWP 5.0을 읽지 못하고 위치 제공은 실측하지 않았다.
  - 요구사항 상세표 양식의 공공 RFP 3건에서 요구사항 건수가 원문과 같았고(141·41·64건), 글자는 원문 XML(1건, 전수)과 다른 엔진(pyhwp)으로 변환한 사본(2건, 포함 대조라 줄 순서·중복은 보증하지 않음)으로 대조해 일치했다. 고유 .hwp 152개 중 151개가 열렸고(못 연 1개는 PDF를 이름만 .hwp로 바꾼 파일), 열린 151개는 HWPX로 내보낸 뒤 읽은 표와 같았다.
- 위험과 대응: PyPI `Development Status :: 3 - Alpha`인 신생 바인딩이다(성숙도는 위 「HWPX·HWP 추출」 표). 버전을 0.8.1로 고정하고, 엔진 호출은 `specton/ingest/hangul_engine.py` 한 곳에만 두며, 엔진 블록 클래스 이름·필드가 바뀌면 CI 시험이 실패하게 했다.
- 범위 밖: 서술형(표가 아닌 문단) 요구사항과 상세표가 아닌 양식은 읽지 않는다. 상세표가 하나도 없는 파일과 암호 걸린 .hwpx는 안내로 멈추지만(.hwp 암호는 시험하지 않았다), 상세표와 서술형이 섞인 파일의 서술형 부분은 안내 없이 빠질 수 있다. 배포용 문서와 HWP 5.0 이전 버전은 시험하지 않았다.
- PDF 추출·스캔 OCR은 위 결정대로 제안 상태이고, PDF 출력은 위 「PDF 출력」 결정대로 승인 상태다.

## 결과

- 좋아지는 점: 표가 많은 문서에 강하고 한글 PDF 출력 경로가 단순하다.
- 감수할 점: Docling 모델 다운로드·한글 폰트를 컨테이너 이미지에 포함해야 한다.
- 감수할 점 (PDF 출력): `mermaid-cli`는 Chromium을 포함해 이미지가 크다(실측 이미지 2.28GB, WeasyPrint 쪽 542MB). 배포 이미지(ADR-0013, #25) 크기에 반영한다. WeasyPrint는 Windows에서 GTK가 따로 필요해, PDF 시험은 Docker·CI(리눅스)에서 돌리고 Windows 로컬에서는 건너뛴다.
- 감수할 점 (Mermaid 11.15.0): `npm audit`에 mermaid 보통 2건(설정 API 프로토타입 오염, CSS 주입)이 있고 11.17.2에서 고쳐졌다. 팀 결정(#13)대로 고정을 유지하되, `securityLevel: 'strict'`와 「서버가 만든 원문」만으로는 막히지 않는다(#190 R1 실험: 별칭 따옴표 안의 `init` 지시문 `themeCSS`가 strict에서도 인식됨). 그래서 위 「Mermaid 설정 보안」을 웹과 PDF 모두에 적용한다. 올릴 때는 웹과 mermaid-cli를 함께 올리고 한글 ERD를 다시 실측한다.
- 관련 문서: [10 문서 입출력](../10-io-and-packs.md), [11 배포](../11-deployment-security.md)
