# Specton

## 명령

- 설치: `uv sync`
- DB: `docker compose up -d db`
- API: `uv run uvicorn specton.api.main:app --reload`
- 테스트: `uv run pytest` (기본은 db·llm 마커 제외)
- 린트·타입: `uv run ruff check . && uv run mypy`
- 팩 재생성: `uv run python -m specton.packs.build` (`--check`로 검사)
- 웹: `cd frontend && npm run dev`

## 규칙

- LLM은 판단만 한다. ID 부여·SQL·Mermaid 생성·RTM 조인은 코드가 한다.
- 생성기·검증기(`codegen/`, `validate/`)는 LLM client를 import하지 않는다.
- 도메인 용어·상수는 `domain_packs/`에서 읽고 코드에 하드코딩하지 않는다.
- `GENERATED` 표시가 있는 팩 파일은 직접 고치지 않는다. `term_specs.yaml` 등 입력을 고치고 `uv run python -m specton.packs.build`를 실행한다.
- 실제 LLM 호출 테스트는 `@pytest.mark.llm`, DB 테스트는 `@pytest.mark.db`를 붙인다.
- 설계 근거는 상위 `docs/`의 착수 문서와 ADR을 따른다.
