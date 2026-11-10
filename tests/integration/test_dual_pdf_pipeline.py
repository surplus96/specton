"""#17 TC-F17·18: 실제 두 PDF를 동시에 켜 8종 생성·승인·동일 바이트 다운로드를 검증한다."""

from __future__ import annotations

import os
import shutil
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from dual_pdf_support import PRIVATE, World
from test_scripted_flow import _Flow

from specton.api import main
from specton.config import Settings
from specton.contracts import DesignState
from specton.pdf_adapter import PdfRenderer, RenderedPdf
from specton.persistence.db import Pool

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        os.environ.get("SPECTON_TEST_NATIVE_PDF") != "1",
        reason="실제 DB·Mermaid·WeasyPrint·한글 폰트 환경에서 SPECTON_TEST_NATIVE_PDF=1로 실행",
    ),
]


@pytest.fixture
def world(pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    assert shutil.which("mmdc") is not None
    config = os.environ.get("SPECTON_MMDC_PUPPETEER")
    settings = Settings(
        _env_file=None,
        openai_api_key=None,
        storage_dir=tmp_path / "storage",
        require_sql_validation=True,
        enable_erd_pdf=True,
        enable_function_spec_pdf=True,
        mermaid_puppeteer_config=Path(config) if config else None,
    )
    calls: list[tuple[str, int]] = []
    for name in ("erd", "functions"):
        attr = "erd_pdf_renderer" if name == "erd" else "function_spec_pdf_renderer"
        monkeypatch.setattr(main, attr, _counted(name, getattr(main, attr), calls))
    item = World(pool, settings, _Flow(pool, settings), calls)
    try:
        yield item
    finally:
        item.flow.runner.stop()
        item.flow.client.close()


def _counted(
    kind: str,
    factory: Callable[[Settings], PdfRenderer],
    calls: list[tuple[str, int]],
) -> Callable[[Settings], PdfRenderer]:
    def create(settings: Settings) -> PdfRenderer:
        native = factory(settings)

        def render(design: DesignState) -> RenderedPdf:
            calls.append((kind, design.revision))
            result = native(design)
            assert result.blocked_urls == ()
            pages = result.pages
            assert pages and all(width > 0 and height > 0 for width, height in pages)
            assert pages[0][0] < pages[0][1]  # 두 표지는 세로다.
            return result

        return render

    return create


def test_two_native_pdfs_hold_restart_and_eight_approved_outputs(world: World) -> None:
    run_id = world.start(restart_requirements=True)
    content = world.candidates(run_id, 0)
    before = world.rows(run_id, 0)
    calls = list(world.renders)
    assert Counter(calls) == Counter({("erd", 0): 1, ("functions", 0): 1})
    assert world.review(run_id, "hold")["status"] == "awaiting_review"
    world.restart()
    assert world.candidates(run_id, 0) == content and world.rows(run_id, 0) == before
    world.assert_approved(run_id, 0, content)
    assert world.renders == calls  # 보류·재시작·승인은 렌더러를 다시 부르지 않는다.
    assert world.flow.transport.calls == {}


def test_two_native_pdfs_revision_keeps_old_drafts_and_approves_only_new(world: World) -> None:
    run_id = world.start()
    old = world.candidates(run_id, 0)
    old_rows = world.rows(run_id, 0)
    first = world.flow.status(run_id)
    status = world.review(run_id, "revise")
    assert (status["status"], status["revision"]) == ("awaiting_review", 1)
    stale = world.flow.resume(first, {"kind": "review", "decision": "approve", "feedback": ""})
    assert stale.status_code == 409 and world.flow.status(run_id) == status
    current = world.candidates(run_id, 1)
    assert world.rows(run_id, 0) == old_rows
    world.assert_approved(run_id, 1, current)
    for key in PRIVATE:
        assert world.download(run_id, key, 0).status_code == 409
        assert old[key] != current[key]
    assert all(row["approval_status"] == "draft" for row in world.rows(run_id, 0).values())
    assert Counter(world.renders) == Counter(
        {
            ("erd", 0): 1,
            ("functions", 0): 1,
            ("erd", 1): 1,
            ("functions", 1): 1,
        }
    )


def test_two_native_pdfs_sql_critical_blocks_approval_until_repair(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from specton import ddl_adapter

    original = ddl_adapter.generate_ddl
    calls = 0

    def broken_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            sql = result.sql.replace("varchar(10)", "numeric(1001)", 1)
            assert sql != result.sql
            return result.model_copy(update={"sql": sql})
        return result

    monkeypatch.setattr(ddl_adapter, "generate_ddl", broken_once)
    run_id = world.start()
    world.candidates(run_id, 0)
    before = world.flow.status(run_id)
    findings = world.flow.view(run_id, "review")["items"]
    assert any(f["rule_code"] == "RULE-07" and f["severity"] == "critical" for f in findings)
    assert world.flow.transport.calls["A09"] == 0
    assert (
        world.flow.resume(
            before, {"kind": "review", "decision": "approve", "feedback": ""}
        ).status_code
        == 422
    )
    assert world.flow.status(run_id) == before
    assert world.review(run_id, "revise")["revision"] == 1
    content = world.candidates(run_id, 1)
    world.assert_approved(run_id, 1, content)


def test_two_native_pdfs_cancel_never_publishes_candidates(world: World) -> None:
    run_id = world.start()
    world.candidates(run_id, 0)
    before = world.rows(run_id, 0)
    response = world.flow.client.post(f"/runs/{run_id}/cancel", json={"expected_revision": 0})
    assert response.status_code == 202
    world.flow.runner.run_pending()
    assert world.flow.status(run_id)["status"] == "cancelled"
    assert world.rows(run_id, 0) == before
    for key in PRIVATE:
        assert world.download(run_id, key, 0).status_code == 409
