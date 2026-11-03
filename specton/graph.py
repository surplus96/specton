"""설계 그래프 (03 문서 "실행 흐름", #17). 통합 담당(R1)만 수정한다.

입력 → A01 → HITL 1 → A02 → A03 → A04 → 모델 정리 → 생성(병렬) → 규칙 → 검토(병렬) → 병합
→ 재작업 판단 → HITL 2 → 내보내기 순서로 잇는다.
- 노드는 상태만 반환하고 DB에 쓰지 않는다. 앱 저장은 실행기가 노드가 끝난 뒤 한다 (ADR-0012).
- 사람 확인(interrupt)은 LLM을 부르지 않는 전용 노드에서만 한다.
  재개하면 그 노드를 처음부터 다시 돌기 때문이다.
- 지금은 빈 노드(stub)로 잇는다. 에이전트 노드는 담당 이슈가 끝나면 `nodes`로 넘겨 바꾼다.
"""

from collections.abc import Callable, Mapping
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from specton.config import get_settings
from specton.contracts import BranchResult, DesignState, Finding, RunState
from specton.contracts.base import TargetStage
from specton.review.merge import merge_review
from specton.review.rework import (
    HitlReason,
    ReworkAction,
    ReworkDecision,
    decide_rework,
    resolve_with_router,
)

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


def _merge_branches(
    old: Mapping[str, BranchResult], new: Mapping[str, BranchResult]
) -> dict[str, BranchResult]:
    """병렬 가지 결과는 가지 이름별로 모은다. 재작업 때는 같은 이름의 새 결과로 바뀐다."""
    return {**old, **new}


class GraphState(TypedDict, total=False):
    design: DesignState
    branches: Annotated[dict[str, BranchResult], _merge_branches]
    rule_findings: tuple[Finding, ...]  # 규칙 검사(#15) 결과
    rework_count: int  # 자동 재작업 횟수 (사람의 수정 요청은 세지 않는다)
    fingerprints: tuple[str, ...]  # 지난 반복의 지적 지문
    action: ReworkAction | None  # 재작업 판단 결과
    next_stage: TargetStage | None
    hitl_reason: HitlReason | None
    router_stage: TargetStage | None  # A09 답
    revising: bool  # HITL 2의 수정 요청으로 A09에 왔는지
    requirements_answer: dict[str, Any]
    review_response: dict[str, Any]


Node = Callable[[GraphState], Mapping[str, Any]]


def initial_state(design: DesignState) -> GraphState:
    return GraphState(design=design, branches={}, rule_findings=(), rework_count=0, fingerprints=())


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
    _add(g, "wait_requirements", _waiting(RunState.AWAITING_REQUIREMENTS))
    _add(g, "hitl_requirements", _ask_requirements)
    _add(g, "generate", _with_status(_noop, RunState.GENERATING))
    _add(g, "merge", _merge)
    _add(g, "route", _route(limit))
    _add(g, "route_router", _route_router)
    _add(g, "wait_review", _waiting(RunState.AWAITING_REVIEW))
    _add(g, "hitl_review", _ask_review)

    _chain(g, START, "parse", "a01", "wait_requirements", "hitl_requirements")
    _chain(g, "hitl_requirements", "a02", "a03", "a04", "normalize", "generate")
    for name in GENERATORS:
        g.add_edge("generate", name)
    g.add_edge(list(GENERATORS), "rules")
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


def _stub_nodes() -> dict[str, Node]:
    stubs: dict[str, Node] = {name: _noop for name in STAGE_STATUS}
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


def _with_status(node: Node, status: RunState) -> Callable[[GraphState], dict[str, Any]]:
    def run(state: GraphState) -> dict[str, Any]:
        update = dict(node(state))
        design: DesignState = update.get("design", state["design"])
        update["design"] = design.evolve(status=status)
        return update

    return run


def _waiting(status: RunState) -> Callable[[GraphState], dict[str, Any]]:
    """상태만 바꾸는 노드. 사람 확인 직전에도 쓴다.

    interrupt 노드는 반환 전에 멈춰 상태를 남기지 못하므로 따로 둔다.
    """
    return lambda state: {"design": state["design"].evolve(status=status)}


def _ask_requirements(state: GraphState) -> dict[str, Any]:
    answer = interrupt({"kind": "requirements"})
    design = state["design"].evolve(status=RunState.DESIGNING)
    return {"requirements_answer": answer, "design": design}


def _ask_review(state: GraphState) -> dict[str, Any]:
    response = interrupt({"kind": "review", "hitl_reason": state.get("hitl_reason")})
    decision = response.get("decision")
    update: dict[str, Any] = {"review_response": response, "revising": decision == "revise"}
    if decision in REVIEW_STATUS:
        update["design"] = state["design"].evolve(status=REVIEW_STATUS[decision])
    return update


def _merge(state: GraphState) -> dict[str, Any]:
    """리뷰 가지 합류·근거 확인·지적 병합 (#18 `merge_review`)."""
    design = state["design"]
    branches = state.get("branches", {})
    results = [branches[name] for name in REVIEWERS if name in branches]
    merged = merge_review(design, results, REVIEWERS, rule_findings=state.get("rule_findings", ()))
    joined = {name: branches[name] for name in (*GENERATORS, *REVIEWERS) if name in branches}
    return {"design": design.evolve(findings=merged.findings, branch_results=joined)}


def _route(max_rework: int) -> Callable[[GraphState], dict[str, Any]]:
    def route(state: GraphState) -> dict[str, Any]:
        findings = state["design"].findings
        previous = state.get("fingerprints", ())
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
    elif decision.action is ReworkAction.REWORK:
        design = state["design"]
        update["design"] = design.evolve(
            revision=design.revision + 1, iteration=design.iteration + 1
        )
        update["rework_count"] = state.get("rework_count", 0) + (1 if counted else 0)
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
    if decision == "approve":
        return "export"
    if decision == "revise":
        return "a09"
    return "wait_review"  # 보류: 내보내지 않고 같은 확인을 다시 기다린다
