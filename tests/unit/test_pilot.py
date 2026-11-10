"""#49 시범 실행을 stub으로 검증한다. 실제 호출은 tests/llm에서만 한다."""

import json

import pytest
from openai.lib._parsing._responses import type_to_text_format_param
from pydantic import BaseModel, SecretStr

from specton.config import Settings
from specton.contracts import DesignState, SourceRequirement
from specton.contracts.state import VersionInfo
from specton.llm.client import RawReply
from specton.llm.errors import LLMAPIError
from specton.llm.stub import reply, stub_client
from specton.nodes.a01_requirements import A01Output
from specton.nodes.a02_functions import A02Output
from specton.nodes.a03_entities import A03Output
from specton.nodes.a04_relationships import A04Output
from specton.pilot import run_pilot
from specton.review.reviewer import CombinedReviewOutput

TEXTS = ("사용자가 창고를 등록한다.", "입고기록은 하나의 창고에 속한다.")


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, openai_api_key=SecretStr("secret-pilot-key"))


@pytest.fixture
def design() -> DesignState:
    return DesignState(
        run_id="pilot-1",
        versions=VersionInfo(pack_id="inventory", pack_version="0.1.23"),
        source_requirements=tuple(
            SourceRequirement(
                document_id="synthetic",
                block_id=f"csv:{row}",
                source_ref={"file_format": "csv", "row": row},
                source_text=text,
                extraction_status="pass",
            )
            for row, text in enumerate(TEXTS, start=2)
        ),
    )


def _entities() -> A03Output:
    return A03Output.model_validate(
        {
            "entities": [
                {
                    "name": name,
                    "description": name,
                    "req_ids": [req],
                    "attributes": [
                        {
                            "name": f"{name}코드",
                            "data_type": "varchar",
                            "length": 10 if name == "창고" else 20,
                            "is_key": True,
                            "nullable": False,
                            "req_ids": [req],
                        }
                    ],
                }
                for name, req in (("창고", "REQ-01"), ("입고기록", "REQ-02"))
            ],
            "entity_ops": [
                {"function_id": "FUNC-01", "entity_name": name, "operations": ["C"]}
                for name in ("창고", "입고기록")
            ],
        }
    )


def _relationships() -> A04Output:
    return A04Output.model_validate(
        {
            "relationships": [
                {
                    "parent_name": "창고",
                    "child_name": "입고기록",
                    "cardinality": "1:N",
                    "optional": False,
                    "rationale": f'"{TEXTS[1]}" 기록은 창고에 속한다.',
                    "req_ids": ["REQ-02"],
                }
            ]
        }
    )


@pytest.fixture
def steps() -> tuple[RawReply, ...]:
    a01 = A01Output.model_validate(
        {
            "requirements": [
                {"source_block_ids": [f"csv:{row}"], "text": text, "type": "FR"}
                for row, text in enumerate(TEXTS, start=2)
            ]
        }
    )
    a02 = A02Output.model_validate(
        {
            "functions": [
                {
                    "name": "창고과 기록 등록",
                    "description": "창고과 입고기록을 등록한다",
                    "priority": None,
                    "priority_source": "unspecified",
                    "req_ids": ["REQ-01", "REQ-02"],
                }
            ]
        }
    )
    review = CombinedReviewOutput.model_validate(
        {
            "perspectives": [
                {"reviewer_id": agent, "findings": []} for agent in ("A05", "A06", "A07", "A08")
            ]
        }
    )
    return tuple(reply(output) for output in (a01, a02, _entities(), _relationships(), review))


