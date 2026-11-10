"""기능 명세서 PDF 연결 (#17, 엔진 #243): 승인 전 비공개 → 승인 뒤 같은 바이트 공개.

#19의 고정 규칙 LLM 흐름(`test_scripted_flow`)으로 실제 노드를 끝까지 돌린다. PDF 엔진(WeasyPrint)은
실행 이미지 시험(#243)이 맡으므로 여기서는 렌더러 공장을 바꿔 끼워 연결·승인·다운로드만 본다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from test_scripted_flow import _Flow, _to_final_review

from specton.api import main
from specton.config import Settings
from specton.contracts import DesignState
from specton.pdf_adapter import PdfRenderer
from specton.persistence.db import Pool

pytestmark = pytest.mark.db


@dataclass(frozen=True)
class _Pdf:
    pdf: bytes
    warnings: tuple[str, ...] = ()
    blocked_urls: tuple[str, ...] = ()


def test_function_spec_pdf_is_private_until_approval_and_published_as_the_same_bytes(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        storage_dir=tmp_path / "storage",
        runner_poll_seconds=0.05,
        lease_seconds=5,
        lease_renew_seconds=1,
        enable_function_spec_pdf=True,
    )
    rendered: list[bytes] = []

    def factory(config: Settings) -> PdfRenderer:
        assert config is settings

        def render(design: DesignState) -> _Pdf:
            content = f"%PDF-1.7\n{design.run_id}:{design.revision}\n%%EOF".encode()
            rendered.append(content)
            return _Pdf(content)

        return render

    monkeypatch.setattr(main, "function_spec_pdf_renderer", factory)
    flow = _Flow(pool, settings)
    flow.runner.start()
    try:
        run_id, asked = _to_final_review(flow)

        # 최종 검토: Markdown 옆에 PDF 후보가 있지만 승인 전이라 내려받을 수 없다
        drafts = {
            (a["kind"], a["file_format"]): a for a in flow.view(run_id, "design")["artifacts"]
        }
        pdf = drafts[("functions", "pdf")]
        assert pdf["approved"] is False and ("functions", "md") in drafts
        (content,) = rendered
        assert pdf["hash"] == hashlib.sha256(content).hexdigest()
        params = {"file_format": "pdf", "revision": asked["revision"]}
        before = flow.client.get(f"/runs/{run_id}/artifacts/functions", params=params)
        assert before.status_code == 409

        approve = {"kind": "review", "decision": "approve", "feedback": ""}
        assert flow.resume(asked, approve).status_code == 202
        done = flow.wait(run_id, state="completed")

        # 승인 뒤: 다시 렌더링하지 않고 같은 바이트를 공개한다
        got = flow.client.get(f"/runs/{run_id}/artifacts/functions", params=params)
        assert got.status_code == 200 and got.content == content
        assert got.headers["content-type"] == "application/pdf"
        assert "-draft" not in got.headers["content-disposition"]
        assert rendered == [content]

        # 승인본 manifest에도 같은 해시로 들어간다
        manifest = flow.client.get(
            f"/runs/{run_id}/artifacts/manifest",
            params={"file_format": "json", "revision": done["revision"]},
        )
        assert manifest.status_code == 200
        exported = json.loads(manifest.content)
        with pool.connection() as conn:
            snapshot = conn.execute(
                "SELECT normalized_model, model_hash FROM model_snapshot "
                "WHERE run_id=%s AND revision=%s",
                (UUID(run_id), done["revision"]),
            ).fetchone()
        assert snapshot is not None
        normalized = snapshot["normalized_model"]["normalized"]
        assert exported["model_hash"] == snapshot["model_hash"]
        assert exported["generator_versions"]["common_version"] == normalized["common_version"]
        assert exported["generator_versions"]["policy_digest"] == normalized["policy_digest"]
        assert normalized["common_version"] == "0.1.5" and normalized["policy_digest"]
        listed = {
            (f["kind"], f["file_format"]): f["hash"] for f in json.loads(manifest.content)["files"]
        }
        assert listed[("functions", "pdf")] == pdf["hash"]
    finally:
        flow.runner.stop()
