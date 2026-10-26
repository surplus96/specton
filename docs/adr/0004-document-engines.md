# ADR-0004: 문서 엔진

- 날짜: 2026-10-23
- 상태: 제안
- 결정자: 팀 설계로 (회의에서 승인·수정·보류)

## 배경

PDF 입력·추출, 최종 PDF 출력, HWPX/HWP 추출에 쓸 라이브러리가 정해지지 않았다. 후보는 설치·실측 없이 공개 자료로만 비교했다.

## 결정

- PDF 추출: Docling(표 구조 인식·OCR 내장). 텍스트형이 느리면 pdfplumber로 보조.
- PDF 출력: WeasyPrint(HTML/CSS → PDF) + `mermaid-cli`로 ERD를 SVG 렌더링해 삽입. ERD가 깨지면 Playwright 인쇄로 전환.
- HWPX: `python-hwpx`(Apache-2.0). HWP 5.0: `hwp-hwpx-parser`와 `hwpkit`를 표 추출로 비교, 시간이 없으면 "HWPX로 변환해 업로드" 안내.
- 스캔 PDF OCR 포함 여부는 회의에서 정한다.
- 채택 전 대표 문서 2~3건으로 1시간 실측한다.

## 검토한 대안

| 대안 | 장점 | 단점 | 기각 이유 |
|---|---|---|---|
| PyMuPDF 단독 | 매우 빠름 | 복잡한 표·병합 셀에 약함 | 요구사항 정의서는 표가 많음 |
| Playwright 인쇄 단독 | 화면과 같은 렌더링 | 이미지 용량 큼, 브라우저 의존 | WeasyPrint 실패 시 대체로 유지 |

## 검토 근거

조사일 2026-10-23. 패키지 설명·공개 비교 자료 기준이며 설치·실측은 하지 않았다.

**HWPX·HWP 추출**

| 후보 | 지원 | 라이선스 | 메모 |
|---|---|---|---|
| python-hwpx | HWPX | Apache-2.0 | 활발히 유지. HWP 5.0 바이너리 미지원 |
| hwpkit | HWP·HWPX | MIT | 순수 Python, 텍스트 추출 중심. 신생 |
| hwp-hwpx-parser | HWP·HWPX | Apache-2.0 (README) | 텍스트·표 추출. 저장소 LICENSE 재확인 필요 |
| jakal-hwpx | HWP·HWPX | MIT | Python 3.11+, 매우 신생, 표 추출 미확인 |
| pyhwpxlib | HWPX 생성·편집 | 상업 유료(BSL 혼합) | 추출용이 아니라 제외 |

**PDF 추출**

| 후보 | 장점 | 단점 |
|---|---|---|
| Docling | AI 표 구조 인식, OCR 내장(스캔본 대응) | 느리고 모델 다운로드 필요 |
| pdfplumber | 문자 좌표 기반이라 표가 정확 | 느림, OCR 없음 |
| PyMuPDF | 매우 빠름 | 복잡한 표·병합 셀에 약함 |

한글 PDF 벤치마크 자료가 없어 대표 PDF로 실측한 뒤 확정한다.

**PDF 출력**

| 후보 | 메모 |
|---|---|
| WeasyPrint | HTML/CSS → PDF. 한글 폰트 설치 필요. Mermaid는 SVG로 먼저 렌더링 |
| Playwright(Chromium) 인쇄 | 화면과 같은 렌더링, Mermaid 직접 렌더. 결과 용량이 큼 |

출처:
- HWP: [python-hwpx](https://github.com/airmang/python-hwpx) · [hwpkit](https://github.com/psychofict/hwpkit) · [hwp-hwpx-parser](https://libraries.io/pypi/hwp-hwpx-parser) · [jakal-hwpx](https://pypi.org/project/jakal-hwpx/1.0/) · [pyhwpxlib](https://pypi.org/project/pyhwpxlib/0.18.0/)
- PDF: [PyTorch KR 레이아웃 벤치마크](https://discuss.pytorch.kr/t/llm-1-gpu-pdf-10/9808) · [docling vs pdfplumber](https://www.file2markdown.ai/blog/docling-vs-pdfplumber) · [pdfplumber vs pymupdf](https://www.file2markdown.ai/blog/pdfplumber-vs-pymupdf) · [Docling 지원 형식](https://docling-project.github.io/docling/usage/supported_formats/) · [WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)

## 결과

- 좋아지는 점: 표가 많은 문서에 강하고 한글 PDF 출력 경로가 단순하다.
- 감수할 점: Docling 모델 다운로드·한글 폰트를 컨테이너 이미지에 포함해야 한다.
- 관련 문서: [10 문서 입출력](../10-io-and-packs.md), [11 배포](../11-deployment-security.md)
