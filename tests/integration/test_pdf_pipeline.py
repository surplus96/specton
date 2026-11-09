"""PDF 후보 → 승인 근거 → 동일 바이트 공개. 생성기·DB·다운로드를 실제 API로 검증한다."""

import hashlib
import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from specton.api import main
from specton.api.session import SESSION_COOKIE
from specton.config import Settings
from specton.contracts import Attribute, DesignState, Entity, Function, Requirement
from specton.contracts.base import TargetStage
from specton.graph import GraphState
from specton.model_hash import model_hash
from specton.pdf_adapter import PdfRenderer
from specton.persistence import lease, runs
from specton.persistence.db import Pool, create_checkpointer
from specton.runner import Runner

pytestmark = pytest.mark.db
DOMAINS = {
    "inventory": ("창고", "창고코드", "창고명"),
    "maintenance": ("설비", "설비코드", "설비명"),
}
WARNING = "영역 상세: 인쇄 글자가 6pt보다 작습니다"


@dataclass(frozen=True)
class _Pdf:
    pdf: bytes
    warnings: tuple[str, ...] = (WARNING,)
    blocked_urls: tuple[str, ...] = ()


def _render(design: DesignState) -> _Pdf:
    content = f"{design.run_id}:{design.revision}:{model_hash(design)}".encode()
    return _Pdf(b"%PDF-1.7\n" + content + b"\n%%EOF")


def _a01(state: GraphState) -> dict[str, Any]:
    (block,) = state["design"].source_requirements
    req = Requirement(
        id="REQ-01", source_id=block.source_id, source_ref=block.source_ref,
        source_text=block.source_text, text=block.source_text, draft_text=block.source_text,
        type="FR", analysis_version=1,
    )  # fmt: skip
    return {"design": state["design"].evolve(requirements=(req,))}


def _a03(state: GraphState) -> dict[str, Any]:
    design = state["design"]
    name, key, label = DOMAINS[design.versions.pack_id]
    entity = Entity.model_validate({
        "id":"ENT-01", "pack":design.versions.pack_id, "name":name, "description":name,
        "req_ids":["REQ-01"], "attributes":[{
            "id":"ATTR-01", "name":key, "data_type":"varchar", "length":10,
            "is_key":True, "nullable":False, "req_ids":["REQ-01"],
        }],
    })  # fmt: skip
    if design.revision:
        entity = entity.evolve(
            attributes=(
                *entity.attributes,
                Attribute(
                    id="ATTR-02",
                    name=label,
                    data_type="varchar",
                    length=200,
                    is_key=False,
                    nullable=True,
                    req_ids=["REQ-01"],
                ),
            )
        )
    functions = tuple(
        f.evolve(entity_ops=({"entity_id": entity.id, "operations": ("C", "R")},))
        for f in design.functions
    )
    return {"design": design.evolve(entities=(entity,), functions=functions)}


def _a02(state: GraphState) -> dict[str, Any]:
    function = Function(
        id="FUNC-01", name="등록", description="대상을 등록한다", req_ids=("REQ-01",)
    )
    return {"design": state["design"].evolve(functions=(function,))}


