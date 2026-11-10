"""#17·#216: 실제 업로드·파싱 후 한도 검사, A01 미호출과 경계값 진행."""

from pathlib import Path

import pytest
from test_scripted_flow import _Flow

from specton.config import Settings
from specton.persistence.db import Pool

pytestmark = pytest.mark.db


@pytest.mark.parametrize("limit", [2, 3])
def test_api_enforces_source_limit_before_a01_without_partial_analysis(
    pool: Pool, tmp_path: Path, limit: int
) -> None:
    settings = Settings(_env_file=None, openai_api_key=None, storage_dir=tmp_path,
                        max_source_blocks=limit)  # fmt: skip
    flow = _Flow(pool, settings)
    try:
        run_id = flow.upload()  # 실제 CSV 파서가 3개 블록(pass 2개·review 1개)을 만든다.
        flow.runner.run_pending()
        current = flow.status(run_id)
        assert dict(flow.transport.calls) == {}
        if limit == 2:
            assert current["status"] == "failed" and current["interrupt"] is None
            assert current["error"]["code"] == "EXTRACTION_FAILED"
            assert "2건" in current["error"]["message"]
            assert "3건" in current["error"]["detail"]
            for section in ("extraction", "requirements", "design"):
                assert (
                    flow.client.get(f"/runs/{run_id}/view", params={"section": section}).json()[
                        "items"
                    ]
                    == []
                )
        else:
            assert current["status"] == "awaiting_input"
            response = flow.resume(
                current, {"kind": "extraction", "confirmed": True, "excluded_blocks": []}
            )
            assert response.status_code == 202
            flow.runner.run_pending()
            assert flow.status(run_id)["status"] == "awaiting_requirements"
            assert flow.transport.calls["A01"] == 1
    finally:
        flow.runner.stop()
        flow.client.close()