def test_pilot_uses_real_nodes_and_both_configured_models(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, transport = stub_client(*steps)

    result = run_pilot(client, settings, design)

    assert result.ok
    assert [r.stage for r in transport.sent] == ["A01", "A02", "A03", "A04", "REVIEW"]
    assert [r.model for r in transport.sent] == [settings.design_model] * 4 + [
        settings.review_model
    ]
    assert [r.reasoning_effort for r in transport.sent] == ["medium"] * 4 + ["low"]
    assert result.design.normalized is not None
    assert result.wall_time_ms >= 0
    assert len(result.design.relationships) == 1
    assert result.design.functions[0].entity_ops
    assert result.design.versions.model_names["A04"] == settings.design_model


def test_report_has_usage_but_no_key_source_text_or_prompt(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, _ = stub_client(*steps)

    usage = run_pilot(client, settings, design).usage()

    assert (usage["input_tokens"], usage["output_tokens"], usage["structured_retries"]) == (
        50,
        50,
        0,
    )
    assert usage["sdk_retry_count"] is None
    serialized = json.dumps(usage, ensure_ascii=False)
    assert "secret-pilot-key" not in serialized
    assert all(text not in serialized for text in TEXTS)
    assert "messages" not in serialized


def test_invalid_output_retry_is_counted(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, _ = stub_client(reply("{}"), *steps)

    result = run_pilot(client, settings, design)

    assert result.ok
    assert result.usage()["structured_retries"] == 1
    assert [c.outcome for c in result.calls[:2]] == ["invalid_output", "ok"]


def test_failed_design_stops_and_retains_previous_usage(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, transport = stub_client(steps[0], LLMAPIError("A02: 실패"))

    result = run_pilot(client, settings, design)

    assert not result.ok
    assert result.error_code == "LLM_UNAVAILABLE"
    assert [c.outcome for c in result.calls] == ["ok", "api_error"]
    assert result.design.requirements and not result.design.functions
    assert len(transport.sent) == 2


def test_failed_review_is_not_reported_as_success(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, _ = stub_client(*steps[:4], LLMAPIError("REVIEW: 실패"))

    result = run_pilot(client, settings, design)

    assert not result.ok
    assert result.error_code == "LLM_UNAVAILABLE"
    assert len(result.branches) == 4 and all(not b.ok for b in result.branches)
    assert [c.outcome for c in result.calls] == ["ok"] * 4 + ["api_error"]


def test_token_budget_prevents_the_next_node_call(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    limited = Settings(_env_file=None, max_tokens_per_run=20)
    client, transport = stub_client(*steps)

    result = run_pilot(client, limited, design)

    assert not result.ok
    assert result.error_code == "BUDGET_EXCEEDED"
    assert len(transport.sent) == 1
    assert result.usage()["input_tokens"] == 10


def test_report_estimates_cost_from_all_recorded_calls(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, _ = stub_client(reply("{}"), *steps)

    result = run_pilot(client, settings, design)
    usage = result.usage(
        rates={settings.design_model: (2.0, 10.0), settings.review_model: (0.1, 0.5)}
    )

    assert usage["estimated_cost_usd"] == pytest.approx(0.000606)
    assert result.usage(rates={})["estimated_cost_usd"] is None


def test_api_failure_cost_is_unknown_even_when_rates_are_known(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, _ = stub_client(steps[0], LLMAPIError("실패"))

    result = run_pilot(client, settings, design)

    assert result.usage(rates={settings.design_model: (2.0, 10.0)})["estimated_cost_usd"] is None


@pytest.mark.parametrize(
    ("model", "definitions"),
    [
        (A01Output, ["RequirementType"]),
        (A02Output, ["PrioritySource"]),
        (A03Output, ["AttributeDraft", "Crud"]),
        (A04Output, ["Cardinality"]),
    ],
)
def test_sdk_schema_keeps_contract_descriptions(
    model: type[BaseModel], definitions: list[str]
) -> None:
    """#49의 #105 후속: 실제 전송할 SDK 스키마에 계약 설명이 포함된다."""
    schema = type_to_text_format_param(model)["schema"]

    assert schema["additionalProperties"] is False
    for name in definitions:
        assert schema["$defs"][name]["description"]


def test_pack_mismatch_stops_before_review(
    settings: Settings, design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, transport = stub_client(*steps)
    design = design.evolve(versions=design.versions.evolve(pack_version="0.0.0"))
    result = run_pilot(client, settings, design)
    assert result.error_code == "NORMALIZATION_FAILED"
    assert result.design.normalized is None
    assert len(transport.sent) == 4


def test_parallel_cannot_be_misreported_as_concurrent(
    design: DesignState, steps: tuple[RawReply, ...]
) -> None:
    client, transport = stub_client(*steps)
    with pytest.raises(ValueError, match="combined"):
        run_pilot(client, Settings(_env_file=None, review_mode="parallel"), design)
    assert not transport.sent
