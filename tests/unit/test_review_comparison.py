"""실제 그래프 fan-out과 지연/실패 가지 보존(TC-F14)을 검증한다."""

from threading import Barrier
from time import sleep

import pytest
from pydantic import BaseModel

from specton.config import Settings
from specton.contracts import DesignState
from specton.llm.client import LLMClient, RawReply
from specton.llm.errors import LLMTimeoutError
from specton.llm.stub import reply, stub_client
from specton.llm.types import LLMRequest
from specton.review.comparison import run_comparison_condition


@pytest.fixture
def design() -> DesignState:
    return DesignState.model_validate(
        {
            "run_id": "synthetic-comparison",
            "versions": {"pack_id": "inventory"},
            "requirements": [
                {
                    "id": "REQ-01",
                    "text": "창고코드로 창고를 등록한다.",
                    "draft_text": "창고코드로 창고를 등록한다.",
                    "source_ref": {"file_format": "csv", "row": 2},
                    "analysis_version": 1,
                    "type": "FR",
                }
            ],
            "entities": [
                {
                    "id": "ENT-01",
                    "pack": "inventory",
                    "description": "창고코드로 식별하는 창고",
                    "name": "창고",
                    "req_ids": ["REQ-01"],
                    "attributes": [
                        {
                            "id": "ATTR-01",
                            "name": "창고코드",
                            "data_type": "varchar",
                            "length": 10,
                            "is_key": True,
                            "nullable": False,
                            "req_ids": ["REQ-01"],
                        }
                    ],
                }
            ],
        }
    )


class ConcurrentTransport:
    def __init__(self, failed: str | None = None) -> None:
        self.barrier = Barrier(4, timeout=5)
        self.failed = failed

    def send(self, request: LLMRequest, output_model: type[BaseModel]) -> RawReply:
        # 순차 실행이면 첫 호출이 barrier에서 실패한다. 네 가지가 실제로 동시에 진입해야 한다.
        self.barrier.wait()
        if request.stage == self.failed:
            sleep(0.05)
            raise LLMTimeoutError("synthetic delayed failure")
        if request.stage == "A06":
            return reply(
                '{"findings":[{"kind":"missing_function","severity":"major",'
                '"targets":[{"kind":"requirement","id":"REQ-01"}],'
                '"evidence":[{"req_id":"REQ-01","quote":"창고"}],'
                '"suggestion":"등록 기능을 추가한다","target_stage":"functions"}]}'
            )
        return reply('{"findings": []}')


@pytest.mark.parametrize("failed", [None, "A08"])
def test_four_branches_really_overlap_and_failures_survive(
    design: DesignState, failed: str | None
) -> None:
    client = LLMClient(ConcurrentTransport(failed), max_structured_retries=0)
    result = run_comparison_condition(
        lambda: client, Settings(_env_file=None, review_mode="parallel"), design
    )
    assert len(result.calls) == 4
    assert len(result.merge.findings) == 1
    assert result.merge.findings[0].reviewer_id == "A06"
    assert result.merge.complete is (failed is None)
    assert result.merge.failed_branches == (() if failed is None else ("A08",))
    assert sum(c.outcome == "ok" for c in result.calls) == (4 if failed is None else 3)
    spans = list(result.branch_times.values())
    assert max(s["start_ms"] for s in spans) <= min(s["end_ms"] for s in spans)
    assert result.provenance["pack_version"] == "0.1.23"


def test_combined_is_one_call_and_four_results(design: DesignState) -> None:
    client, transport = stub_client(
        reply(
            '{"perspectives":['
            '{"reviewer_id":"A05","findings":[]},'
            '{"reviewer_id":"A06","findings":[]},'
            '{"reviewer_id":"A07","findings":[]},'
            '{"reviewer_id":"A08","findings":[]}]}'
        )
    )
    result = run_comparison_condition(
        lambda: client, Settings(_env_file=None, review_mode="combined"), design
    )
    assert result.merge.complete
    assert len(transport.sent) == len(result.calls) == 1
    assert result.report()["scoring"].startswith("unscored")
    assert result.report()["sdk_retry_count"] is None
