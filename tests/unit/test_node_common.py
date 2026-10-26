import json

import pytest
from pydantic import BaseModel

from specton.config import Settings
from specton.nodes.common import (
    COMMON_RULES,
    assign_ids,
    build_request,
    data_block,
    unwrap_data,
)
from specton.packs.examples import FewShot


class Label(BaseModel):
    label: str


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_data_block_wraps_text_and_mappings() -> None:
    assert data_block("입고한다") == "<data>\n입고한다\n</data>"
    assert unwrap_data(data_block({"요구": ["REQ-01"]})) == '{"요구": ["REQ-01"]}'


def test_design_request_uses_design_model_and_common_rules() -> None:
    settings = _settings()

    request = build_request(
        settings,
        role="design",
        stage="A02",
        prompt_version="a02-v1",
        system="기능을 설계한다",
        data={"requirements": []},
    )

    system, user = request.messages
    assert (request.model, request.reasoning_effort) == (
        settings.design_model,
        settings.design_reasoning_effort,
    )
    assert system.content.startswith("기능을 설계한다") and COMMON_RULES in system.content
    assert json.loads(unwrap_data(user.content)) == {"requirements": []}
    assert request.max_output_tokens == settings.max_output_tokens


def test_review_request_uses_review_model() -> None:
    settings = _settings()

    request = build_request(
        settings, role="review", stage="A05", prompt_version="a05-v1", system="검토", data="x"
    )

    assert (request.model, request.reasoning_effort) == (
        settings.review_model,
        settings.review_reasoning_effort,
    )


def test_examples_become_conversation_pairs_before_the_input() -> None:
    examples = (FewShot(source_id="INV-003", input="입고를 등록한다", output=Label(label="FR")),)

    request = build_request(
        _settings(),
        role="design",
        stage="A01",
        prompt_version="a01-v1",
        system="분류한다",
        data="출고한다",
        examples=examples,
    )

    assert [m.role for m in request.messages] == ["system", "user", "assistant", "user"]
    assert request.messages[1].content == data_block("입고를 등록한다")
    assert json.loads(request.messages[2].content) == {"label": "FR"}
    assert request.messages[3].content == data_block("출고한다")


def test_assign_ids_numbers_from_one_with_two_digits() -> None:
    assert assign_ids("FUNC", 3) == ("FUNC-01", "FUNC-02", "FUNC-03")
    assert assign_ids("ENT", 0) == ()


def test_assign_ids_rejects_negative_count() -> None:
    with pytest.raises(ValueError):
        assign_ids("FUNC", -1)
