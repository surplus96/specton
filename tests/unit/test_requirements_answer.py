"""#17 분석 확인(HITL 1) 답을 요구사항에 반영한다: keep·edit·split (docs/06 resume, REQ-05)."""

from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.contracts import DesignState, Requirement
from specton.contracts.requirements import QualityIssue
from specton.graph import GraphState, Node, build_graph, initial_state

AMBIGUOUS = QualityIssue(kind="ambiguous", message="취소 사유를 어디에 남기는지 없습니다")


def _req(n: int, text: str, **extra: Any) -> Requirement:
    return Requirement.model_validate(
        {
            "id": f"REQ-{n:02d}",
            "source_id": f"SFR-{n:03d}",
            "source_ref": {"file_format": "csv", "row": n + 1},
            "text": text,
            "draft_text": text,
            "source_text": text,
            "source_acceptance_level": "필수",
            "type": "FR",
            "analysis_version": 1,
            **extra,
        }
    )


REQS = (
    _req(1, "입고를 등록한다"),
    _req(2, "출고를 등록한다"),
    _req(3, "주문을 취소하고 사유를 저장한다", quality_issues=[AMBIGUOUS]),
)


class _Run:
    """A01 자리에 고정 요구사항을 넣고, A02가 받은 요구사항을 남기는 그래프."""

    def __init__(self) -> None:
        self.designed: list[tuple[Requirement, ...]] = []
        self.config = {"configurable": {"thread_id": "run-1"}}

        def a01(state: GraphState) -> Mapping[str, Any]:
            return {"design": state["design"].evolve(requirements=REQS)}

        def a02(state: GraphState) -> Mapping[str, Any]:
            self.designed.append(state["design"].requirements)
            return {}

        nodes: dict[str, Node] = {"a01": a01, "a02": a02}
        self.graph = build_graph(nodes, checkpointer=InMemorySaver())
        self.graph.invoke(initial_state(DesignState(run_id="run-1")), self.config)

    def answer(self, *answers: dict[str, Any]) -> tuple[Requirement, ...]:
        response = {"kind": "requirements", "answers": list(answers)}
        self.graph.invoke(Command(resume=response), self.config)
        [requirements] = self.designed
        return requirements


def _texts(requirements: tuple[Requirement, ...]) -> list[tuple[str, str]]:
    return [(r.id, r.text) for r in requirements]


def test_no_answers_keep_every_requirement() -> None:
    assert _Run().answer() == REQS


def test_edit_changes_the_final_text_and_keeps_the_analysed_draft() -> None:
    result = _Run().answer({"req_id": "REQ-02", "action": "edit", "texts": ["출고를 확정한다"]})

    edited = result[1]
    assert (edited.id, edited.text, edited.draft_text) == (
        "REQ-02",
        "출고를 확정한다",
        "출고를 등록한다",
    )
    assert result[0] == REQS[0] and result[2] == REQS[2]


def test_split_keeps_the_first_id_and_gives_new_ids_to_the_rest() -> None:
    result = _Run().answer(
        {
            "req_id": "REQ-03",
            "action": "split",
            "texts": ["주문을 취소한다", "취소 사유를 저장한다"],
        }
    )

    assert _texts(result) == [
        ("REQ-01", "입고를 등록한다"),
        ("REQ-02", "출고를 등록한다"),
        ("REQ-03", "주문을 취소한다"),
        ("REQ-04", "취소 사유를 저장한다"),
    ]


def test_split_pieces_keep_the_source_link_of_the_original() -> None:
    """분할한 요구사항은 부모의 원문·분류를 그대로 쓴다 (docs/05).

    parent_id는 A01 분할처럼 비운다.
    """
    result = _Run().answer(
        {
            "req_id": "REQ-03",
            "action": "split",
            "texts": ["주문을 취소한다", "취소 사유를 저장한다"],
        }
    )

    original = REQS[2]
    for piece in result[2:]:
        assert piece.source_ref == original.source_ref
        assert (piece.source_id, piece.source_text) == (original.source_id, original.source_text)
        assert piece.source_acceptance_level == "필수"
        assert (piece.type, piece.analysis_version, piece.parent_id) == ("FR", 1, None)
        assert piece.draft_text == original.draft_text
    assert result[2].quality_issues == (AMBIGUOUS,)  # 원래 ID에 경고 기록을 남긴다
    assert result[3].quality_issues == ()


@pytest.mark.parametrize(
    "answer",
    [
        {"req_id": "REQ-09", "action": "keep", "texts": []},
        {"req_id": "REQ-01", "action": "edit", "texts": []},
        {"req_id": "REQ-01", "action": "edit", "texts": ["가", "나"]},
        {"req_id": "REQ-01", "action": "split", "texts": ["하나만"]},
        {"req_id": "REQ-01", "action": "keep", "texts": ["바꿀 문장"]},
    ],
)
def test_answer_that_does_not_fit_the_requirements_is_rejected(answer: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="REQ-0"):
        _Run().answer(answer)


def test_two_answers_for_one_requirement_are_rejected() -> None:
    keep = {"req_id": "REQ-01", "action": "keep", "texts": []}

    with pytest.raises(ValueError, match="REQ-01"):
        _Run().answer(keep, keep)
