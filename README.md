# Specton

고객 요구사항 문서를 읽어 **기능 명세서·ERD·DDL·RTM** 초안을 만들고, 누락·모순을 검토하는 LangGraph 기반 에이전트 서비스.
팀 설계로 · 한화시스템 K-뉴딜 아카데미 캡스톤 과제 8.

개발 문서는 [docs/](docs/README.md)에 있다. 기획·회의 원본은 상위 기획 폴더의 `docs/`(기획서, `개발착수_문서/`, `회의준비/`)에 있다.

## 기술 구성

| 영역 | 사용 |
|---|---|
| 언어·패키지 | Python 3.12, uv |
| LLM·워크플로 | OpenAI API, LangGraph |
| 계약·검증 | Pydantic, pglast |
| API | FastAPI |
| DB | PostgreSQL 18 (Docker) |
| 웹 | React (`frontend/`) |
| 품질 | ruff, mypy, pytest |

미정: PDF·HWPX 엔진(ADR-0004), 화면 라이브러리(ADR-0005), AWS 구성(ADR-0013).

## 시작하기

```bash
cp .env.example .env              # 키는 개인 환경에서만 입력
uv sync                           # 의존성 설치 (.venv)
docker compose up -d db           # PostgreSQL 18 (app + sandbox)
uv run uvicorn specton.api.main:app --reload
curl localhost:8000/health
```

웹(`frontend/`):

```bash
cd frontend && npm install && npm run dev
```

## 품질 검사

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                     # 단위 테스트 (db·llm 제외)
uv run pytest -m db               # 격리 DB 필요
uv run pytest -m llm              # 실제 LLM 호출, 예산 승인 후 수동 실행
```

## 도메인 팩

`domain_packs/`는 공공데이터 공통표준 8차 기반 입력이다. 사람이 쓰는 파일과 생성 파일이 나뉘어 있다([안내](domain_packs/README.md)).

```bash
uv run python -m specton.packs.build          # 입력 수정 후 재생성
uv run python -m specton.packs.build --check  # 생성 파일 최신 여부 (CI)
```

## 폴더 구조

```text
specton/
  contracts/    단계 간 데이터 계약 (상태·LLM 입출력·Finding)
  ingest/       Excel·CSV·PDF·HWPX 추출, 원문 위치 보존
  packs/        도메인 팩 로더
  llm/          공통 LLM client·재요청·프롬프트 버전
  nodes/        에이전트 노드 A01~A09
  codegen/      ID·명명·N:M·FK, Mermaid·DDL·RTM 생성
  review/       규칙 검사·설정형 리뷰어·근거 병합
  validate/     DDL 파싱·격리 DB 실행 검사
  persistence/  플랫폼 저장·checkpointer
  export/       중간 Markdown, 최종 PDF·SQL·Excel/CSV
  api/          FastAPI
  config.py     환경 설정
domain_packs/   common · inventory(재고·자재) · maintenance(설비)
eval/           평가 데이터·정답 (origin: synthetic 표시)
frontend/       React 웹
tests/          unit · integration · e2e
```

## 협업 규칙

자세한 내용은 [CONTRIBUTING.md](CONTRIBUTING.md).

- 작업은 GitHub Issues로 관리한다. 브랜치 `feat/<이슈번호>-요약`, 커밋 `feat: 내용 (#이슈번호)`
- PR은 `Closes #이슈번호`와 테스트 결과를 적고 작성자 외 1명이 검토한다. 계약(`contracts/`) 변경은 2인 승인.
- 노드는 얇은 어댑터로 두고, 생성기·검증기는 LLM client를 import하지 않는다. 도메인 상수는 팩에서 읽는다.
- 고객 문서·API 키·실행 산출물은 커밋하지 않는다.

## 라이선스

[MIT](LICENSE). `domain_packs/sources/`의 공공데이터 공통표준 CSV는 행정안전부 공개 데이터(이용허락범위 제한 없음)로, 출처는 `domain_packs/sources/sources.yaml`에 적는다.
