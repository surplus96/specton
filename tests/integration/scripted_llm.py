"""고정 규칙으로 답하는 LLM (#19 기본 흐름 검증, 실제 OpenAI 호출 없음).

실제 노드(A01~A04·검토·A09)는 그대로 두고 Transport만 바꾼다. 검증·재요청은 진짜 `LLMClient`가 한다.
응답은 요청에 담긴 입력(JSON)을 읽어 항상 같은 규칙으로 만든다. 블록·요구사항·기능 ID는 실행마다
코드가 붙이므로 응답에 적어 두지 않고 입력에서 가져온다.

- A01: 원문 블록마다 FR 요구사항 하나 (문장은 원문 그대로). 첫 요구사항에 확인 질문 하나
- A02: 요구사항마다 기능 하나 (우선순위 미정)
- A03: 재고 팩에서 물리명이 풀리는 엔티티 4개(창고·품목·입고·입고내역). 팩 용어 속성은 입력의
  팩 용어 타입을 그대로 쓴다. 첫 기능은 모든 엔티티를 C·R·U·D, 나머지는 품목을 R
- A04: 창고→입고, 입고→입고내역(식별), 품목→입고내역. 근거는 첫 요구사항 문장 인용
- 검토(combined·parallel): 지적 없음
- A09(수정 요청 뒤): 데이터 모델 단계로 되돌림

`calls`에 단계별 호출 수를 남긴다.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from functools import cache
from typing import Any

from pydantic import BaseModel

from specton.agent_nodes import design_nodes, review_nodes, router_node
from specton.config import Settings
from specton.graph import REVIEWERS, Node
from specton.llm.client import LLMClient, RawReply
from specton.llm.types import LLMRequest
from specton.nodes.a01_requirements import A01Output
from specton.nodes.a02_functions import A02Output
from specton.nodes.a03_entities import A03Output
from specton.nodes.a04_relationships import A04Output
from specton.nodes.a09_rework_router import A09Output
from specton.nodes.common import unwrap_data
from specton.review.reviewer import CombinedReviewOutput, ReviewOutput

# (엔티티 이름, [(속성 이름, 키, 팩 용어가 아닐 때 쓸 타입)])
ENTITIES: tuple[tuple[str, tuple[tuple[str, bool, dict[str, Any]], ...]], ...] = (
    ("창고", (("창고코드", True, {}), ("창고명", False, {}))),
    ("품목", (("품목코드", True, {}), ("품목명", False, {}))),
    ("입고", (
        ("입고번호", True, {"data_type": "varchar", "length": 20}),
        ("입고일자", False, {"data_type": "date"}),
    )),
    ("입고내역", (
        ("일련번호", True, {"data_type": "integer"}),
        ("입고수량", False, {"data_type": "numeric", "precision": 12, "scale": 3}),
    )),
)  # fmt: skip
RELATIONSHIPS = (
    ("창고", "입고", False),
    ("입고", "입고내역", True),
    ("품목", "입고내역", False),
)


class ScriptedTransport:
    """출력 모델 종류를 보고 고정 규칙으로 답한다."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    def send(self, request: LLMRequest, output_model: type[BaseModel]) -> RawReply:
        data = json.loads(unwrap_data(request.messages[-1].content))
        self.calls[request.stage] += 1
        for base, answer in _ANSWERS:
            if issubclass(output_model, base):
                return RawReply(text=json.dumps(answer(data), ensure_ascii=False))
        raise AssertionError(f"준비하지 않은 출력 모델: {output_model.__name__}")


def _a01(data: Mapping[str, Any]) -> dict[str, Any]:
    """첫 요구사항에만 확인 질문을 붙여 분석 확인(HITL 1)에서 멈추게 한다."""
    question = {
        "kind": "missing_value",
        "message": "시험용 확인 질문",
        "question": "이 요구사항을 그대로 둘까요?",
    }
    return {
        "requirements": [
            {
                "source_block_ids": [b["block_id"]],
                "text": b["text"],
                "type": "FR",
                "quality_issues": [question] if i == 0 else [],
            }
            for i, b in enumerate(data["source_blocks"])
        ]
    }


def _a02(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "functions": [
            {"name": f"{r['id']} 기능", "description": r["text"], "req_ids": [r["id"]]}
            for r in data["requirements"]
        ]
    }


def _a03(data: Mapping[str, Any]) -> dict[str, Any]:
    terms = {t["term"]: t for t in data["pack"]["terms"]}
    first_req = data["requirements"][0]["id"]

    def attribute(name: str, key: bool, fallback: Mapping[str, Any]) -> dict[str, Any]:
        term = terms.get(name)
        typed = (
            {k: term[k] for k in ("data_type", "length", "precision", "scale") if k in term}
            if term
            else dict(fallback)
        )
        return {
            "name": name,
            **typed,
            "is_key": key,
            "nullable": not key,
            "req_ids": [first_req],
        }

    functions = [f["id"] for f in data["functions"]]
    ops = [
        {"function_id": functions[0], "entity_name": name, "operations": ["C", "R", "U", "D"]}
        for name, _ in ENTITIES
    ] + [{"function_id": f, "entity_name": "품목", "operations": ["R"]} for f in functions[1:]]
    return {
        "entities": [
            {
                "name": name,
                "description": f"{name} 정보",
                "attributes": [attribute(*a) for a in attrs],
                "req_ids": [first_req],
            }
            for name, attrs in ENTITIES
        ],
        "entity_ops": ops,
    }


def _a04(data: Mapping[str, Any]) -> dict[str, Any]:
    quoted = next(r for r in data["requirements"] if '"' not in r["text"])
    return {
        "relationships": [
            {
                "parent_name": parent,
                "child_name": child,
                "cardinality": "1:N",
                "optional": False,
                "identifying": identifying,
                "rationale": f'"{quoted["text"]}" 시험용 고정 관계다.',
                "req_ids": [quoted["id"]],
            }
            for parent, child, identifying in RELATIONSHIPS
        ]
    }


def _combined(data: Mapping[str, Any]) -> dict[str, Any]:
    return {"perspectives": [{"reviewer_id": r, "findings": []} for r in REVIEWERS]}


def _review(data: Mapping[str, Any]) -> dict[str, Any]:
    return {"findings": []}


def _a09(data: Mapping[str, Any]) -> dict[str, Any]:
    return {"decision": "data_model", "rationale": "수정 요청이 데이터 모델에 대한 것이다."}


_ANSWERS: tuple[tuple[type[BaseModel], Callable[[Mapping[str, Any]], dict[str, Any]]], ...] = (
    (A01Output, _a01),
    (A02Output, _a02),
    (A03Output, _a03),
    (A04Output, _a04),
    (CombinedReviewOutput, _combined),
    (ReviewOutput, _review),
    (A09Output, _a09),
)


def scripted_agent_nodes(settings: Settings, transport: ScriptedTransport) -> dict[str, Node]:
    """`openai_agent_nodes`와 같은 노드를 고정 규칙 LLM으로 만든다."""
    get_client = cache(
        lambda: LLMClient(transport, max_structured_retries=settings.max_structured_retries)
    )
    return {
        **design_nodes(get_client, settings),
        **review_nodes(get_client, settings),
        "a09": router_node(get_client, settings),
    }
