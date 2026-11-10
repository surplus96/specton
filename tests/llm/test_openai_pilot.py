"""#49: 예산 확인 후 수동 실행하는 합성 입력 시범 5회 (#105 현행 스키마 포함).

저장소 루트에서 실행:
    uv run pytest tests/llm/test_openai_pilot.py -m llm -q -s -x --tb=short

combined에서 설계 4회 + 검토 1회이며 A03 이름 재검토·구조화 출력·SDK 재시도는 추가된다.
출력한 호출별 JSON에는 원문·키가 없다. 비용은 표준 입력/출력 단가 추정이다.
캐시 읽기 할인·쓰기 비용은 포함하지 않는다.
"""

import json
import os

import pytest

from specton.config import Settings
from specton.contracts import DesignState, SourceRequirement
from specton.contracts.state import VersionInfo
from specton.llm.openai_transport import openai_client
from specton.pilot import run_pilot

pytestmark = pytest.mark.llm

# 2026-11-11 공식 모델 페이지의 표준 입력/출력 단가(100만 토큰당 USD).
# https://developers.openai.com/api/docs/models/gpt-6.1-sol
# https://developers.openai.com/api/docs/models/gpt-6-luna
# 다른 모델로 바꾸면 단가를 확인해 추가한다. 모르는 모델의 비용은 null로 남긴다.
RATES = {"gpt-6.1-sol": (2.0, 10.0), "gpt-6-luna": (0.10, 0.50)}


@pytest.fixture(scope="module")
def pilot_settings() -> Settings:
    settings = Settings(_env_file=os.environ.get("SPECTON_PILOT_ENV_FILE", ".env"))
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
        pytest.skip("SPECTON_OPENAI_API_KEY가 없습니다")
    return settings


@pytest.mark.parametrize("repetition", range(1, 6))
def test_synthetic_design_and_review(pilot_settings: Settings, repetition: int) -> None:
    """출력은 노드의 현행 스키마와 원문 참조 검사를 거친다. 판단 정확도의 평가는 별도다."""
    texts = (
        "사용자는 창고의 고유 창고코드와 이름을 등록하고 조회할 수 있다.",
        "사용자는 창고에 입고 기록을 등록하고 조회할 수 있다. "
        "각 입고 기록은 하나의 창고에 속하며 기록 내용과 작성일시를 저장한다.",
    )
    design = DesignState(
        run_id=f"pilot-{repetition}",
        versions=VersionInfo(pack_id="inventory", pack_version="0.1.23"),
        source_requirements=tuple(
            SourceRequirement(
                document_id="synthetic-pilot",
                block_id=f"csv:{row}",
                source_ref={"file_format": "csv", "row": row},
                source_text=text,
                extraction_status="pass",
            )
            for row, text in enumerate(texts, start=2)
        ),
    )

    result = run_pilot(openai_client(pilot_settings), pilot_settings, design)

    report = result.usage(rates=RATES) | {
        "design_model": pilot_settings.design_model,
        "review_model": pilot_settings.review_model,
        "design_reasoning_effort": pilot_settings.design_reasoning_effort,
        "review_reasoning_effort": pilot_settings.review_reasoning_effort,
        "review_mode": pilot_settings.review_mode,
        "pricing_as_of": "2026-11-11",
        "adr_0007_full_run_reference_usd": 0.2,
        "scope": "A01-A04 and review only; no HITL, rework, or artifact generation",
    }
    print(json.dumps(report, ensure_ascii=False), flush=True)
    assert result.ok, f"시범 실행 실패: {result.error_code} (위 호출 기록 참조)"
    assert result.design.requirements and result.design.functions and result.design.entities
    assert {b.branch for b in result.branches} == {"A05", "A06", "A07", "A08"}