class _World:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        client: TestClient,
        patch: pytest.MonkeyPatch,
        pack: str,
        render: PdfRenderer,
        native: bool,
    ) -> None:
        self.pool, self.settings, self.client, self.pack = pool, settings, client, pack
        self.rendered: list[int] = []
        self.results: list[Any] = []
        real_factory = main.erd_pdf_renderer

        def factory(config: Settings) -> PdfRenderer:
            delegate = real_factory(config) if native else render

            def capture(design: DesignState) -> Any:
                self.rendered.append(design.revision)
                result = delegate(design)
                self.results.append(result)
                return result

            return capture

        with patch.context() as context:
            context.setattr(
                main,
                "openai_agent_nodes",
                lambda config: {
                    "a01": _a01,
                    "a02": _a02,
                    "a03": _a03,
                    "a09": lambda state: {"router_stage": TargetStage.DATA_MODEL},
                },
            )
            context.setattr(main, "erd_pdf_renderer", factory)
            self.graph = main.create_graph(settings, create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def create(self) -> str:
        name, _, _ = DOMAINS[self.pack]
        text = f"요구사항 ID,요구사항명,상세 내용\nREQ-01,{name} 등록,{name}를 등록한다\n".encode()
        response = self.client.post(
            "/runs", data={"pack": self.pack}, files={"file": ("req.csv", text, "text/csv")}
        )
        assert response.status_code == 202, response.text
        return str(response.json()["run_id"])

    def status(self, run_id: str) -> dict[str, Any]:
        return dict(self.client.get(f"/runs/{run_id}").json())

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return list(
            self.client.get(f"/runs/{run_id}/view", params={"section": "design"}).json()[
                "artifacts"
            ]
        )

    def download(self, run_id: str, revision: int = 0) -> Any:
        return self.client.get(
            f"/runs/{run_id}/artifacts/erd", params={"file_format": "pdf", "revision": revision}
        )

    def answer(self, run_id: str, decision: str) -> Any:
        status = self.status(run_id)
        return self.client.post(
            f"/runs/{run_id}/resume",
            json={
                "interrupt_id": status["interrupt"]["interrupt_id"],
                "expected_revision": status["revision"],
                "response": {
                    "kind": "review",
                    "decision": decision,
                    "feedback": "설계를 확인해 주세요",
                },
            },
        )


@pytest.fixture
def world(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., _World]]:
    worlds = []
    config = os.environ.get("SPECTON_MMDC_PUPPETEER")
    settings = Settings(
        _env_file=None,
        storage_dir=tmp_path,
        require_sql_validation=True,
        enable_erd_pdf=True,
        mermaid_puppeteer_config=Path(config) if config else None,
    )
    with ExitStack() as stack:

        def make(
            pack: str = "inventory",
            *,
            previous: _World | None = None,
            render: PdfRenderer = _render,
            native: bool = False,
        ) -> _World:
            client = stack.enter_context(TestClient(main.create_app(settings, pool)))
            if previous is not None:
                previous.runner.stop()
                client.cookies.update(previous.client.cookies)
                pack = previous.pack
            item = _World(pool, settings, client, monkeypatch, pack, render, native)
            worlds.append(item)
            return item

        yield make
        for item in worlds:
            item.runner.stop()


@pytest.mark.parametrize("pack", DOMAINS)
def test_pdf_is_private_until_approval_and_restart_publishes_identical_bytes(
    world: Callable[..., _World],
    pack: str,
) -> None:
    first = world(pack)
    run_id = first.create()
    first.runner.run_pending()
    assert first.status(run_id)["status"] == "awaiting_review"
    assert first.rendered == [0]
    (pdf,) = [item for item in first.artifacts(run_id) if item["file_format"] == "pdf"]
    assert pdf["approved"] is False and first.download(run_id).status_code == 409
    content = first.results[0].pdf
    assert pdf["hash"] == hashlib.sha256(content).hexdigest()
    with TestClient(main.create_app(first.settings, first.pool)) as other:
        response = other.get(
            f"/runs/{run_id}/artifacts/erd", params={"file_format": "pdf", "revision": 0}
        )
        assert response.status_code == 404
    assert first.answer(run_id, "hold").status_code == 202
    first.runner.run_pending()
    assert first.rendered == [0] and first.download(run_id).status_code == 409
    with first.pool.connection() as conn:
        events = runs.events_after(conn, UUID(run_id), first.client.cookies[SESSION_COOKIE], 0)
    assert sum(event.data.message == WARNING for event in events) == 1

    restarted = world(previous=first)
    assert restarted.answer(run_id, "approve").status_code == 202
    with first.pool.connection() as conn:
        basis = conn.execute(
            "SELECT b.artifact_hash,b.validation_id FROM approval_basis b "
            "JOIN approval p USING(approval_id) "
            "JOIN artifact a USING(artifact_id) WHERE p.run_id=%s AND a.file_format='pdf'",
            (UUID(run_id),),
        ).fetchone()
    assert basis == {"artifact_hash": pdf["hash"], "validation_id": None}
    restarted.runner.run_pending()
    assert restarted.status(run_id)["status"] == "completed" and restarted.rendered == []
    response = restarted.download(run_id)
    assert response.status_code == 200 and response.content == content
    assert response.headers["etag"] == f'"{pdf["hash"]}"'
    assert response.headers["content-type"] == "application/pdf"
    assert "-draft" not in response.headers["content-disposition"]


