"""설계 그래프 (03 문서 "실행 흐름", #17). 통합 담당(R1)만 수정한다.

입력 → 추출 확인 → A01 → HITL 1 → A02 → A03 → A04 → 모델 정리 → 생성(병렬) → 규칙
→ 검토(병렬) → 병합 → 재작업 판단 → HITL 2 → 내보내기 순서로 잇는다.
- 노드는 상태만 반환하고 DB에 쓰지 않는다. 앱 저장은 실행기가 노드가 끝난 뒤 한다 (ADR-0012).
- 사람 확인(interrupt)은 LLM을 부르지 않는 전용 노드에서만 한다.
  재개하면 그 노드를 처음부터 다시 돌기 때문이다.
- 추출 확인(UI-02)은 `review`·`fail` 블록이 있을 때만 멈춘다 (ADR-0015 결정 1).
  답은 블록의 `user_decision`·`excluded_reason`으로 남기고 블록을 지우지 않는다 (RTM 「제외」 행).
- 분석 확인(HITL 1, UI-03)은 품질 경고·질문이나 분할이 있을 때만 멈춘다 (ADR-0015 결정 1).
  멈추지 않으면 `analysing → designing`으로 바로 간다.
- 지금은 빈 노드(stub)로 잇는다. 에이전트 노드는 담당 이슈가 끝나면 `nodes`로 넘겨 바꾼다.
"""

import operator
import re
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from specton.artifacts import GeneratedArtifact
from specton.config import get_settings
from specton.contracts import (
    BranchResult,
    DesignState,
    ExtractionResponse,
    Finding,
    Requirement,
    RequirementsResponse,
    RunState,
    ValidationStatus,
)
from specton.contracts.base import ExtractionStatus, TargetStage, UserDecision
from specton.contracts.findings import FindingSource, Severity
from specton.contracts.requirements import SourceRequirement
from specton.review.merge import merge_review
from specton.review.rework import (
    HitlReason,
    ReworkAction,
    ReworkDecision,
    decide_rework,
    resolve_with_router,
)
from specton.validation_attempts import ValidationAttempt, merge_validation_attempts

GENERATORS = ("ddl", "erd", "rtm")  # 같은 고정 모델을 읽는 코드 작업 (병렬)
REVIEWERS = ("A05", "A06", "A07", "A08")  # 검토 관점 = 리뷰 가지 이름 (병렬)
STAGE_NODES: Mapping[TargetStage, str] = {
    TargetStage.REQUIREMENTS: "a01",
    TargetStage.FUNCTIONS: "a02",
    TargetStage.DATA_MODEL: "a03",
}
# 순차 노드가 끝난 뒤의 run 상태 (03 문서 상태도). 병렬 가지와 A09는 상태를 바꾸지 않는다.
# A09는 자동 재작업(reviewing)과 HITL 2 수정 요청(designing) 양쪽에서 오기 때문이다.
STAGE_STATUS: Mapping[str, RunState] = {
    "parse": RunState.PARSING,
    "a01": RunState.ANALYSING,
    "a02": RunState.DESIGNING,
    "a03": RunState.DESIGNING,
    "a04": RunState.DESIGNING,
    "normalize": RunState.DESIGNING,
    "rules": RunState.REVIEWING,
    "export": RunState.EXPORTING,
}
# HITL 2 답을 받은 뒤 상태. resume API(#110)가 바꾸는 상태와 같아야 실행기 저장이 되돌아가지 않는다.
# 보류는 상태를 바꾸지 않고 다시 묻는다 (06 문서 resume).
REVIEW_STATUS: Mapping[str, RunState] = {
    "approve": RunState.EXPORTING,
    "revise": RunState.DESIGNING,
}


class ExtractionFailedError(Exception):
    """분석할 원문을 얻지 못했다. 실행은 `EXTRACTION_FAILED`로 끝난다 (ADR-0015 결정 3·5).

    파일 단위로 읽지 못했거나, 추출 확인에서 제외하고 남은 원문이 0건일 때다.
    `notice`는 화면에 보일 짧은 안내, `detail`은 원인이다.
    """

    def __init__(self, notice: str, detail: str = "") -> None:
        super().__init__(f"{notice} {detail}".strip())
        self.notice = notice
        self.detail = detail


