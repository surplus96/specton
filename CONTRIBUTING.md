# 협업 규칙

작업은 **GitHub Issues + [Projects 보드](https://github.com/users/surplus96/projects/1)**로 관리하고, 코드는 **GitHub Flow**(보호된 `main` + 짧은 작업 브랜치)로 합친다.

## 한눈에 보기

```text
이슈 배정 → 브랜치 → 커밋·push → PR (Closes #이슈) → CI 통과 + 리뷰 승인 → R1이 Squash 병합 → 이슈 자동 종료
보드:  Backlog → Todo → In Progress → In Review(자동) → Done(자동)
```

## 작업 흐름

1. **이슈:** 배정된 이슈를 보드의 "내 작업" 뷰에서 확인한다. 새 작업은 이슈 템플릿(Task / Bug)으로 만든다. 새 이슈는 보드의 Backlog에 자동으로 들어온다.
2. **착수:** 카드를 **In Progress**로 옮긴다. 이슈 본문의 "할 일" 체크리스트를 진행하면서 체크한다.
3. **브랜치:** 최신 `main`에서 만든다.
   ```bash
   git switch main && git pull
   git switch -c feat/12-a01-requirement-node
   ```
4. **커밋·push:** 작게 커밋하고 자주 push한다. 브랜치의 커밋은 병합할 때 하나로 합쳐진다(Squash).
5. **PR:** 본문 첫 줄에 `Closes #이슈번호`를 적는다. 카드가 **In Review**로 자동 이동한다. 작업 중이면 Draft PR로 올린다.
6. **리뷰:** CODEOWNERS가 경로별 리뷰어를 자동 지정한다. 수정 요청을 받으면 카드가 **In Progress**로 돌아간다.
7. **병합:** CI 통과와 승인이 끝나면 **R1(@surplus96)이 Squash 병합**한다. 병합되면 이슈가 닫히고 카드가 **Done**으로 이동하며 브랜치는 자동 삭제된다.

- 이슈는 직접 닫지 않는다. 카드를 Done으로 끌어도 이슈는 닫히지 않는다. 완료는 PR 병합으로만 한다.
- 브랜치는 **2일 안에** 병합을 목표로 한다. 길어지면 이슈를 쪼갠다.

## `main` 보호 규칙

| 규칙 | 내용 |
|---|---|
| 병합 권한 | **R1(@surplus96)만.** 팀원은 PR 작성·리뷰·승인까지 하고 병합 버튼은 비활성 |
| PR 필수 | `main`에 직접 push 불가, 강제 push·삭제 불가 |
| 승인 | 작성자 외 1명. 새 커밋을 올리면 기존 승인이 취소된다 |
| 리뷰 대화 | 모든 리뷰 댓글 대화를 해결해야 병합 가능 |
| CI | `python`·`frontend` 통과, 브랜치가 `main` 최신 상태여야 함 |
| 병합 방식 | Squash만 |

- **브랜치가 뒤처졌을 때:** PR 화면의 **Update branch** 버튼을 누른다. 로컬에서 맞추려면 `git pull --rebase origin main` 후 `git push --force-with-lease`.
- **R1 자신의 PR:** 팀원 1명의 승인을 받는다. 관리자 예외 병합은 저장소 설정·문서 정리처럼 팀이 합의한 경우에만 쓰고, PR 본문에 이유를 적는다.

## 이름 규칙

| 대상 | 형식 | 예시 |
|---|---|---|
| 브랜치 | `<type>/<이슈번호>-<요약>` | `feat/12-a01-requirement-node` |
| PR 제목 | `<type>: <내용>` (번호 없이) | `feat: add A01 fixture tests` |
| 병합 커밋 | PR 제목 + `(#PR번호)` (GitHub가 자동으로 붙임), 본문은 PR 본문 | `feat: add A01 fixture tests (#40)` |
| 브랜치 커밋 | `<type>: <내용>` 권장 | `test: add A01 contract error fixture` |

`type`: feat, fix, refactor, docs, test, chore, ci, perf

이슈 번호는 브랜치 이름과 PR 본문의 `Closes #번호`로 연결한다. PR 제목에 이슈 번호를 넣으면 병합 커밋에 번호가 두 번 붙는다.

## 리뷰

- CODEOWNERS가 지정한 리뷰어가 검토한다. 담당 범위는 [docs/08-roles.md](docs/08-roles.md).
- `specton/contracts/` 변경은 `contract-change` 라벨을 붙이고 **2명 승인**을 받는다. 자동으로 강제되지 않으므로 R1이 병합 전에 확인한다.
- 실행하지 않은 테스트를 통과로 적지 않는다.

## 병합 전 확인

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run python -m specton.packs.build --check
cd frontend && npm run lint && npm run build   # frontend를 바꾼 경우
```

CI도 같은 검사를 실행한다. `uv run pytest`에는 문서가 저장소 밖 문서를 참조하지 않는지 보는 검사가 포함된다.

## 이슈 작성

Task 템플릿의 칸을 그대로 채운다. 초기 작업 이슈 #3~#25가 예시다.

| 칸 | 내용 |
|---|---|
| 관련 항목 | 요구사항(REQ), 설계 문서(`docs/`), 테스트(TC), 결정 대기 ADR. 저장소 안에 있는 근거만 적는다 |
| 할 일 | 체크리스트 (`- [ ]`) |
| 완료 조건 | 확인 가능한 결과 |
| 선행 작업 | 선행 이슈 `#번호`, 기다리는 이유, 기다리는 동안 할 수 있는 일 |

이슈를 만든 뒤 담당자(Assignees), 마일스톤, `role:` 라벨을 지정하고, 선행 이슈는 오른쪽 **Relationships → Blocked by**로도 연결한다.

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
| `role:R1` ~ `role:R5` | 담당 역할 (담당자 지정과 함께 붙임) |
| `agent:A01` ~ `agent:A09` | 관련 에이전트 |
| `contract-change` | 데이터 계약 변경 (2인 승인) |
| `blocked` | 결정(ADR)·외부 조건을 기다리는 중. 다른 이슈를 기다리는 경우는 Blocked by 관계로 표시 |
| `db`, `llm` | DB 통합 테스트(`-m db`) 또는 실제 LLM 테스트(`-m llm`)를 수동으로 실행해야 하는 변경. CI는 이 테스트를 돌리지 않는다 |

## 결정 기록

설계 결정을 새로 하거나 바꿀 때는 `docs/adr/`에 ADR을 추가하는 PR을 올린다 ([작성 규칙](docs/adr/README.md)). 회의에서 승인되면 상태를 "승인"으로 바꾼다.

## 보안

- `.env`, API 키, 고객 문서 원문, 실행 산출물, 평가 데이터·정답은 커밋하지 않는다.
- 실제 LLM 호출 테스트(`-m llm`)는 예산 승인 후 수동으로 실행한다.
- Dependabot 보안 업데이트 PR은 R1이 검토·병합한다.
