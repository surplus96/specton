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

## 결과

- 좋아지는 점: 표가 많은 문서에 강하고 한글 PDF 출력 경로가 단순하다.
- 감수할 점: Docling 모델 다운로드·한글 폰트를 컨테이너 이미지에 포함해야 한다.
- 관련 문서: [10 문서 입출력](../10-io-and-packs.md), [11 배포](../11-deployment-security.md)
