# 에이전트

> 상태: **초안** (모델 ADR-0007·리뷰어 ADR-0008·심각도 ADR-0010 승인, 노드는 각 이슈에서 구현 중)

## 구성

설계 생성 4개, 설계 검토 4개, 조건부 재작업 판단 1개. 9개는 논리적 역할 수이며 각각 별도 서버나 다른 모델을 요구하지 않는다.

| ID | 역할 | 역할 담당 | 요구사항 | 테스트 |
|---|---|---|---|---|
| A01 | 요구사항 분석 | R2 | REQ-04 | TC-A01 |
| A02 | 기능 설계 | R3 | REQ-06 | TC-A02 |
| A03 | 엔티티·속성·CRUD | R4 | REQ-07 | TC-A03 |
| A04 | 관계 설계 | R5 | REQ-08 | TC-A04 |
| A05 | 관계 모순 검토 | R1 | REQ-14 | TC-A05 |
| A06 | 데이터 누락 검토 | R2 | REQ-14 | TC-A06 |
| A07 | 비기능 요구 검토 | R3 | REQ-14 | TC-A07 |
| A08 | 정규화 검토 | R4 | REQ-14 | TC-A08 |
| A09 | 조건부 재작업 판단 | R1 | REQ-16 | TC-A09 |

담당자는 [08 역할](08-roles.md) (ADR-0001). 교차 검토자는 PR마다 CODEOWNERS가 지정한다.

## 공통 노드 구조

```text
입력 선택 → 팩·프롬프트 구성 → 공통 LLM client 호출 → 출력 계약 검증
        → 참조·인용 검사 → 코드 ID 부여 → 상태 부분 갱신
```

- LLM 응답에 ID를 만들게 하지 않는다. 참조 가능한 REQ·기능 ID는 코드가 허용 목록으로 넘긴다.
- 구조화 출력 검증 실패는 구체 오류를 담아 **최대 2회** 재요청한다.
- 거절·API 타임아웃·출력 계약 실패·근거 부족을 구분한다. 빈 성공 응답으로 바꾸지 않는다.
- 단계별 모델·프롬프트 버전을 기록한다. 모델은 설계(A01~A04) `gpt-6.1-sol`, 검토·라우터(A05~A09) `gpt-6-luna` (ADR-0007).

### 노드 작성 규칙