@pytest.mark.parametrize("pack", DOMAINS)
def test_revision_does_not_publish_the_previous_pdf_candidate(
    world: Callable[..., _World], pack: str
) -> None:
    w = world(pack)
    run_id = w.create()
    w.runner.run_pending()
    original = w.results[0].pdf
    assert w.answer(run_id, "revise").status_code == 202
    w.runner.run_pending()
    assert (w.status(run_id)["status"], w.status(run_id)["revision"]) == ("awaiting_review", 1)
    assert w.rendered == [0, 1] and w.results[1].pdf != original
    assert w.download(run_id, 0).status_code == w.download(run_id, 1).status_code == 409
    assert w.answer(run_id, "approve").status_code == 202
    w.runner.run_pending()
    assert w.download(run_id, 0).status_code == 409
    assert w.download(run_id, 1).content == w.results[1].pdf


@pytest.mark.parametrize("failure", ["blocked", "invalid", "exception"])
def test_renderer_failure_does_not_publish_a_pdf_or_expose_internal_messages(
    world: Callable[..., _World],
    failure: str,
) -> None:
    def render(design: DesignState) -> _Pdf:
        if failure == "exception":
            raise OSError("fixture private renderer details")
        return (
            _Pdf(b"invalid")
            if failure == "invalid"
            else _Pdf(b"%PDF-1.7", blocked_urls=("file:///private/resource",))
        )

    w = world(render=render)
    run_id = w.create()
    w.runner.run_pending()
    current = w.status(run_id)
    assert current["status"] == "failed" and current["error"]["code"] == "INTERNAL"
    assert "private" not in str(current["error"])
    assert not any(item["file_format"] == "pdf" for item in w.artifacts(run_id))
    assert w.download(run_id).status_code == 409


@pytest.mark.parametrize("boundary", ["cancel", "lease"])
def test_cancel_or_lease_loss_blocks_a_late_pdf_candidate(
    world: Callable[..., _World], boundary: str
) -> None:
    def render(design: DesignState) -> _Pdf:
        with w.pool.connection() as conn:
            if boundary == "cancel":
                runs.request_cancel(conn, UUID(run_id), w.client.cookies[SESSION_COOKIE], 0)
            else:
                conn.execute(
                    "UPDATE job_lease SET lease_until=now() WHERE run_id=%s", (UUID(run_id),)
                )
                assert lease.acquire(conn, UUID(run_id), "other-worker", 60)
        return _render(design)

    w = world(render=render)
    run_id = w.create()
    w.runner.run_pending()
    assert w.status(run_id)["status"] == ("cancelled" if boundary == "cancel" else "generating")
    assert not any(item["file_format"] == "pdf" for item in w.artifacts(run_id))
    assert w.download(run_id).status_code == 409


def test_checkpoint_recovery_does_not_render_pdf_twice(
    world: Callable[..., _World],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import specton.runner as runner_module

    first = world()
    run_id = first.create()
    publish = runner_module.publish_artifacts

    def crash(*args: Any, **kwargs: Any) -> None:
        publish(*args, **kwargs)
        if any(item["ref"].file_format == "pdf" for item in args[3].values()):
            first.runner.request_stop()
            raise runner_module._Stop

    monkeypatch.setattr(runner_module, "publish_artifacts", crash)
    first.runner.run_pending()
    assert first.status(run_id)["status"] == "generating" and first.rendered == [0]
    assert first.artifacts(run_id) == []
    monkeypatch.setattr(runner_module, "publish_artifacts", publish)
    restarted = world(previous=first)
    restarted.runner.run_pending()
    assert restarted.status(run_id)["status"] == "awaiting_review" and restarted.rendered == []
    assert restarted.answer(run_id, "approve").status_code == 202
    restarted.runner.run_pending()
    assert restarted.download(run_id).content == first.results[0].pdf


@pytest.mark.parametrize("pack", DOMAINS)
def test_native_mermaid_weasyprint_pdf_approval_and_download(
    world: Callable[..., _World], pack: str
) -> None:
    if os.environ.get("SPECTON_TEST_NATIVE_PDF") != "1":
        pytest.skip("실제 CLI·PDF 도구를 갖춘 환경에서 SPECTON_TEST_NATIVE_PDF=1로 실행")
    assert shutil.which("mmdc") is not None
    w = world(pack, native=True)
    run_id = w.create()
    w.runner.run_pending()
    assert w.status(run_id)["status"] == "awaiting_review", w.status(run_id)
    (result,) = w.results
    assert result.pdf.startswith(b"%PDF-") and len(result.pages) >= 4 and result.blocked_urls == ()
    assert w.download(run_id).status_code == 409
    assert w.answer(run_id, "approve").status_code == 202
    w.runner.run_pending()
    assert w.status(run_id)["status"] == "completed" and w.rendered == [0]
    response = w.download(run_id)
    assert response.status_code == 200 and response.content == result.pdf