class RunNote(TypedDict):
    """노드가 실행 기록(`run_event`)에 남길 안내.

    실행기가 그 노드를 저장할 때 status 이벤트로 쓴다.
    """

    message: str
    payload: dict[str, Any]


class DocumentRef(TypedDict):
    """실행에 올린 문서. 실행기가 첫 상태에 넣고 parse 노드가 읽는다."""

    document_id: str
    file_format: str
    storage_ref: str  # 저장소 기준 상대 위치 (`Settings.storage_dir`)


def _merge_branches(
    old: Mapping[str, BranchResult], new: Mapping[str, BranchResult]
) -> dict[str, BranchResult]:
    """병렬 가지 결과는 가지 이름별로 모은다. 재작업 때는 같은 이름의 새 결과로 바뀐다."""
    return {**old, **new}


def _merge_versions(
    old: Mapping[str, tuple[str, str]], new: Mapping[str, tuple[str, str]]
) -> dict[str, tuple[str, str]]:
    """병렬 가지가 쓴 (프롬프트 버전, 모델). 가지는 design을 동시에 쓸 수 없어 따로 모은다."""
    return {**old, **new}


def _merge_artifacts(
    old: Mapping[str, GeneratedArtifact], new: Mapping[str, GeneratedArtifact]
) -> dict[str, GeneratedArtifact]:
    """병렬 생성 결과를 revision·종류·형식별로 모으고 export 결과로 갱신한다."""
    return {**old, **new}


class GraphState(TypedDict, total=False):
    evaluation_condition: str  # 평가 전용 실행기의 고정 조건 해시. 기본 API는 사용하지 않는다
    call_summaries: Annotated[dict[str, tuple[dict[str, Any], ...]], operator.or_]
    design: DesignState
    documents: tuple[DocumentRef, ...]  # 업로드 문서 (parse 노드 입력)
    notes: tuple[
        RunNote, ...
    ]  # 방금 끝난 노드가 남긴 안내. 실행기는 노드 결과(update)에서만 읽는다
    branches: Annotated[dict[str, BranchResult], _merge_branches]
    generated_artifacts: Annotated[dict[str, GeneratedArtifact], _merge_artifacts]
    validation_attempts: Annotated[dict[str, ValidationAttempt], merge_validation_attempts]
    ddl_validation_status: ValidationStatus | None
    rule_findings: tuple[Finding, ...]  # 규칙 검사(#15) 결과
    normalization_failed: bool  # 정리 실패이면 생성·LLM 검토를 건너뛴다
    requires_manual_review: bool  # 사전·명명 규칙 등 자동 수정으로 해결할 수 없는 문제
    rework_count: int  # 자동 재작업 횟수 (사람의 수정 요청은 세지 않는다)
    fingerprints: tuple[str, ...]  # 지난 반복의 지적 지문
    action: ReworkAction | None  # 재작업 판단 결과
    next_stage: TargetStage | None
    hitl_reason: HitlReason | None
    router_stage: TargetStage | None  # A09 답
    router_decision: dict[str, Any] | None  # 판단 시점 revision·근거·안전한 오류 코드
    rejected_findings: tuple[dict[str, str | None], ...]  # 근거 검사 제외 메타데이터
    unrouted: tuple[Finding, ...]  # 코드가 복귀 단계를 정하지 못해 A09에 넘길 지적
    branch_versions: Annotated[dict[str, tuple[str, str]], _merge_versions]  # 합류에서 기록
    tokens_used: Annotated[int, operator.add]  # 이번 실행에 쓴 LLM 토큰 (`max_tokens_per_run`)
    revising: bool  # HITL 2의 수정 요청으로 A09에 왔는지
    failed_branches: tuple[str, ...]  # 이번 검토에서 실패하거나 빠진 리뷰 가지 (불완전 검토)
    requirements_answer: dict[str, Any]
    review_response: dict[str, Any]


