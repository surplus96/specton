"""설계 에이전트(A01~A04)를 그래프 노드로 잇는다 (#17). 통합 담당(R1)만 수정한다.

- 노드는 `run(client, design, settings, pack=...)`을 부르고 결과를 상태에 반영한다.
  호출한 에이전트의 프롬프트 버전과 모델은 `DesignState.versions`에 남긴다 (재현용).
- 팩은 실행마다 다르므로 실행기가 첫 상태의 `versions.pack_id`에 넣은 값을 쓴다.
- client는 노드가 처음 LLM을 부를 때 만든다. API 키가 없어도 서버는 뜨고,
  실행만 `LLM_UNAVAILABLE`로 실패한다.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from specton.config import Settings
from specton.contracts import DesignState
from specton.graph import GraphState, Node
from specton.llm.client import LLMClient
from specton.llm.openai_transport import openai_client
from specton.nodes import a01_requirements, a02_functions, a03_entities, a04_relationships
from specton.nodes.a03_entities import A03Result
from specton.nodes.common import NodeRun


@dataclass(frozen=True)
class _Agent:
    agent_id: str
    prompt_version: str
    run: Callable[..., NodeRun[Any]]
    apply: Callable[[DesignState, Any], DesignState]


def _apply_entities(design: DesignState, result: A03Result) -> DesignState:
    return design.evolve(entities=result.entities, functions=result.functions)


# 그래프 노드 이름 → 에이전트. 모두 설계 모델(role="design")을 쓴다.
_DESIGN_AGENTS: Mapping[str, _Agent] = {
    "a01": _Agent(
        "A01",
        a01_requirements.PROMPT_VERSION,
        a01_requirements.run,
        lambda design, output: design.evolve(requirements=output),
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


def openai_design_nodes(settings: Settings) -> dict[str, Node]:
    """실제 OpenAI client를 쓰는 노드. client는 첫 호출 때 한 번 만든다."""
    return design_nodes(cache(lambda: openai_client(settings)), settings)


def _design_node(agent: _Agent, get_client: Callable[[], LLMClient], settings: Settings) -> Node:
    def node(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        pack = design.versions.pack_id
        if pack is None:
            raise ValueError(f"{agent.agent_id}: 실행의 팩이 정해지지 않았습니다")
        result = agent.run(get_client(), design, settings, pack=pack)
        recorded = design.versions
        versions = recorded.evolve(
            prompt_versions={**recorded.prompt_versions, agent.agent_id: agent.prompt_version},
            model_names={**recorded.model_names, agent.agent_id: settings.design_model},
        )
        return {"design": agent.apply(design, result.output).evolve(versions=versions)}

    return node
