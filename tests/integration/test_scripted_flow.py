"""기본 흐름 검증: 고정 규칙 LLM으로 업로드부터 다운로드까지 (#19, TC-F19의 LLM 없는 부분).

실제 OpenAI를 부르지 않는다. A01~A09는 `scripted_llm.ScriptedTransport`가 답하고, 그 밖의 노드
(원문 읽기·정리·ERD·DDL·SQL 검증·RTM·기능 명세·규칙 검사·승인·내보내기)는 API가 쓰는 것과 같은
실제 노드다(`create_graph`). 사용자 행동은 웹 화면과 같은 API 호출로 한다.

시나리오
1. 승인 흐름: 업로드 → 추출 확인(UI-02) → 분석 확인(UI-03) → 최종 검토(UI-06) 승인
   → 내려받기(UI-07)
   - 같은 확인 요청에 두 번 답하면 409, 상태 다시 조회(새로고침)해도 같은 결과
2. 수정 요청 흐름: 최종 검토에서 수정 요청 → A09가 데이터 모델로 되돌림
   → 새 revision 최종 검토 → 승인
실제 LLM을 쓰는 E2E(TC-F19)는 실행 조건(키·예산)을 맞춘 뒤 따로 확인한다.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from scripted_llm import ENTITIES, RELATIONSHIPS, ScriptedTransport, scripted_agent_nodes

from specton.api.main import create_app, create_graph
from specton.config import Settings
from specton.persistence.db import Pool, create_checkpointer
from specton.runner import Runner

pytestmark = pytest.mark.db

# 세 번째 행은 요구사항 ID가 없어 추출 확인(review)에서 멈춘다
CSV = (
    "요구사항 ID,요구사항명,상세 내용\n"
    "SFR-001,입고 등록,창고에 품목을 입고하고 입고 내역을 남긴다.\n"
    "SFR-002,품목 조회,품목 목록을 조회한다.\n"
    ",재고 확인,창고별 재고를 확인한다.\n"
).encode()
WAIT_SECONDS = 90


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        storage_dir=tmp_path / "storage",
        runner_poll_seconds=0.05,
        lease_seconds=5,
        lease_renew_seconds=1,
        enable_erd_pdf=False,  # mermaid-cli 없이 돈다. PDF는 실행 이미지 시험(#209·#243)
    )


class _Flow:
    """API 클라이언트(웹과 같은 호출)와 고정 규칙 LLM으로 도는 실행기."""

    def __init__(self, pool: Pool, settings: Settings) -> None:
        self.transport = ScriptedTransport()
        graph = create_graph(
            settings,
            create_checkpointer(pool),
            agent_nodes=scripted_agent_nodes(settings, self.transport),
        )
        self.runner = Runner(pool, graph, settings)
        self.client = TestClient(create_app(settings, pool))

    def upload(self) -> str:
        response = self.client.post(
            "/runs",
            files={"file": ("재고_요구사항.csv", CSV, "text/csv")},
            data={"pack": "inventory"},
        )
        assert response.status_code == 202, response.text
        return str(response.json()["run_id"])

    def status(self, run_id: str) -> dict[str, Any]:
        response = self.client.get(f"/runs/{run_id}")
        assert response.status_code == 200, response.text
        return dict(response.json())

    def wait(
        self, run_id: str, *, interrupt: str | None = None, state: str | None = None
    ) -> dict[str, Any]:
        """확인 요청(`interrupt`)이나 상태(`state`)가 될 때까지 기다린다.

        실행이 실패·취소로 끝나면 이유와 함께 멈춘다.
        """
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            current = self.status(run_id)
            if current["status"] in {"failed", "cancelled"} and state != current["status"]:
                raise AssertionError(f"실행이 끝났습니다: {current}")
            asked = current["interrupt"] and current["interrupt"]["kind"]
            if (interrupt and asked == interrupt) or (state and current["status"] == state):
                return current
            time.sleep(0.1)
        raise AssertionError(f"기다린 상태가 오지 않았습니다: {self.status(run_id)}")

    def resume(self, current: dict[str, Any], response: dict[str, Any]) -> Any:
        return self.client.post(
            f"/runs/{current['run_id']}/resume",
            json={
                "interrupt_id": current["interrupt"]["interrupt_id"],
                "expected_revision": current["revision"],
                "response": response,
            },
        )

    def view(self, run_id: str, section: str) -> dict[str, Any]:
        response = self.client.get(f"/runs/{run_id}/view", params={"section": section})
        assert response.status_code == 200, response.text
        return dict(response.json())


@pytest.fixture
def flow(pool: Pool, settings: Settings) -> Iterator[_Flow]:
    f = _Flow(pool, settings)
    f.runner.start()
    try:
        yield f
    finally:
        f.runner.stop()


def _to_final_review(f: _Flow) -> tuple[str, dict[str, Any]]:
    """업로드 → 추출 확인 → 분석 확인 → 최종 검토까지 (UI-01~UI-06)."""
    run_id = f.upload()

    asked = f.wait(run_id, interrupt="extraction")
    blocks = f.view(run_id, "extraction")["items"]
    review = [b for b in blocks if b["extraction_status"] == "review"]
    assert len(blocks) == 3 and len(review) == 1  # ID 없는 행 하나
    assert (
        f.resume(
            asked, {"kind": "extraction", "confirmed": True, "excluded_blocks": []}
        ).status_code
        == 202
    )

    asked = f.wait(run_id, interrupt="requirements")
    requirements = f.view(run_id, "requirements")["items"]
    assert [r["id"] for r in requirements] == ["REQ-01", "REQ-02", "REQ-03"]
    keep = {
        "kind": "requirements",
        "answers": [{"req_id": "REQ-01", "action": "keep", "texts": []}],
    }
    assert f.resume(asked, keep).status_code == 202

    return run_id, f.wait(run_id, interrupt="review")


def test_upload_to_download_with_the_scripted_llm(flow: _Flow) -> None:
    run_id, asked = _to_final_review(flow)

    # UI-06: 설계·산출물(초안)·검토
    design = flow.view(run_id, "design")
    kinds = [i["type"] for i in design["items"]]
    assert kinds.count("function") == 3
    assert kinds.count("entity") == len(ENTITIES) and kinds.count("relationship") == len(
        RELATIONSHIPS
    )
    drafts = {(a["kind"], a["file_format"]): a for a in design["artifacts"]}
    assert {
        ("erd", "mmd"),
        ("ddl", "sql"),
        ("rtm", "xlsx"),
        ("rtm", "csv"),
        ("functions", "md"),
    } <= set(drafts)
    assert not any(a["approved"] for a in drafts.values())
    assert drafts[("ddl", "sql")]["validation"]["status"] == "passed"  # 격리 DB에서 실제 실행
    assert design["normalization"]["tables"] == len(ENTITIES)
    assert design["normalization"]["columns"] >= len(ENTITIES)
    assert design["normalization"]["common_version"] is not None
    findings = flow.view(run_id, "review")["items"]
    assert not [f for f in findings if f["severity"] == "critical"]  # 승인할 수 있다

    approve = {"kind": "review", "decision": "approve", "feedback": ""}
    assert flow.resume(asked, approve).status_code == 202
    second = flow.resume(asked, approve)  # 같은 확인 요청에 다시 답함 (다른 탭·중복 클릭)
    assert second.status_code == 409 and second.json()["code"] == "INTERRUPT_STALE"

    done = flow.wait(run_id, state="completed")
    assert flow.status(run_id) == done  # 새로고침(상태 다시 조회)해도 같다

    # UI-07: 승인본 내려받기
    artifacts = flow.view(run_id, "design")["artifacts"]
    assert artifacts and all(a["approved"] for a in artifacts)
    texts = {}
    for kind, file_format in [("erd", "mmd"), ("ddl", "sql"), ("rtm", "csv"), ("functions", "md")]:
        got = flow.client.get(
            f"/runs/{run_id}/artifacts/{kind}",
            params={"file_format": file_format, "revision": done["revision"]},
        )
        assert got.status_code == 200, (kind, got.text)
        assert "-draft" not in got.headers["content-disposition"]
        texts[kind] = got.content.decode("utf-8-sig")
    assert texts["erd"].startswith("erDiagram") and "입고내역" in texts["erd"]
    assert texts["ddl"].count("CREATE TABLE") == len(ENTITIES)
    assert "REQ-01" in texts["rtm"] and "REQ-03" in texts["rtm"]
    assert texts["functions"].startswith("# 기능 명세서")
    xlsx = flow.client.get(
        f"/runs/{run_id}/artifacts/rtm",
        params={"file_format": "xlsx", "revision": done["revision"]},
    )
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"

    # LLM 단계별 호출: 다시 묻지 않고 한 번씩, 수정 요청이 없으니 A09는 부르지 않는다
    assert flow.transport.calls["A01"] == flow.transport.calls["A02"] == 1
    assert flow.transport.calls["A03"] == flow.transport.calls["A04"] == 1
    assert flow.transport.calls["A09"] == 0
    stream = flow.client.get(f"/runs/{run_id}/events")
    assert stream.status_code == 200
    import json

    data = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    progress = [e["payload"] for e in data if e.get("payload", {}).get("node")]
    assert len({(p["task_id"], p["phase"]) for p in progress}) == len(progress)
    a01 = next(p for p in progress if p["node"] == "a01" and p["phase"] == "finished")
    assert a01["result_saved"] is True and a01["calls"][0]["model"]
    assert not any(key in str(a01) for key in ("messages", "api_key", "storage_ref"))


def test_revise_goes_back_to_the_data_model_and_approves_the_new_revision(flow: _Flow) -> None:
    run_id, asked = _to_final_review(flow)
    revise = {
        "kind": "review",
        "decision": "revise",
        "feedback": "입고 엔티티에 입고일자를 필수로 해 주세요.",
    }
    assert flow.resume(asked, revise).status_code == 202

    again = flow.wait(run_id, interrupt="review")
    while again["interrupt"]["interrupt_id"] == asked["interrupt"]["interrupt_id"]:
        again = flow.wait(run_id, interrupt="review")
    assert again["revision"] == asked["revision"] + 1
    assert flow.transport.calls["A09"] == 1 and flow.transport.calls["A03"] == 2

    assert (
        flow.resume(again, {"kind": "review", "decision": "approve", "feedback": ""}).status_code
        == 202
    )
    done = flow.wait(run_id, state="completed")
    assert done["revision"] == again["revision"]
    artifacts = flow.view(run_id, "design")["artifacts"]
    assert artifacts and all(a["approved"] and a["revision"] == done["revision"] for a in artifacts)