Node = Callable[[GraphState], Mapping[str, Any]]


def initial_state(design: DesignState, documents: tuple[DocumentRef, ...] = ()) -> GraphState:
    return GraphState(
        design=design,
        documents=documents,
        branches={},
        generated_artifacts={},
        validation_attempts={},
        ddl_validation_status=None,
        rule_findings=(),
        normalization_failed=False,
        requires_manual_review=False,
        rework_count=0,
        fingerprints=(),
    )


def build_graph(
    nodes: Mapping[str, Node] | None = None,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    max_rework: int | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """그래프를 만든다. `nodes`로 넘긴 노드가 같은 이름의 빈 노드를 바꾼다."""
    impl = {**_stub_nodes(), **(nodes or {})}
    unknown = sorted(set(impl) - set(_stub_nodes()))
    if unknown:
        raise ValueError(f"그래프에 없는 노드입니다: {', '.join(unknown)}")
    limit = get_settings().max_rework_iterations if max_rework is None else max_rework

    g = StateGraph(GraphState)
    for name, status in STAGE_STATUS.items():
        _add(g, name, _with_status(impl[name], status))
    for name in (*GENERATORS, *REVIEWERS, "a09"):
        _add(g, name, _as_dict(impl[name]))
    _add(g, "complete", _waiting(RunState.COMPLETED))
    _add(g, "wait_extraction", _waiting(RunState.AWAITING_INPUT))
    _add(g, "hitl_extraction", _ask_extraction)
    _add(g, "wait_requirements", _waiting(RunState.AWAITING_REQUIREMENTS))
    _add(g, "hitl_requirements", _ask_requirements)
    _add(g, "generate", _with_status(_noop, RunState.GENERATING))
    _add(g, "merge", _merge)
    _add(g, "normalization_failure", _normalization_failure)
    _add(g, "generation_result", _with_status(_noop, RunState.GENERATING))
    _add(g, "validation_failure", _with_status(_validation_failure, RunState.REVIEWING))
    _add(g, "route", _route(limit))
    _add(g, "route_router", _route_router)
    _add(g, "wait_review", _with_status(impl["wait_review"], RunState.AWAITING_REVIEW))
    _add(g, "hitl_review", _ask_review)

    g.add_edge(START, "parse")
    g.add_conditional_edges("parse", _next_after_parse)
    _chain(g, "wait_extraction", "hitl_extraction", "a01")
    g.add_conditional_edges("a01", _next_after_analysis)
    g.add_edge("wait_requirements", "hitl_requirements")
    _chain(g, "hitl_requirements", "a02", "a03", "a04", "normalize")
    g.add_conditional_edges("normalize", _next_after_normalization)
    g.add_edge("normalization_failure", "route")
    for name in GENERATORS:
        g.add_edge("generate", name)
    g.add_edge(list(GENERATORS), "generation_result")
    g.add_conditional_edges("generation_result", _next_after_generation)
    g.add_edge("validation_failure", "route")
    for name in REVIEWERS:
        g.add_edge("rules", name)
    _chain(g, list(REVIEWERS), "merge", "route")
    g.add_conditional_edges("route", _next_after_route)
    g.add_edge("a09", "route_router")
    g.add_conditional_edges("route_router", _next_after_route)
    g.add_edge("wait_review", "hitl_review")
    g.add_conditional_edges("hitl_review", _next_after_review)
    _chain(g, "export", "complete", END)
    return g.compile(checkpointer=checkpointer)


def _add(
    g: StateGraph[GraphState], name: str, node: Callable[[GraphState], dict[str, Any]]
) -> None:
    # LangGraph 1.2의 add_node 오버로드는 mypy에서 TypedDict 상태를 노드 입력으로 받지 못한다
    # (일반 TypedDict도 같다). 노드 등록을 여기 한 곳에 모아 이 검사만 건너뛴다.
    g.add_node(name, node)  # type: ignore[call-overload]


def _chain(g: StateGraph[GraphState], first: str | list[str], *rest: str) -> None:
    for start, end in zip((first, *rest[:-1]), rest, strict=True):
        g.add_edge(start, end)


def _noop(state: GraphState) -> Mapping[str, Any]:
    return {}


def _next_after_normalization(state: GraphState) -> str:
    return "normalization_failure" if state.get("normalization_failed") else "generate"


def _sql_blocks_approval(state: GraphState) -> bool:
    return state.get("ddl_validation_status") not in (None, ValidationStatus.PASSED)


def _blocks_approval(state: GraphState) -> bool:
    return (
        bool(state.get("normalization_failed"))
        or _sql_blocks_approval(state)
        or any(f.severity is Severity.CRITICAL for f in state["design"].findings)
    )


def _next_after_generation(state: GraphState) -> str:
    return "validation_failure" if _sql_blocks_approval(state) else "rules"


def _validation_failure(state: GraphState) -> dict[str, Any]:
    # 검증기의 상태 분류를 그대로 소비한다. failed의 RULE-07 지적은 ddl_node가 채운다.
    # 실행하지 않은 후속 리뷰를 실패한 리뷰로 기록하지 않는다.
    return {
        "design": state["design"].evolve(
            findings=state.get("rule_findings", ()), branch_results={}
        ),
        "requires_manual_review": True,
        "failed_branches": (),
        "rejected_findings": (),
        "notes": ({"message": "SQL 검증을 통과하지 못해 사람의 확인이 필요합니다", "payload": {}},),
    }


def _normalization_failure(state: GraphState) -> dict[str, Any]:
    """#15가 변환한 규칙 지적만 사용한다. 실행하지 않은 리뷰 가지를 실패로 만들지 않는다.

    문제 → Finding 변환과 실행 오류 구분은 #15의 책임이다. 차단 지적이 없는 실패는 잘못된
    노드 반환값이므로 실행 오류로 멈춘다. API 승인도 저장된 critical 지적으로 차단된다.
    """
    findings = state.get("rule_findings", ())
    if not any(
        f.source is FindingSource.RULE and f.severity is Severity.CRITICAL for f in findings
    ):
        raise ValueError("정리 실패에는 차단 규칙 지적이 필요합니다")
    return {
        "design": state["design"].evolve(findings=findings, branch_results={}),
        "failed_branches": (),
        "rejected_findings": (),
    }


def _stub_nodes() -> dict[str, Node]:
    stubs: dict[str, Node] = {name: _noop for name in STAGE_STATUS}
    stubs["wait_review"] = _noop  # API의 승인 후보 준비 훅. 기존 체크포인트 노드명 유지
    stubs.update({name: _noop for name in GENERATORS})
    stubs.update({name: _stub_reviewer(name) for name in REVIEWERS})
    stubs["a09"] = lambda state: {"router_stage": None}  # 판단 불가 → HITL 2
    return stubs


def _stub_reviewer(name: str) -> Node:
    def review(state: GraphState) -> Mapping[str, Any]:
        result = BranchResult(branch=name, revision=state["design"].revision, ok=True)
        return {"branches": {name: result}}

    return review


def _as_dict(node: Node) -> Callable[[GraphState], dict[str, Any]]:
    return lambda state: dict(node(state))


def _artifact_design(state: GraphState) -> DesignState:
    design = state["design"]
    if "generated_artifacts" not in state:
        return design  # 기존 체크포인트·직접 주입한 상태도 읽는다
    refs = tuple(
        item["ref"]
        for _, item in sorted(state["generated_artifacts"].items())
        if item["ref"].revision == design.revision
    )
    return design.evolve(artifacts=refs)


def _with_status(node: Node, status: RunState) -> Callable[[GraphState], dict[str, Any]]:
    def run(state: GraphState) -> dict[str, Any]:
        current: GraphState = {**state, "design": _artifact_design(state)}
        update = dict(node(current))
        joined: GraphState = {
            "design": update.get("design", current["design"]),
            "generated_artifacts": {
                **state.get("generated_artifacts", {}),
                **update.get("generated_artifacts", {}),
            },
        }
        update["design"] = _artifact_design(joined).evolve(status=status)
        return update

    return run


def _waiting(status: RunState) -> Callable[[GraphState], dict[str, Any]]:
    """사람 확인 직전·완료 상태. 승인 후 export 결과도 DesignState에 모은다."""
    return lambda state: {"design": _artifact_design(state).evolve(status=status)}


def _next_after_analysis(state: GraphState) -> str:
    """확인할 것이 있을 때만 분석 확인(HITL 1)에서 멈춘다 (ADR-0015 결정 1).

    품질 경고·질문(`quality_issues`)이 있거나, 같은 원문(`source_ref`)에서 요구사항이 2건 이상
    나왔으면(분할) 멈춘다. 분할은 새 계약 칸 없이 A01 결과의 요구사항 수로 센다.
    """
    requirements = state["design"].requirements
    per_source = Counter(r.source_ref for r in requirements)
    flagged = any(r.quality_issues for r in requirements)
    split = any(count > 1 for count in per_source.values())
    return "wait_requirements" if flagged or split else "a02"


def _next_after_parse(state: GraphState) -> str:
    """확인할 블록(`review`·`fail`)이 있을 때만 추출 확인에서 멈춘다 (ADR-0015 결정 1)."""
    checked = (ExtractionStatus.REVIEW, ExtractionStatus.FAIL)
    blocks = state["design"].source_requirements
    return "wait_extraction" if any(b.extraction_status in checked for b in blocks) else "a01"


def _ask_extraction(state: GraphState) -> dict[str, Any]:
    """추출 확인 답을 블록 결정으로 남긴다. 판정과 맞지 않는 답은 resume API가 422로 막는다 (#120).

    중단(`confirmed=false`)은 API가 실행을 `cancelled`로 끝내므로 여기까지 오지 않는다.
    """
    answer = ExtractionResponse.model_validate(interrupt({"kind": "extraction"}))
    design = state["design"]
    blocks = _decide_blocks(design.source_requirements, answer)
    if not any(b.analysable for b in blocks):
        raise ExtractionFailedError(
            "분석할 요구사항이 없어요. 요구사항을 적은 뒤 다시 올려 주세요.",
            "추출 확인에서 모든 원문을 제외했거나, 남은 원문에 요구사항 문장이 없어요.",
        )
    return {
        "design": design.evolve(source_requirements=blocks, status=RunState.ANALYSING),
        "notes": _related_warnings(blocks),
    }


def _related_warnings(blocks: tuple[SourceRequirement, ...]) -> tuple[RunNote, ...]:
    """제외한 원문의 ID가 남은 원문의 「관련 요구사항」에 나오면 경고를 남긴다 (ADR-0015 결정 5).

    제외는 막지 않는다. ID는 앞뒤가 다른 글자·숫자·`-`가 아닐 때만 같은 ID로 본다
    (「SFR-0031」 ≠ 「SFR-003」).
    """
    excluded = [b for b in blocks if b.user_decision is UserDecision.EXCLUDED and b.source_id]
    remaining = [
        b
        for b in blocks
        if b.user_decision is not UserDecision.EXCLUDED and b.source_related_requirements
    ]
    notes: list[RunNote] = []
    for block in excluded:
        same_id = re.compile(rf"(?<![\w-]){re.escape(block.source_id or '')}(?![\w-])")
        related = [
            r.block_id for r in remaining if same_id.search(r.source_related_requirements or "")
        ]
        if related:
            payload = {
                "warning": "excluded_related",
                "block_id": block.block_id,
                "source_id": block.source_id,
                "related_block_ids": related,
            }
            notes.append(RunNote(message=_EXCLUDED_RELATED, payload=payload))
    return tuple(notes)


_EXCLUDED_RELATED = "제외한 원문을 관련 요구사항으로 적은 원문이 있습니다"


def _decide_blocks(
    blocks: tuple[SourceRequirement, ...], answer: ExtractionResponse
) -> tuple[SourceRequirement, ...]:
    """제외 목록의 블록은 `excluded`, 목록에 없는 `review` 블록은 `confirmed`로 둔다 (ADR-0015).

    빈 사유(`""`)는 사유 없음(None)으로 넣는다. 계약의 `excluded_reason`은 빈 문자열을 받지 않는다.
    """
    reasons = {b.block_id: b.reason or None for b in answer.excluded_blocks}

    def decided(block: SourceRequirement) -> SourceRequirement:
        if block.block_id in reasons:
            return block.evolve(
                user_decision=UserDecision.EXCLUDED, excluded_reason=reasons[block.block_id]
            )
        if block.extraction_status is ExtractionStatus.REVIEW:
            return block.evolve(user_decision=UserDecision.CONFIRMED)
        return block

    return tuple(decided(b) for b in blocks)


def _ask_requirements(state: GraphState) -> dict[str, Any]:
    answer = interrupt({"kind": "requirements"})
    design = state["design"]
    requirements = _answered(design.requirements, RequirementsResponse.model_validate(answer))
    design = design.evolve(requirements=requirements, status=RunState.DESIGNING)
    return {"requirements_answer": answer, "design": design}


def _answered(
    requirements: tuple[Requirement, ...], response: RequirementsResponse
) -> tuple[Requirement, ...]:
    """분석 확인 답을 반영한다 (docs/06 resume). 답이 없는 요구사항은 그대로(keep) 둔다.

    - edit: 문장 하나로 `text`를 바꾼다. A01이 낸 `draft_text`는 그대로 둔다 (docs/05).
    - split: 문장 2개 이상. 첫 조각은 원래 ID, 나머지는 이어지는 새 ID다. 원문 연결·분류는
      부모 값을 쓰고, `parent_id`는 A01 분할처럼 비운다(원문으로 잇는다).
      경고 기록은 원래 ID에 남긴다.
    """
    answers = response.answers_for(r.id for r in requirements)
    next_number = max((_number(r.id) for r in requirements), default=0) + 1
    result: list[Requirement] = []
    for req in requirements:
        answer = answers.get(req.id)
        if answer is None or answer.action == "keep":
            result.append(req)
        elif answer.action == "edit":
            result.append(req.evolve(text=answer.texts[0]))
        else:
            first, *rest = answer.texts
            result.append(req.evolve(text=first))
            for offset, text in enumerate(rest):
                new_id = f"REQ-{next_number + offset:02d}"
                result.append(req.evolve(id=new_id, text=text, quality_issues=()))
            next_number += len(rest)
    return tuple(result)


def _number(req_id: str) -> int:
    return int(req_id.split("-", 1)[1])


def _ask_review(state: GraphState) -> dict[str, Any]:
    response = interrupt(
        {
            "kind": "review",
            "hitl_reason": state.get("hitl_reason"),
            # 실패하거나 빠진 리뷰 가지. 비어 있지 않으면 불완전 검토다 (TC-F14)
            "failed_branches": list(state.get("failed_branches", ())),
            "rejected_findings": list(state.get("rejected_findings", ())),
            "router_decision": state.get("router_decision"),
        }
    )
    decision = response.get("decision")
    update: dict[str, Any] = {"review_response": response, "revising": decision == "revise"}
    if decision == "approve" and _blocks_approval(state):
        return update  # API 밖에서 직접 재개해도 차단 규칙 지적을 승인·내보내기 할 수 없다
    if decision in REVIEW_STATUS:
        update["design"] = state["design"].evolve(status=REVIEW_STATUS[decision])
    return update


def _merge(state: GraphState) -> dict[str, Any]:
    """리뷰 가지 합류·근거 확인·지적 병합 (#18 `merge_review`).

    `branches`는 가지 이름별로 누적되므로, 이번 revision에 결과를 내지 못한 가지의 이전 결과가
    남아 있을 수 있다. 현재 revision 결과만 합류하고, 빠진 가지는 `merge_review`가 실패로 남긴다
    (04 문서 "지적 확정 절차" 합류, TC-F14). 이전 결과로 채우지 않는다.
    """
    design = state["design"]
    current = {
        name: result
        for name, result in state.get("branches", {}).items()
        if result.revision == design.revision
    }
    results = [current[name] for name in REVIEWERS if name in current]
    merged = merge_review(design, results, REVIEWERS, rule_findings=state.get("rule_findings", ()))
    joined = {name: current[name] for name in (*GENERATORS, *REVIEWERS) if name in current}
    versions = design.versions
    used = state.get("branch_versions", {})
    versions = versions.evolve(
        prompt_versions={**versions.prompt_versions, **{k: p for k, (p, _) in used.items()}},
        model_names={**versions.model_names, **{k: m for k, (_, m) in used.items()}},
    )
    return {
        "design": design.evolve(findings=merged.findings, branch_results=joined, versions=versions),
        "failed_branches": merged.failed_branches,
        "rejected_findings": tuple(
            {"finding_id": r.finding.id, "reviewer_id": r.finding.reviewer_id, "reason": r.reason}
            for r in merged.rejected
        ),
    }


def _route(max_rework: int) -> Callable[[GraphState], dict[str, Any]]:
    def route(state: GraphState) -> dict[str, Any]:
        findings = state["design"].findings
        previous = state.get("fingerprints", ())
        if state.get("requires_manual_review"):
            decision = ReworkDecision(ReworkAction.HITL, hitl_reason=HitlReason.MANUAL)
        else:
            decision = decide_rework(
                findings,
                rework_count=state.get("rework_count", 0),
                max_rework=max_rework,
                previous_fingerprints=frozenset(previous),
            )
        seen = tuple(dict.fromkeys([*previous, *(f.fingerprint for f in findings)]))
        return {**_apply(state, decision, counted=True), "fingerprints": seen, "revising": False}

    return route


def _route_router(state: GraphState) -> dict[str, Any]:
    """A09 답으로 복귀 단계를 정한다. 답이 없으면 HITL 2 (판단 불가)."""
    router_stage = state.get("router_stage")
    if state.get("revising"):
        if router_stage is None:
            return _apply(
                state, ReworkDecision(ReworkAction.HITL, hitl_reason=HitlReason.UNDECIDED)
            )
        return _apply(state, ReworkDecision(ReworkAction.REWORK, router_stage), counted=False)
    pending = ReworkDecision(ReworkAction.ASK_ROUTER, target_stage=state.get("next_stage"))
    return _apply(state, resolve_with_router(pending, router_stage), counted=True)


def _apply(state: GraphState, decision: ReworkDecision, *, counted: bool = True) -> dict[str, Any]:
    """결정을 상태에 적는다. 재작업이면 revision·iteration을 올리고 복귀 단계를 남긴다."""
    update: dict[str, Any] = {
        "action": decision.action,
        "next_stage": decision.target_stage,
        "hitl_reason": decision.hitl_reason,
    }
    if decision.action is ReworkAction.ASK_ROUTER:
        update["router_stage"] = None
        update["unrouted"] = decision.unrouted
    elif decision.action is ReworkAction.REWORK:
        design = state["design"]
        update["design"] = design.evolve(
            revision=design.revision + 1, iteration=design.iteration + 1, normalized=None
        )
        update["rework_count"] = state.get("rework_count", 0) + (1 if counted else 0)
        update.update(
            normalization_failed=False, requires_manual_review=False, rule_findings=(),
            rejected_findings=(),
            ddl_validation_status=None,
        )  # fmt: skip
    return update


def _next_after_route(state: GraphState) -> str:
    action = state.get("action")
    if action is ReworkAction.ASK_ROUTER:
        return "a09"
    stage = state.get("next_stage")
    if action is ReworkAction.REWORK and stage is not None:
        return STAGE_NODES[stage]
    return "wait_review"  # 재작업할 지적 없음, 또는 사람에게 넘김


def _next_after_review(state: GraphState) -> str:
    decision = state.get("review_response", {}).get("decision")
    if decision == "approve" and not _blocks_approval(state):
        return "export"
    if decision == "revise":
        return "a09"
    return "wait_review"  # 보류: 내보내지 않고 같은 확인을 다시 기다린다
