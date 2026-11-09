"""#202 R1: 파서 상세 안내를 DB·상태 API·SSE에 보존하고 재조회·재시작해도 유지한다."""

import io
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from specton.api import main
from specton.config import Settings
from specton.graph import ExtractionFailedError, GraphState
from specton.llm.errors import LLMRefusalError
from specton.persistence.db import Pool, create_checkpointer
from specton.runner import Runner

pytestmark = pytest.mark.db
PRIVATE = "fixture-internal-exception /private/fixture/document.csv"
VALID = "요구사항 ID,요구사항명,상세 내용\nREQ-01,등록,정보를 등록한다\n".encode()


@pytest.mark.parametrize(
    "failure",
    [
        "csv_headers",
        "xlsx_headers",
        "detail_empty",
        "detail_whitespace",
        "detail_trimmed",
        "llm_refusal",
        "internal",
    ],
)
def test_error_detail_survives_reload_and_restart_without_exposing_other_errors(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    settings = Settings(_env_file=None, storage_dir=tmp_path, sse_poll_seconds=0.01)
    name, content = "req.csv", VALID
    if failure == "csv_headers":
        content = "이름,값\n가,1\n".encode()
    elif failure == "xlsx_headers":
        book = Workbook()
        book.active.append(["이름", "값"])
        book.active.append(["가", 1])
        stream = io.BytesIO()
        book.save(stream)
        name, content = "req.xlsx", stream.getvalue()

    def fail(state: GraphState) -> dict[str, Any]:
        if failure.startswith("detail_"):
            detail = {
                "detail_empty": "",
                "detail_whitespace": " \t\n",
                "detail_trimmed": " \n표의 칸 이름을 확인해 주세요. \n",
            }[failure]
            raise ExtractionFailedError("문서를 읽지 못했습니다.", detail)
        if failure == "llm_refusal":
            raise LLMRefusalError(PRIVATE)
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(
        main, "openai_agent_nodes", lambda config: {"a01": fail} if failure == "llm_refusal" else {}
    )
    if failure.startswith("detail_") or failure == "internal":
        monkeypatch.setattr(main, "parse_node", lambda root: fail)
    runner = Runner(pool, main.create_graph(settings, create_checkpointer(pool)), settings)
    try:
        with TestClient(main.create_app(settings, pool)) as client:
            created = client.post(
                "/runs", data={"pack": "inventory"}, files={"file": (name, content)}
            )
            assert created.status_code == 202, created.text
            run_id = created.json()["run_id"]
            runner.run_pending()
            response = client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            status = response.json()
            assert status["status"] == "failed"
            error = status["error"]
            expected_code = {"llm_refusal": "LLM_REFUSED", "internal": "INTERNAL"}.get(
                failure, "EXTRACTION_FAILED"
            )
            assert error["code"] == expected_code
            if expected_code == "EXTRACTION_FAILED":
                assert error["retryable"] is False
            assert PRIVATE not in json.dumps(status, ensure_ascii=False)
            if failure in ("csv_headers", "xlsx_headers"):
                assert error["code"] == "EXTRACTION_FAILED"
                assert isinstance(error["detail"], str) and error["detail"]
                assert "20행" in error["detail"]
            elif failure == "detail_trimmed":
                assert error["detail"] == "표의 칸 이름을 확인해 주세요."
            else:
                assert error["detail"] is None

            events = client.get(f"/runs/{run_id}/events")
            assert events.status_code == 200 and PRIVATE not in events.text
            rows = [json.loads(s[6:]) for s in events.text.splitlines() if s.startswith("data: ")]
            [failed] = [row for row in rows if row["payload"].get("code") == error["code"]]
            assert failed["message"] == error["message"]
            if error["detail"] is None:
                assert "detail" not in failed["payload"]
            else:
                assert failed["payload"]["detail"] == error["detail"]
            assert client.get(f"/runs/{run_id}").json()["error"] == error
            cookies = client.cookies
    finally:
        runner.stop()

    with pool.connection() as conn:
        saved = conn.execute("SELECT error FROM run WHERE run_id=%s", (UUID(run_id),)).fetchone()
    assert saved is not None and saved["error"] == error
    with TestClient(main.create_app(settings, pool)) as reopened:
        reopened.cookies.update(cookies)
        assert reopened.get(f"/runs/{run_id}").json()["error"] == error
        assert reopened.get(f"/runs/{run_id}/events").text == events.text
    with TestClient(main.create_app(settings, pool)) as other:
        assert other.get(f"/runs/{run_id}").status_code == 404
        assert other.get(f"/runs/{run_id}/events").status_code == 404