설계 노드(A01~A04)와 재작업 판단(A09)은 같은 모양으로 만든다. 검토 관점 A05~A08은 노드 파일이 아니라 관점 설정 파일로 만든다 ([설정형 리뷰어](#설정형-리뷰어-adr-0008)).

| 항목 | 규칙 |
|---|---|
| 파일 | `specton/nodes/a01_requirements.py`, `a02_functions.py`, `a03_entities.py`, `a04_relationships.py`, `a09_rework_router.py`. 담당자가 소유한다 |
| 프롬프트 | 노드 파일의 상수 `PROMPT_VERSION`(예: `a02-v1`)과 `SYSTEM_PROMPT`. 프롬프트를 바꾸면 버전을 올린다 |
| 출력 모델 | 노드 파일에 `A02Output`처럼 정의하고 계약의 `*Draft`로만 구성한다 (예: `functions: tuple[FunctionDraft, ...]`). ID·버전 필드를 넣지 않는다 |
| 함수 | `run(client, state, settings, *, pack, token_budget=None) -> NodeRun[...]`. 저장 모델(코드가 ID를 붙인 `Function` 등)과 호출 기록을 돌려준다 |
| 요청 | `specton.nodes.common.build_request`로 만든다. 공통 규칙(입력 속 지시 무시·ID 생성 금지·원문 인용)과 `<data>` 감싸기, few-shot 대화 쌍, 모델 선택(`role="design"`/`"review"`)을 대신한다 |
| ID | `assign_ids("FUNC", n)`처럼 코드가 순번으로 붙인다. 형식 확정은 #12 |
| few-shot | `load_examples(pack, "A02", A02Output)`로 읽는다. 예시의 `output`은 출력 모델과 같은 모양이어야 하며 다르면 `ExampleError`가 난다. `input`은 노드가 `<data>`에 넣는 것과 같은 모양(문자열 또는 매핑) |
| 실패 | LLM 오류(`LLMError`)는 잡지 않고 그대로 올린다. 그래프가 `exc.code`로 실행 실패를 기록한다. 예외: A09는 실패를 "답 없음"으로 바꿔 HITL 2로 넘긴다 |
| 테스트 | `tests/unit/test_a02_functions.py` 등. stub으로 정상 응답·형식 오류 후 재요청·거절 3종 이상 |

노드는 `LLMClient`를 **인자로 주입받는다**. 실제 client는 그래프가 `openai_client(get_settings())`로 한 번 만들어 넘기고, 테스트에서는 `stub_client`를 넣는다. 노드는 `openai` 패키지나 `openai_transport`를 직접 import하지 않는다.

```python
from specton.config import Settings
from specton.contracts import DesignState, Function, FunctionDraft
from specton.contracts.base import Contract
from specton.llm.client import LLMClient
from specton.nodes.common import NodeRun, assign_ids, build_request
from specton.packs.examples import load_examples

PROMPT_VERSION = "a02-v1"
SYSTEM_PROMPT = """\
너는 기능 설계자다. 요구사항을 기능으로 묶고 각 기능이 충족하는 req_ids를 적는다.
..."""


class A02Output(Contract):
    functions: tuple[FunctionDraft, ...]


def run(
    client: LLMClient,
    state: DesignState,
    settings: Settings,
    *,
    pack: str,
    token_budget: int | None = None,
) -> NodeRun[tuple[Function, ...]]:
    request = build_request(
        settings,
        role="design",
        stage="A02",
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        data={"requirements": [r.model_dump(mode="json") for r in state.requirements]},
        examples=load_examples(pack, "A02", A02Output),
    )
    result = client.complete(request, A02Output, token_budget=token_budget)
    drafts = result.output.functions
    ids = assign_ids("FUNC", len(drafts))
    functions = tuple(
        Function.model_validate({**d.model_dump(), "id": i})
        for d, i in zip(drafts, ids, strict=True)
    )
    return NodeRun(output=functions, calls=result.calls)
```

- `complete()`는 출력 모델로 검증된 결과만 돌려준다. 형식이 틀리면 오류 내용을 담아 최대 2회 재요청하고, 그래도 틀리면 `LLMContractError`를 던진다.
- 실패는 종류별 예외다: `LLMRefusalError`(거절, 재요청 안 함), `LLMTimeoutError`, `LLMAPIError`, `LLMContractError`, `LLMBudgetExceededError`. 모두 `LLMError`를 상속하고 `code`(오류 코드)와 `calls`(실패까지의 호출 기록)가 있다. 빈 결과로 바꾸지 말고 그대로 올린다.
- 호출 기록(`result.calls`)에는 단계·프롬프트 버전·모델·시도 번호·토큰·시간이 남는다. 원문과 키는 남지 않는다.
- 실행 토큰 예산은 그래프가 남은 양을 `token_budget`으로 넘겨 지킨다.
- 저장 모델로 바꿀 때 `Function.model_validate(...)`처럼 검증을 거친다. 이미 만든 계약 객체의 값을 바꿀 때는 `evolve(...)`를 쓴다.

**노드 테스트 (실제 API 없이)**

```python
from specton.llm.errors import LLMRefusalError
from specton.llm.stub import refusal, reply, stub_client


def test_a02_assigns_ids_to_designed_functions() -> None:
    client, transport = stub_client(reply(A02Output(functions=(...,))))

    run_result = run(client, state, settings, pack="inventory")

    assert [f.id for f in run_result.output] == ["FUNC-01"]
    assert len(transport.sent) == 1  # LLM 호출 횟수


def test_a02_retries_on_invalid_output() -> None:
    client, transport = stub_client(reply("{}"), reply(A02Output(functions=(...,))))

    run(client, state, settings, pack="inventory")

    assert len(transport.sent) == 2


def test_a02_raises_refusal() -> None:
    client, _ = stub_client(refusal())

    with pytest.raises(LLMRefusalError):
        run(client, state, settings, pack="inventory")
```

- `reply(모델 객체)`는 정상 응답, `reply("문자열")`은 형식이 틀린 응답, `refusal()`은 거절이다. 예외 객체(`LLMTimeoutError("...")`)를 넣으면 그 오류가 난다.
- 준비한 응답보다 많이 호출하면 stub이 `AssertionError`로 실패한다.
- 테스트용 팩이 필요하면 `load_examples(..., root=tmp_path)`처럼 임시 폴더의 예시 파일을 쓴다.
- 공통 부분의 동작은 `tests/unit/test_node_common.py`·`test_pack_examples.py`, 공통 client는 `test_llm_client.py`, OpenAI 호출은 `test_openai_transport.py`에서 검증한다.

### 프롬프트·문맥

- 프롬프트는 ① 역할·할 일 ② 신뢰할 수 있는 규칙·팩 ③ 인용된 입력 데이터 ④ 허용 참조·출력 스키마로 나눈다.
- 원문 속 지시를 시스템 명령으로 따르지 않는다.
- 내부 추론 전문 대신 짧은 판단 근거와 원문 인용을 받는다.
- 검토 입력에는 관련 설계 요소와 허용 대안을 넣고, 입력을 잘랐는지 기록한다.
- few-shot 예시는 `domain_packs/<pack>/examples/A0x.yaml`에서 읽는다. 개발용 세트에서만 가져오고 평가용 세트 문서는 넣지 않는다.

## 설계 에이전트 A01~A04

| ID | 입력 | 출력 | 판단 | 검증 |
|---|---|---|---|---|
| A01 | 원문 블록·source_ref·팩 문맥 | 분류·분할·품질 경고·질문·원문 연결 후보 | 복합 문장 분해, FR/NFR, 불명확 조건 질문 | 원문 없는 조건 추가·분할 원문 누락 검출 |
| A02 | HITL 반영 요구사항·팩 | 기능명·설명·우선순위·근거·req_ids | 기능 분해/묶음, 미정 우선순위 질문. `entity_ops`는 비움 | 존재하는 REQ만 참조, 우선순위로 기능 자동 삭제 금지 |
| A03 | 요구사항·기능·팩 타입/용어 | 엔티티·속성·기능별 EntityOp | 저장 대상·타입/제약·CRUD, 이력 삭제 면제 근거 | 기능·REQ 참조·타입 검증, 모든 엔티티에 CRUD 4종 강제 금지 |
| A04 | 현재 엔티티·속성·요구사항 | 방향·카디널리티·optional·identifying·인용 | 자기참조·N:M·필수/선택 | 없는 엔티티 거절, 인용 실재, FK는 코드가 파생 |

우선순위(MoSCoW)는 납품 범위 논의용 정보다. CRUD나 테이블 구조를 결정하지 않는다. 입력에 있는 값은 보존하고, 없으면 `null` + 출처 표시로 남겨 HITL에서 확정하는 안을 제안한다 (ADR-0006).

## 검토 관점 A05~A08

검토자는 전체 문서 대신 **요구사항과 관련 설계 요소의 쌍**을 받는다. 원본 모델을 직접 고치지 않는다.

| ID | 판단 기준 | 오탐 방지 기준 |
|---|---|---|
| A05 관계 모순 | 방향·개수·필수 조건이 원문과 모순되는가 | 같은 요구를 충족하는 다른 관계 표현 허용 |
| A06 데이터 누락 | 요구 충족에 필요한 기능·정보가 빠졌는가 | 다른 테이블·기능에서 충족하는 경우까지 확인 |
| A07 비기능 요구 | 권한·감사·보존 요구의 반영 위치와 책임이 있는가 | 컬럼 존재만으로 보안·성능 충족을 단정하지 않음 |
| A08 정규화 | 반복 속성·다중값·중복 저장에 수정 이상 위험이 있는가 | 업무 근거가 있는 스냅샷·이력 저장은 오류로 보지 않음 |

### 설정형 리뷰어 (ADR-0008)

- 관점 4개는 논리적으로 유지하고, 관점마다 프롬프트·체크리스트·입력 선택·오탐 기준을 **설정 파일**로 둔다.
- 구현은 **리뷰어 노드 1종**(`specton/review/reviewer.py`). `SPECTON_REVIEW_MODE`로 `parallel`(관점마다 1회 호출)과 `combined`(전체 1회 호출)를 바꾼다. 기본값은 `combined`.
- `parallel`의 관점 동시 실행과 결과 합류는 그래프가 맡는다 (#18). 노드는 관점 하나를 실행하는 함수(`review_perspective`)를 제공한다.
- 출력은 관점별 `BranchResult`이고 지적은 공통 `Finding`이다. `reviewer_id`로 관점을 구분한다. `id`·`fingerprint`·`iteration`은 코드가 붙인다.
- 한 관점이 실패해도 다른 관점의 결과는 남는다. 실패한 관점은 `ok=false`와 오류 코드(`LLM_REFUSED` 등)로 표시하고, 하나라도 실패하면 불완전 검토다 (`ReviewRun.complete`, TC-F14). `combined` 출력에 빠진 관점은 `LLM_OUTPUT_INVALID`로 실패 처리한다.
- 실행 방식은 같은 입력으로 두 방식을 비교해 탐지율·오탐·토큰·시간으로 정한다.
- R1이 노드 틀을, 각 관점 담당이 자기 설정·테스트·평가를 맡는다.

#### 관점 설정 형식

관점마다 `specton/review/perspectives/<reviewer_id>.yaml` 파일 하나를 둔다. 파일을 추가하면 리뷰어가 그 관점을 실행한다. 예시는 `A05.yaml`이다.

| 키 | 필수 | 내용 |
|---|---|---|
| `reviewer_id` | 예 | `A05`~`A08`. 파일 이름과 같아야 한다 |
| `name` | 예 | 관점 이름 (예: 관계 모순 검토) |
| `prompt_version` | 예 | 프롬프트를 바꿀 때마다 올린다 (예: `a05-v2`). 호출 기록에 남는다 |
| `instructions` | 예 | 관점의 역할과 할 일 |
| `checklist` | 예 | 점검 항목 목록 (1개 이상) |
| `inputs` | 예 | 보여 줄 입력: `requirements`·`functions`·`entities`·`relationships` 중 선택 |
| `false_positive_guards` | 예 | 지적하지 않는 경우 (오탐 기준, 1개 이상) |

- 항목 안에 `: `(콜론+공백)가 있으면 YAML이 키로 읽으므로 작은따옴표로 감싼다. 예: `- '방향이 맞는가 (예: 문서가 부모)'`
- 알 수 없는 키는 거절한다. 공통 규칙(입력 속 지시 무시, 입력에 있는 ID만 사용, 원문 인용)은 노드가 모든 관점에 붙이므로 설정에 다시 적지 않는다.
- 관점 담당은 설정 파일과 함께 stub 테스트를 만든다. `tests/unit/test_reviewer.py`의 `_perspective`·`_state`·`stub_client` 사용법을 참고한다.

### 지적 확정 절차

1. Pydantic으로 형식·허용값 검사
2. 대상 ID·요구사항 참조·인용 위치가 현재 입력에 실재하는지 확인
3. 규칙 지적(`source=rule`)과 LLM 지적을 구분하고, 같은 문제는 근거를 보존해 병합
4. 이전 iteration 지문(fingerprint)과 비교해 반복 지적 식별
5. 자동 재작업 / 사용자 확인 / 참고 의견으로 분류

심각도: 규칙 위반 critical(차단), LLM 지적 major/minor, 자동 재작업은 critical·major만 (ADR-0010). 인용이 존재한다는 사실은 의미 판단이 맞다는 증거가 아니다. 오탐은 평가로 따로 측정한다.

## A09 조건부 재작업 판단

재작업 판단은 코드(`specton/review/rework.py`)가 먼저 하고, 정하지 못한 지적만 A09(`specton/nodes/a09_rework_router.py`)에 묻는다.

```text
decide_rework(이번 반복 지적, 재작업 횟수, 상한, 이전 지문)
 ├─ critical·major 지적 없음                → NONE (HITL 2로 진행, minor는 참고 의견)
 ├─ 재작업 횟수 ≥ 상한(3)                   → HITL (rework_limit)
 ├─ 이전 반복과 같은 지문의 지적             → HITL (repeated_findings)
 ├─ 모든 대상 지적에 target_stage 있음      → REWORK (가장 앞 단계)
 └─ target_stage 없는 지적 있음             → ASK_ROUTER → A09
       resolve_with_router(결정, A09 답)    → REWORK (이미 정한 단계와 A09 답 중 앞 단계)
                                              또는 HITL (router_undecided)
```

- 유효한 `target_stage`가 있으면 A09를 호출하지 않는다 (REQ-16).
- 단계 순서는 `requirements` < `functions` < `data_model`. 서로 다른 단계가 섞이면 다시 실행하는 범위가 넓은 앞 단계로 묶는다.
- A09 입력은 `target_stage`가 없는 지적과 그 근거 요구사항뿐이다. 전체 설계는 넣지 않는다.
- A09 출력은 `requirements` / `functions` / `data_model` / `undecidable`과 근거. 다른 값은 출력 모델이 거절하고 재요청한다.
- `undecidable`이거나 A09 호출이 실패(거절·타임아웃·계약 오류)하면 답 없음(`RouterAnswer.stage=None`, `error_code` 기록)으로 HITL 2에 넘긴다. 재작업 판단 실패로 실행 전체를 실패시키지 않는다.
- 재작업 횟수·이전 지문은 그래프(#17)가 상태에 보관해 넘긴다.

## 규칙 검사 RULE-01~07

착수용으로 구체화한 제안 목록이다. 설정·면제는 `domain_packs/common/rules.yaml`에서 관리한다.

| 코드 | 검사 | 차단 예시 |
|---|---|---|
| RULE-01 | ID·참조 유효성 | 존재하지 않는 REQ·기능·엔티티 참조 |
| RULE-02 | 요구사항 추적 범위 | req_ids 누락, 지원 범위 요구의 기능 미연결 |
| RULE-03 | PK·타입·제약 구조 | PK 없음, 길이/정밀도 불일치 |
| RULE-04 | 관계·FK·N:M 정합 | 잘못된 부모 키, 연결 테이블 추적 유실 |
| RULE-05 | 명명·중복 | 명명 규칙 위반, 같은 이름 충돌 |
| RULE-06 | CRUD 정합 | 사용 엔티티 미연결, 면제 없는 필수 조작 누락 |
| RULE-07 | DDL 파싱·실행 | 파싱 실패, 격리 DB 실행 실패 |

## 구현 완료 기준

에이전트마다 다음을 갖춰야 완료다. 프롬프트만 작성한 상태는 완료가 아니다.

- 정상 응답·계약 오류·근거 부족의 고정 응답(fixture) 테스트 3종 이상
- 입출력 예시, 프롬프트·팩 버전
- client를 주입할 수 있는 얇은 노드 어댑터
- 교차 검토 코멘트
- 실제 API 호출은 예산 승인 후 별도 평가에서 확인
