# 협업 규칙

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-1f6feb)](CONTRIBUTING.md) [![English](https://img.shields.io/badge/lang-English-lightgrey)](CONTRIBUTING.en.md)

작업은 **GitHub Issues + Projects**로 관리하고, 코드는 **GitHub Flow**(보호된 `main` + 짧은 작업 브랜치)로 합친다.

## 작업 흐름

1. 이슈를 만들거나 배정받는다 (템플릿: Task / Bug). 마일스톤 M1~M5와 `role:`·`agent:` 라벨을 붙인다.
2. 최신 `main`에서 브랜치를 만든다.
   ```bash
   git switch main && git pull
   git switch -c feat/12-a01-requirement-node
   ```
3. 작게 커밋하고, 매일 오전 `main`을 반영한다 (`git fetch && git rebase origin/main`).
4. PR을 올린다. 본문에 `Closes #이슈번호`를 적는다. 병합은 **Squash**만 쓴다.
5. 브랜치는 **2일 안에** 병합한다. 길어지면 이슈를 쪼갠다.

## 이름 규칙

| 대상 | 형식 | 예시 |
|---|---|---|
| 브랜치 | `<type>/<이슈번호>-<요약>` | `feat/12-a01-requirement-node` |
| 커밋·PR 제목 | `<type>: <내용> (#이슈번호)` | `feat: add A01 fixture tests (#12)` |

`type`: feat, fix, refactor, docs, test, chore, ci, perf

## 리뷰

- 작성자 외 **1명 승인** 후 병합한다. `.github/CODEOWNERS`가 경로별 리뷰어를 지정한다.
- `specton/contracts/` 변경은 `contract-change` 라벨을 붙이고 **2명 승인** 후 병합한다.
- 실행하지 않은 테스트를 통과로 적지 않는다.

## 병합 전 확인

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run python -m specton.packs.build --check
cd frontend && npm run lint && npm run build   # frontend를 바꾼 경우
```

## 충돌이 잦은 파일

| 파일 | 규칙 |
|---|---|
| `uv.lock`, `frontend/package-lock.json` | 의존성 추가는 단독 PR. 충돌은 손으로 고치지 않고 `uv lock` / `npm install`로 재생성 |
| `specton/contracts/` | 변경 전 이슈로 공지. 작은 PR로 자주 |
| `specton/graph.py` | 통합 담당(R1)만 수정. 노드 연결은 이슈로 요청 |
| `domain_packs/` 생성 파일 (`GENERATED` 표시) | 직접 수정 금지. 입력을 고치고 `uv run python -m specton.packs.build` 결과를 같은 PR에 포함 ([안내](domain_packs/README.md)) |

## 라벨

| 라벨 | 용도 |
|---|---|
| `type:task`, `type:bug` | 이슈 종류 (템플릿이 자동 부착) |
| `role:R1` ~ `role:R5` | 담당 역할 |
| `agent:A01` ~ `agent:A09` | 관련 에이전트 |
| `contract-change` | 데이터 계약 변경 (2인 승인) |
| `blocked` | 다른 이슈·결정 대기 |
| `db`, `llm` | 해당 CI 작업 실행 대상 |

## 보안

- `.env`, API 키, 고객 문서 원문, 실행 산출물은 커밋하지 않는다.
- 실제 LLM 호출 테스트(`-m llm`)는 예산 승인 후 수동으로 실행한다.
