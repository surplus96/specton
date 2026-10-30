# 협업 규칙

작업은 **GitHub Issues + [Projects 보드](https://github.com/users/surplus96/projects/1)**로 관리하고, 코드는 **GitHub Flow**(보호된 `main` + 짧은 작업 브랜치)로 합친다.

## 한눈에 보기

```text
이슈 배정 → 브랜치 → 커밋·push → PR (Closes #이슈) → CI 통과 + 리뷰 승인 → R1이 Squash 병합 → 이슈 자동 종료
보드:  Backlog → Todo → In Progress → In Review(자동) → Done(자동)
```

## 작업 흐름

1. **이슈:** 배정된 이슈를 보드의 "내 작업" 뷰에서 확인한다. **순서** 필드가 낮은 카드부터 진행하고, 이슈의 "넘겨줄 것"·"받을 것"으로 인계 상대를 확인한다 ([역할별 작업 순서](docs/08-roles.md#작업-순서)). 새 작업은 이슈 템플릿(Task / Bug)으로 만든다. 새 이슈는 보드의 Backlog에 자동으로 들어온다.
2. **착수:** 브랜치를 만들어 바로 push한다(3번). 브랜치 이름의 이슈 번호로 카드를 찾아 **In Progress**로 자동 이동한다. 이슈 본문의 "할 일" 체크리스트를 진행하면서 체크한다.
3. **브랜치:** 최신 `main`에서 만든다.
   ```bash
   git switch main && git pull
   git switch -c feat/12-a01-requirement-node
   git push -u origin feat/12-a01-requirement-node
   ```
   이름은 `<type>/<이슈번호>-요약`을 지킨다. 번호가 없으면 카드가 움직이지 않는다.
4. **커밋·push:** 작게 커밋하고 자주 push한다. 브랜치의 커밋은 병합할 때 하나로 합쳐진다(Squash).
5. **PR:** 본문 첫 줄에 `Closes #이슈번호`를 적는다. **이슈 카드**와 **PR 카드**가 **In Review**로 자동 이동한다(Draft PR 카드는 In Progress, Ready for review로 바꾸면 In Review). 작업 중이면 Draft PR로 올린다. PR의 **Assignees에 작성자와 리뷰어를 모두** 넣는다. 팀원별 보드 뷰는 담당자로 거르므로, 리뷰어도 담당자여야 자기 뷰에 리뷰 건이 보인다.
6. **리뷰:** CODEOWNERS가 경로별 리뷰어를 자동 지정한다. 수정 요청을 받으면 카드가 **In Progress**로 돌아간다. 수정을 반영하고 다시 리뷰를 요청하면(Re-request review) PR 카드와 연결 이슈 카드가 **In Review**로 자동 이동한다.
7. **병합:** CI 통과와 승인이 끝나면 **R1(@surplus96)이 Squash 병합**한다. 병합되면 이슈가 닫히고 카드가 **Done**으로 이동하며 브랜치는 자동 삭제된다.

- 2·5·6번의 자동 이동은 `board-status` 워크플로(`.github/workflows/board-status.yml`)가 관리자 토큰(`PROJECT_TOKEN`)으로 한다. 카드가 움직이지 않으면 직접 옮기고 R1에게 알린다.
- 이슈는 직접 닫지 않는다. 카드를 Done으로 끌어도 이슈는 닫히지 않는다. 완료는 PR 병합으로만 한다.
- 브랜치는 **2일 안에** 병합을 목표로 한다. 길어지면 이슈를 쪼갠다.

## 알림·기록

PR의 진행은 `pr-activity` 워크플로(`.github/workflows/pr-activity.yml`)가 **연결 이슈(`Closes #번호`)에 한 줄 댓글**로 자동 기록한다. 이슈만 보고 있어도 리뷰·병합 상황을 알 수 있고, 이슈에 작업 이력이 남는다.

| 시점 | 기록 |
|---|---|
| PR 열림·Ready for review·리뷰 재요청 | 🔎 리뷰 요청 (작성자 → 리뷰어, 변경 규모) |
| 리뷰 제출 | ✅ 승인 / 🔧 변경 요청 (리뷰어 → 작성자, 리뷰 링크). 댓글만 단 리뷰는 기록하지 않는다 |
| 병합 | 🚀 병합 (`main` 커밋, 병합한 사람, 변경 규모) |
| 병합 없이 닫힘 | ⏹ 닫힘 |

- 같은 내용이 Actions 실행 요약에도 남는다. Draft PR과 fork PR은 기록하지 않는다. 실패해도 PR·병합을 막지 않는다.
- **Slack:** 저장소 Secret `SLACK_WEBHOOK_URL`(Incoming Webhook)이 있으면 같은 줄을 Slack 채널에도 보낸다. 없으면 건너뛴다.
- **알림 받기 (각자 한 번):** 저장소 상단 **Watch**에서 **Participating and @mentions**(기본)나 **All Activity**를 고른다. 기록 댓글은 작성자·리뷰어를 멘션하므로 기본값으로도 자기 PR 소식은 받는다. 팀 전체 소식을 보려면 All Activity나 Slack 채널을 쓴다.
- 리뷰 판단은 PR 리뷰 댓글에, 수정 반영 내역은 작성자가 PR 댓글로 요약한다(#79처럼). 자동 기록은 그 결과를 이슈에 연결하는 역할만 한다.

## `main` 보호 규칙

| 규칙 | 내용 |
|---|---|
| 병합 권한 | **R1(@surplus96)만.** 팀원은 PR 작성·리뷰·승인까지 하고 병합 버튼은 비활성 |
| PR 필수 | `main`에 직접 push 불가, 강제 push·삭제 불가 |
| 승인 | **R1(@surplus96)의 승인 필수** (CODEOWNERS 리뷰). 새 커밋을 올리면 기존 승인이 취소된다 |
| 리뷰 대화 | 모든 리뷰 댓글 대화를 해결해야 병합 가능 |
| CI | `python`·`frontend` 통과, 브랜치가 `main` 최신 상태여야 함 |
| 병합 방식 | Squash만 |

- **브랜치가 뒤처졌을 때:** PR 화면의 **Update branch** 버튼을 누른다. 로컬에서 맞추려면 `git pull --rebase origin main` 후 `git push --force-with-lease`.
- **R1 자신의 PR:** GitHub는 작성자 본인의 승인을 허용하지 않는다. R1은 아래 [리뷰 점검표](#리뷰-점검표)로 스스로 점검하고, PR 본문에 점검 결과를 적은 뒤 관리자 예외로 병합한다. 병합 커밋 본문에 예외 병합 사유를 남긴다.

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

- 구현 단계 동안 **모든 PR의 리뷰어는 R1(@surplus96)**이다. CODEOWNERS가 자동으로 지정한다.
- 팀원끼리 서로 리뷰 댓글을 다는 것은 권장한다. 병합 조건은 R1의 승인이다.
- `specton/contracts/` 변경은 `contract-change` 라벨을 붙이고 **2명 승인**(R1 + 계약 영향을 받는 담당 1명)을 받는다. 두 번째 승인은 자동으로 강제되지 않으므로 R1이 병합 전에 확인한다.
- **R1이 작성한 계약 변경:** R1이 승인한다. GitHub은 작성자가 자기 PR을 승인(Approve)할 수 없으므로 다음으로 승인을 대신한다.
  - PR 본문에 R1 자체 점검(리뷰 점검표) 결과와 변경 근거(ADR 또는 이슈)를 적는다. 이것이 R1 승인 기록이다.
  - 계약 영향을 받는 담당을 PR 본문에 멘션해 변경을 알린다. 담당의 승인은 필요하지 않다.
  - CI 통과 후 관리자 예외로 Squash 병합하고, 커밋 본문에 관리자 예외 병합 사유를 남긴다 (예: PR #73, ADR-0010).
- 실행하지 않은 테스트를 통과로 적지 않는다.

### 리뷰 흐름

1. **작성자:** PR을 Ready로 올린다(Draft는 리뷰하지 않음). 본문에 `Closes #번호`, 테스트 명령과 결과, 미정·실패 사항을 적는다.
2. **R1:** 알림 또는 [리뷰 요청 목록](https://github.com/pulls/review-requested)에서 PR을 연다. CI가 실패한 PR은 먼저 작성자에게 돌려보낸다.
3. **R1:** **Files changed** 탭에서 파일마다 점검표를 보고, 문제 줄에 댓글을 단다. 바로 고칠 수 있는 것은 **Suggest changes**로 제안한다. 확인한 파일은 **Viewed**에 체크한다.
4. **R1:** **Review changes**에서 하나를 고른다.
   - **Approve:** 점검표를 모두 통과
   - **Request changes:** 고쳐야 할 것이 있음. 카드가 In Progress로 돌아간다
   - **Comment:** 질문만 있고 판단은 보류
5. **작성자:** 수정해서 push하고, 각 댓글에 답한 뒤 대화를 **Resolve**한다. 새 커밋이 올라오면 기존 승인은 취소되므로 R1이 다시 승인한다.
6. **R1:** 승인·CI 통과·대화 해결이 끝나면 **Squash and merge**. 커밋 제목은 PR 제목 + `(#PR번호)` 그대로 두고, 본문의 체크박스·빈 항목은 정리한다.

### 리뷰 점검표

| 구분 | 확인할 것 |
|---|---|
| 범위 | 이슈의 "할 일"·"완료 조건"과 맞는가. 이슈 밖 변경이 섞이지 않았는가 |
| 테스트 | 새 동작마다 테스트가 있는가(정상·오류·경계). 테스트가 구현을 그대로 다시 쓴 것이 아닌가. 실제 LLM은 stub으로 대신했는가 |
| 계약 | `specton/contracts/`·API 모양이 바뀌면 `contract-change` 라벨, `docs/05`·`docs/06`·`docs/api/openapi.json`도 같이 고쳤는가 |
| 책임 경계 | LLM이 ID·SQL·Mermaid를 만들지 않는가. `codegen/`·`validate/`가 `specton.llm`을 import하지 않는가. 노드가 client를 주입받는가 |
| 도메인 값 | 용어·코드 길이 같은 도메인 상수를 하드코딩하지 않고 `domain_packs/`에서 읽는가. `GENERATED` 파일을 직접 고치지 않았는가 |
| 보안 | 키·비밀번호·고객 문서 원문·평가 데이터가 없는가. 로그·오류 메시지에 원문이나 키가 남지 않는가 |
| 오류 처리 | 실패를 빈 결과나 성공으로 바꾸지 않는가. 예외 종류가 구분되는가 |
| 코드 품질 | 불변 객체·새 객체 반환, 함수 50줄·파일 800줄 이내, 깊은 중첩 없음, 이름이 뜻을 드러내는가 |
| 문서·결정 | 동작이 바뀌면 `docs/`를 같은 PR에서 고쳤는가. 설계 결정이 바뀌면 ADR을 갱신했는가 |
| 이름 규칙 | 브랜치 `<type>/<이슈번호>-요약`, PR 제목 `<type>: 내용`(번호 없음) |

## 테스트 작성

기능을 구현하면 그 기능의 테스트도 같은 PR에 넣는다. CI는 `tests/` 아래 `test_*.py`를 자동으로 모두 실행하므로 CI 설정은 건드리지 않는다. 테스트가 없으면 CI는 통과해도 리뷰에서 Request changes 대상이다.

| 할 일 | 방법 |
|---|---|
| 파일 위치 | `tests/unit/test_<대상>.py` (예: `test_a01_node.py`, `test_excel_ingest.py`) |
| 순서 | 테스트 먼저 → 실패 확인 → 구현 → 통과 |
| LLM을 쓰는 노드 | `stub_client`로 응답을 준비한다. 실제 API는 부르지 않는다 ([사용법](docs/04-agents.md#공통-llm-client-사용법)) |
| 케이스 | 이슈의 완료 조건과 TC([docs/12](docs/12-test-cases.md)) 기준으로 정상·오류·경계를 하나 이상. 에이전트는 고정 응답 3종(정상·계약 오류·근거 부족) |
| DB가 필요한 테스트 | `@pytest.mark.db`. CI 기본 실행에서 빠진다. 로컬에서 `docker compose up -d db` 후 `uv run pytest -m db` |
| 실제 LLM 호출 테스트 | `@pytest.mark.llm`. 예산 승인 후 수동으로만 실행 |
| 공통 준비 코드 | 처음에는 각 테스트 파일 안에 둔다. 여러 파일에서 실제로 중복되면 `tests/conftest.py`로 모은다 |

- LLM을 쓰지 않는 작업(입력 파서, 모델 정리, DDL 등)은 입력 파일·객체를 넣고 결과를 확인하는 일반 테스트로 쓴다.
- 지금 CI는 커버리지를 측정하지 않는다. 목표는 새 코드 80% 이상이다.
- `@pytest.mark.db` 테스트를 CI에서 돌리는 작업은 격리 DB 작업(#15) 무렵에 추가한다.

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
