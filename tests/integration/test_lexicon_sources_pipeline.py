"""#291: 출처가 고정된 어휘를 실제 API·정리·SQL·승인·다운로드로 연결한다."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
import scripted_llm
import test_scripted_flow as scripted_flow

from specton.config import Settings
from specton.packs.provenance import policy_digest
from specton.persistence.db import Pool

pytestmark = pytest.mark.db


def test_sourced_inventory_words_keep_policy_and_approved_download_bytes(
    pool: Pool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = scripted_llm._a03

    def with_sourced_attributes(data: dict[str, Any]) -> dict[str, Any]:
        answer = original(data)
        item = next(entity for entity in answer["entities"] if entity["name"] == "품목")
        for name in ("간선명", "금형번호", "거점명", "연차명"):
            item["attributes"].append(
                {
                    "name": name,
                    "data_type": "varchar",
                    "length": 200,
                    "is_key": False,
                    "nullable": True,
                    "req_ids": [data["requirements"][0]["id"]],
                }
            )
        return answer

    monkeypatch.setattr(
        scripted_llm,
        "_ANSWERS",
        tuple(
            (model, with_sourced_attributes if answer is original else answer)
            for model, answer in scripted_llm._ANSWERS
        ),
    )
    monkeypatch.setattr(
        scripted_flow,
        "CSV",
        scripted_flow.CSV.replace(
            "창고에 품목을 입고하고 입고 내역을 남긴다.".encode(),
            "품목의 간선명·금형번호·거점명·연차명을 등록하고 입고 내역을 남긴다.".encode(),
        ),
    )
    settings = Settings(
        _env_file=None,
        storage_dir=tmp_path / "storage",
        runner_poll_seconds=0.05,
        lease_seconds=5,
        lease_renew_seconds=1,
        enable_erd_pdf=False,
        enable_function_spec_pdf=False,
    )
    flow = scripted_flow._Flow(pool, settings)
    flow.runner.start()
    try:
        run_id, asked = scripted_flow._to_final_review(flow)
        design = flow.runner.graph.get_state({"configurable": {"thread_id": run_id}}).values[
            "design"
        ]
        assert design.normalized is not None
        assert design.normalized.pack_version == "0.1.23"
        assert design.normalized.policy_digest == policy_digest(settings.pack_root, "inventory")
        names = {
            column.physical_name for table in design.normalized.tables for column in table.columns
        }
        assert {"mnn_nm", "mld_no", "fthl_nm", "cnyr_nm"} <= names
        artifacts = flow.view(run_id, "design")["artifacts"]
        sql = next(a for a in artifacts if a["kind"] == "ddl" and a["file_format"] == "sql")
        assert sql["validation"]["status"] == "passed"
        url = f"/runs/{run_id}/artifacts/ddl"
        params = {"file_format": "sql", "revision": 0}
        draft = flow.client.get(url, params=params)
        assert draft.status_code == 200 and hashlib.sha256(draft.content).hexdigest() == sql["hash"]
        assert (
            flow.resume(
                asked, {"kind": "review", "decision": "approve", "feedback": ""}
            ).status_code
            == 202
        )
        flow.wait(run_id, state="completed")
        approved = flow.client.get(url, params=params)
        assert approved.status_code == 200 and approved.content == draft.content
        assert "-draft" not in approved.headers["content-disposition"]
    finally:
        flow.runner.stop()
