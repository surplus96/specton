"""동일 요구사항을 보존하며 비교 조건의 예시·사전 힌트만 제거하는 경계."""

import json

import pytest
from pydantic import BaseModel

from specton.evaluation.pipeline import WithoutDomainContext
from specton.llm.stub import reply, stub_client
from specton.llm.types import LLMRequest, Message
from specton.nodes.common import data_block, unwrap_data


class Answer(BaseModel):
    ok: bool


@pytest.mark.parametrize("keep_naming", [False, True])
def test_ablation_preserves_requirements_and_never_sends_example_answers(keep_naming: bool) -> None:
    inner, transport = stub_client(reply(Answer(ok=True)))
    request = LLMRequest(
        stage="A03",
        prompt_version="a03-v6-exploration-v1",
        model="stub",
        max_output_tokens=1000,
        messages=(
            Message(role="system", content="계약과 공통 설계 규칙"),
            Message(role="user", content=data_block({"example": "private-example"})),
            Message(role="assistant", content="private-example-answer"),
            Message(
                role="user",
                content=data_block(
                    {
                        "requirements": [{"id": "REQ-01", "text": "품목을 등록한다."}],
                        "pack": {"terms": ["private-term"]},
                        "evaluation_naming": {"approved_name_forms": {"old": "new"}},
                    }
                ),
            ),
        ),
    )
    result = WithoutDomainContext(inner, keep_naming_guidance=keep_naming).complete(
        request, Answer, token_budget=100
    )
    sent = transport.sent[0]
    assert len(sent.messages) == 2 and sent.messages[0] == request.messages[0]
    data = json.loads(unwrap_data(sent.messages[-1].content))
    expected = {"requirements": [{"id": "REQ-01", "text": "품목을 등록한다."}]}
    if keep_naming:
        expected["evaluation_naming"] = {"approved_name_forms": {"old": "new"}}
    assert data == expected
    assert "private-example-answer" not in str(sent)
    suffix = "-without-pack-context-v1" if keep_naming else "-without-domain-context-v1"
    assert result.calls[0].prompt_version.endswith(suffix)
