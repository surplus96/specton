"""에이전트(A01~A09)를 그래프 노드로 잇는다 (#17). 통합 담당(R1)만 수정한다.

- 설계 노드(A01~A04)는 `run(client, design, settings, pack=...)`을 부르고 결과를 상태에 반영한다.
  호출한 에이전트의 프롬프트 버전과 모델은 `DesignState.versions`에 남긴다 (재현용).
- 검토 노드(A05~A08)는 설정형 리뷰어(`specton.review.reviewer`)로 관점 하나를 검토해 가지 결과를
  낸다. 병렬 가지라 design을 쓰지 않고, 버전은 `branch_versions`로 넘겨 합류에서 기록한다.
  `review_mode=combined`면 첫 관점 노드가 모든 관점을 한 번에 검토하고 나머지 노드는 비운다.
- 재작업 판단 노드(A09)는 코드가 단계를 정하지 못한 지적이나 HITL 2 수정 요청을 넘긴다.
- 팩은 실행마다 다르므로 실행기가 첫 상태의 `versions.pack_id`에 넣은 값을 쓴다.
- client는 노드가 처음 LLM을 부를 때 만든다. API 키가 없어도 서버는 뜨고,
  실행만 `LLM_UNAVAILABLE`로 실패한다.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from langgraph.config import get_stream_writer

from specton.config import Settings
from specton.contracts import DesignState
from specton.graph import REVIEWERS, GraphState, Node
from specton.llm.client import LLMClient
from specton.llm.errors import LLMBudgetExceededError, LLMError
from specton.llm.openai_transport import openai_client
from specton.llm.types import CallRecord
from specton.nodes import (
    a01_requirements,
    a02_functions,
    a03_entities,
    a04_relationships,
    a09_rework_router,
)
from specton.nodes.a03_entities import A03Result
from specton.nodes.common import NodeRun
from specton.review.perspective import Perspective, load_perspectives
from specton.review.reviewer import ReviewRun, review_combined, review_perspective

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Agent:
    agent_id: str
    prompt_version: str
    run: Callable[..., NodeRun[Any]]
    apply: Callable[[DesignState, Any], DesignState]
    options: Callable[[DesignState], dict[str, Any]] = lambda design: {}  # run()에 더 넘길 값


def _apply_entities(design: DesignState, result: A03Result) -> DesignState:
    return design.evolve(entities=result.entities, functions=result.functions)


def _analysis_options(design: DesignState) -> dict[str, Any]:
    """다시 분석하면(요구사항 단계 재작업·수정 요청) 분석 버전을 올린다."""
    previous = max((r.analysis_version for r in design.requirements), default=0)
    return {"analysis_version": previous + 1}


# 그래프 노드 이름 → 에이전트. 모두 설계 모델(role="design")을 쓴다.
_DESIGN_AGENTS: Mapping[str, _Agent] = {
    "a01": _Agent(
        "A01",
        a01_requirements.PROMPT_VERSION,
        a01_requirements.run,
        lambda design, output: design.evolve(requirements=output),
        _analysis_options,
    ),
    "a02": _Agent(
        "A02",
        a02_functions.PROMPT_VERSION,
        a02_functions.run,
        lambda design, output: design.evolve(functions=output),
    ),
    "a03": _Agent("A03", a03_entities.PROMPT_VERSION, a03_entities.run, _apply_entities),
    "a04": _Agent(
        "A04",
        a04_relationships.PROMPT_VERSION,
        a04_relationships.run,
        lambda design, output: design.evolve(relationships=output),
    ),
}


def design_nodes(get_client: Callable[[], LLMClient], settings: Settings) -> dict[str, Node]:
    """A01~A04 그래프 노드. `get_client`는 노드가 LLM을 부를 때마다 호출한다."""
    return {
        name: _design_node(agent, get_client, settings) for name, agent in _DESIGN_AGENTS.items()
    }


def review_nodes(
    get_client: Callable[[], LLMClient],
    settings: Settings,
    perspectives: Sequence[Perspective] | None = None,
) -> dict[str, Node]:
    """검토 노드 A05~A08. 관점 설정 파일은 그래프의 검토 가지와 하나씩 맞아야 한다."""
    loaded = tuple(perspectives) if perspectives is not None else load_perspectives()
    by_id = {p.reviewer_id: p for p in loaded}
    if set(by_id) != set(REVIEWERS):
        missing = sorted(set(REVIEWERS) ^ set(by_id))
        raise ValueError(f"관점 설정과 검토 가지가 다릅니다: {', '.join(missing)}")
    ordered = tuple(by_id[r] for r in REVIEWERS)
    if settings.review_mode == "combined":
        nodes: dict[str, Node] = {r: _skip for r in REVIEWERS[1:]}
        return {REVIEWERS[0]: _combined_node(ordered, get_client, settings), **nodes}
    return {p.reviewer_id: _reviewer_node(p, get_client, settings) for p in ordered}


def router_node(get_client: Callable[[], LLMClient], settings: Settings) -> Node:
    """재작업 판단 노드 A09. 답이 없거나 호출이 실패하면 `router_stage=None`(HITL 2)."""

    def node(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        revising = state.get("revising", False)
        feedback = state.get("review_response", {}).get("feedback", "") if revising else ""
        findings = () if revising else state.get("unrouted", ())
        if not feedback and not findings:
            return {"router_stage": None}  # 판단할 내용이 없다: 사람에게 다시 묻는다
        result = a09_rework_router.run(
            get_client(),
            design,
            settings,
            pack=_pack(design, "A09"),
            findings=findings,
            feedback=feedback or None,
            token_budget=_remaining(state, settings, "A09"),
        )
        versions = _recorded(design, {"A09": (a09_rework_router.PROMPT_VERSION, _review(settings))})
        return {
            "router_stage": result.output.stage,
            "design": design.evolve(versions=versions),
            "tokens_used": _used(design.run_id, result.calls),
            "call_summaries": {"A09": tuple(c.model_dump(mode="json") for c in result.calls)},
        }

    return node


def openai_agent_nodes(settings: Settings) -> dict[str, Node]:
    """실제 OpenAI client를 쓰는 노드 A01~A09. client는 첫 호출 때 한 번 만든다."""
    get_client = cache(lambda: openai_client(settings))
    return {
        **design_nodes(get_client, settings),
        **review_nodes(get_client, settings),
        "a09": router_node(get_client, settings),
    }


def _design_node(agent: _Agent, get_client: Callable[[], LLMClient], settings: Settings) -> Node:
    def node(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        try:
            result = agent.run(
                get_client(),
                design,
                settings,
                pack=_pack(design, agent.agent_id),
                token_budget=_remaining(state, settings, agent.agent_id),
                **agent.options(design),
            )
        except LLMError as exc:
            _used(design.run_id, exc.calls)  # 실패까지의 호출도 남긴다
            raise
        versions = _recorded(
            design, {agent.agent_id: (agent.prompt_version, settings.design_model)}
        )
        return {
            "design": agent.apply(design, result.output).evolve(versions=versions),
            "tokens_used": _used(design.run_id, result.calls),
            "call_summaries": {
                agent.agent_id: tuple(c.model_dump(mode="json") for c in result.calls)
            },
        }

    return node


def _reviewer_node(
    perspective: Perspective, get_client: Callable[[], LLMClient], settings: Settings
) -> Node:
    def node(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        pack = _pack(design, perspective.reviewer_id)
        budget = _remaining(state, settings, perspective.reviewer_id)
        run = review_perspective(
            get_client(), perspective, design, settings, pack=pack, token_budget=budget
        )
        return _branch_update(run, (perspective,), settings, design.run_id)

    return node


def _combined_node(
    perspectives: tuple[Perspective, ...], get_client: Callable[[], LLMClient], settings: Settings
) -> Node:
    def node(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        pack = _pack(design, "REVIEW")
        budget = _remaining(state, settings, "REVIEW")
        run = review_combined(
            get_client(), perspectives, design, settings, pack=pack, token_budget=budget
        )
        return _branch_update(run, perspectives, settings, design.run_id)

    return node


def _skip(state: GraphState) -> Mapping[str, Any]:
    """combined 방식에서 첫 관점 노드가 이미 검토한 관점."""
    return {}


def _branch_update(
    run: ReviewRun, perspectives: Sequence[Perspective], settings: Settings, run_id: str
) -> dict[str, Any]:
    return {
        "branches": {r.branch: r for r in run.results},
        "branch_versions": {
            p.reviewer_id: (p.prompt_version, _review(settings)) for p in perspectives
        },
        "tokens_used": _used(run_id, run.calls),
        "call_summaries": {
            p.reviewer_id: tuple(c.model_dump(mode="json") for c in run.calls)
            for p in perspectives[:1]
        },
    }


def _remaining(state: GraphState, settings: Settings, agent_id: str) -> int:
    """이번 실행에 남은 토큰 예산 (`max_tokens_per_run`). 다 썼으면 부르지 않고 실패한다."""
    remaining = settings.max_tokens_per_run - state.get("tokens_used", 0)
    if remaining <= 0:
        raise LLMBudgetExceededError(
            f"{agent_id}: 실행 토큰 예산 {settings.max_tokens_per_run}을 다 썼습니다"
        )
    return remaining


def _used(run_id: str, calls: Sequence[CallRecord]) -> int:
    """호출 기록을 한 줄씩 로그로 남기고 쓴 토큰을 돌려준다 (docs/13 단계별 비용 확인).

    기록에는 단계·프롬프트 버전·모델·시도·결과·토큰·시간만 있다. 원문·키는 없다 (docs/04).
    """
    for c in calls:
        try:
            writer = get_stream_writer()
        except RuntimeError:
            writer = None  # 단위 호출처럼 그래프 실행 문맥이 없을 수 있다
        if writer is not None:
            writer({"llm_call": c.model_dump(mode="json")})
        logger.info(
            "LLM 호출 run=%s stage=%s prompt=%s model=%s attempt=%d outcome=%s "
            "input_tokens=%d output_tokens=%d duration_ms=%d",
            run_id, c.stage, c.prompt_version, c.model, c.attempt, c.outcome,
            c.input_tokens, c.output_tokens, c.duration_ms,
        )  # fmt: skip
    return sum(c.input_tokens + c.output_tokens for c in calls)


def _pack(design: DesignState, agent_id: str) -> str:
    pack = design.versions.pack_id
    if pack is None:
        raise ValueError(f"{agent_id}: 실행의 팩이 정해지지 않았습니다")
    return pack


def _recorded(design: DesignState, used: Mapping[str, tuple[str, str]]) -> Any:
    """호출한 에이전트의 (프롬프트 버전, 모델)을 기록한 새 VersionInfo."""
    recorded = design.versions
    return recorded.evolve(
        prompt_versions={**recorded.prompt_versions, **{k: p for k, (p, _) in used.items()}},
        model_names={**recorded.model_names, **{k: m for k, (_, m) in used.items()}},
    )


def _review(settings: Settings) -> str:
    return settings.review_model
