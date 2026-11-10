"""#18 수동 합성 진단. 승인 비공개 평가 자료·정답은 모델에 보내지 않는다."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from specton.config import Settings
from specton.contracts import DesignState
from specton.llm.openai_transport import openai_client
from specton.review.comparison import run_comparison_condition

pytestmark = pytest.mark.llm
FIXTURES = Path(__file__).parents[1] / "unit/data/review_comparison_synthetic.json"
CASES = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
@pytest.mark.parametrize("repetition", [1, 2])
def test_same_design_in_both_review_modes(case: dict[str, object], repetition: int) -> None:
    base = Settings(_env_file=os.environ.get("SPECTON_PILOT_ENV_FILE", ".env"))
    if not base.openai_api_key or not base.openai_api_key.get_secret_value().strip():
        pytest.skip("SPECTON_OPENAI_API_KEY가 없습니다")
    # 순서 효과를 드러내기 위해 두 번째 반복은 실행 순서를 뒤집는다.
    modes = ("parallel", "combined") if repetition == 1 else ("combined", "parallel")
    for mode in modes:
        settings = Settings(_env_file=None, **(base.model_dump() | {"review_mode": mode}))
        client = openai_client(settings)
        result = run_comparison_condition(
            lambda client=client: client, settings, DesignState.model_validate(case["design"])
        )
        report = result.report() | {
            "case_id": case["case_id"],
            "repetition": repetition,
            "fixture_sha256": hashlib.sha256(FIXTURES.read_bytes()).hexdigest(),
            "scope": "synthetic diagnostic; no design/rework/generation; not blind evaluation",
        }
        print(json.dumps(report, ensure_ascii=False), flush=True)
        assert result.merge.complete
