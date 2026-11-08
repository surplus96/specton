"""실제 API의 기능 명세·RTM 생성, 원문 추적, 저장·승인·다운로드·복구 (#17)."""

import csv
import hashlib
import io
import json
import os
import shutil
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from specton.api import main
from specton.api.session import SESSION_COOKIE
from specton.codegen.manifest import build_manifest, render_manifest
from specton.config import Settings
from specton.contracts import BranchResult, Entity, Function, Requirement
from specton.contracts.base import TargetStage
from specton.graph import REVIEWERS, GraphState
from specton.model_hash import model_hash
from specton.persistence import lease, runs
from specton.persistence.db import Pool, create_checkpointer
from specton.runner import Runner

pytestmark = pytest.mark.db
DOMAINS = {
    "inventory": ("창고", "창고코드", "창고명"),
    "maintenance": ("설비", "설비코드", "설비명"),
}
DOCUMENTS = (("functions", "md"), ("rtm", "xlsx"), ("rtm", "csv"))


def _requirements(state: GraphState) -> Mapping[str, Any]:
    (source,) = [s for s in state["design"].source_requirements if s.analysable]
    name = DOMAINS[state["design"].versions.pack_id][0]
    requirements = tuple(
        Requirement(
            id=f"REQ-{n:02}", source_id=source.source_id, source_ref=source.source_ref,
            source_text=source.source_text, text=f"{name}를 {verb}한다",
            draft_text=f"{name}를 {verb}한다", type="FR", analysis_version=1,
        )
        for n, verb in enumerate(("등록", "조회"), 1)
    )  # fmt: skip
    return {"design": state["design"].evolve(requirements=requirements)}


def _functions(state: GraphState) -> Mapping[str, Any]:
    name = DOMAINS[state["design"].versions.pack_id][0]
    function = Function(
        id="FUNC-01", name=f"{name} 등록", description=f"{name}를 등록한다",
        req_ids=("REQ-01",), priority="Must", priority_source="explicit",
        priority_rationale="등록 요구",
    )  # fmt: skip
    return {"design": state["design"].evolve(functions=(function,))}


def _entities(state: GraphState, *, keyed: bool = True) -> Mapping[str, Any]:
    design = state["design"]
    name, key, label = DOMAINS[design.versions.pack_id]
    attributes = [
        {
            "id": "ATTR-01",
            "name": key,
            "data_type": "varchar",
            "length": 10,
            "is_key": keyed,
            "nullable": False,
            "req_ids": ["REQ-01"],
        }
    ]
    if design.revision:
        attributes.append(
            {
                "id": "ATTR-02",
                "name": label,
                "data_type": "varchar",
                "length": 200,
                "is_key": False,
                "nullable": True,
                "req_ids": ["REQ-01"],
            }
        )
    entity = Entity.model_validate({
        "id": "ENT-01", "pack": design.versions.pack_id, "name": name, "description": name,
        "attributes": attributes, "req_ids": ["REQ-01"],
    })  # fmt: skip
    functions = tuple(
        f.evolve(entity_ops=({"entity_id": entity.id, "operations": ("C", "R")},))
        for f in design.functions
    )
    return {"design": design.evolve(entities=(entity,), functions=functions)}


class _World:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        client: TestClient,
        patch: pytest.MonkeyPatch,
        pack: str,
        keyed: bool,
        after_documents: Callable[[GraphState], None] | None,
    ) -> None:
        self.pool, self.settings, self.client, self.pack = pool, settings, client, pack
        self.generated: list[int] = []
        factory = main.document_node

        def documents(root: Path) -> Callable[[GraphState], Mapping[str, Any]]:
            generate = factory(root)

            def node(state: GraphState) -> Mapping[str, Any]:
                self.generated.append(state["design"].revision)
                update = generate(state)
                if after_documents:
                    after_documents(state)
                return update

            return node

        def review(name: str) -> Callable[[GraphState], Mapping[str, Any]]:
            def node(state: GraphState) -> Mapping[str, Any]:
                return {
                    "branches": {
                        name: BranchResult(
                            branch=name,
                            revision=state["design"].revision,
                            ok=True,
                        )
                    }
                }

            return node

        with patch.context() as context:
            context.setattr(
                main,
                "openai_agent_nodes",
                lambda config: {
                    "a01": _requirements,
                    "a02": _functions,
                    "a03": lambda state: _entities(state, keyed=keyed),
                    "a09": lambda state: {"router_stage": TargetStage.DATA_MODEL},
                    **{name: review(name) for name in REVIEWERS},
                },
            )
            context.setattr(main, "document_node", documents)
            self.graph = main.create_graph(settings, create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def create(self) -> str:
        name = DOMAINS[self.pack][0]
        buffer = io.StringIO()
        csv.writer(buffer).writerows(
            [
                ["요구사항 ID", "요구사항명", "상세 내용"],
                ["SFR-001", f"{name} 관리", f"{name}를 등록하고 조회한다"],
                ["", "=1+1", ""],  # ID 없는 원문을 제외해도 RTM에서는 원문을 보존한다
                ["META-001", "", ""],  # 원문 없는 블록은 확인 후 분석에서 제외한다
            ]
        )
        response = self.client.post(
            "/runs",
            data={"pack": self.pack},
            files={"file": ("req.csv", buffer.getvalue().encode(), "text/csv")},
        )
        assert response.status_code == 202, response.text
        return str(response.json()["run_id"])

    def status(self, run_id: str) -> dict[str, Any]:
        return dict(self.client.get(f"/runs/{run_id}").json())

    def design(self, run_id: str) -> Any:
        return self.graph.get_state({"configurable": {"thread_id": run_id}}).values["design"]

    def answer(self, run_id: str, response: dict[str, Any]) -> Any:
        current = self.status(run_id)
        return self.client.post(
            f"/runs/{run_id}/resume",
            json={
                "interrupt_id": current["interrupt"]["interrupt_id"],
                "expected_revision": current["revision"],
                "response": response,
            },
        )

    def review(self, run_id: str, decision: str) -> Any:
        return self.answer(
            run_id,
            {
                "kind": "review",
                "decision": decision,
                "feedback": "설계를 확인해 주세요" if decision == "revise" else "",
            },
        )

    def prepare(self, run_id: str, *, final: str = "awaiting_review") -> None:
        self.runner.run_pending()
        assert self.status(run_id)["status"] == "awaiting_input"
        source = next(s for s in self.design(run_id).source_requirements if s.source_text == "=1+1")
        assert (
            self.answer(
                run_id,
                {
                    "kind": "extraction",
                    "confirmed": True,
                    "excluded_blocks": [{"block_id": source.block_id, "reason": "안내 문단"}],
                },
            ).status_code
            == 202
        )
        self.runner.run_pending()
        assert self.status(run_id)["status"] == "awaiting_requirements"
        assert self.answer(run_id, {"kind": "requirements", "answers": []}).status_code == 202
        self.runner.run_pending()
        assert self.status(run_id)["status"] == final, self.status(run_id)

    def download(self, run_id: str, kind: str, file_format: str, revision: int = 0) -> Any:
        return self.client.get(
            f"/runs/{run_id}/artifacts/{kind}",
            params={
                "file_format": file_format,
                "revision": revision,
            },
        )

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return list(
            self.client.get(f"/runs/{run_id}/view", params={"section": "design"}).json()[
                "artifacts"
            ]
        )


@pytest.fixture
def world(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., _World]]:
    config = os.environ.get("SPECTON_MMDC_PUPPETEER")
    settings = Settings(
        _env_file=None,
        storage_dir=tmp_path,
        require_sql_validation=True,
        mermaid_puppeteer_config=Path(config) if config else None,
    )
    worlds = []
    with ExitStack() as stack:

        def make(
            pack: str = "inventory",
            *,
            previous: _World | None = None,
            keyed: bool = True,
            after_documents: Callable[[GraphState], None] | None = None,
            pdf: bool = False,
        ) -> _World:
            current = (
                previous.settings
                if previous
                else settings.model_copy(update={"enable_erd_pdf": pdf})
            )
            client = stack.enter_context(TestClient(main.create_app(current, pool)))
            if previous:
                previous.runner.stop()
                client.cookies.update(previous.client.cookies)
                pack = previous.pack
            item = _World(pool, current, client, monkeypatch, pack, keyed, after_documents)
            worlds.append(item)
            return item

        yield make
        for item in worlds:
            item.runner.stop()


@pytest.mark.parametrize("pack", DOMAINS)
def test_documents_trace_sources_and_are_approved_as_identical_bytes(
    world: Callable[..., _World], pack: str
) -> None:
    first = world(pack)
    run_id = first.create()
    first.prepare(run_id)
    design = first.design(run_id)
    digest = model_hash(design)
    content = {}
    for kind, fmt in DOCUMENTS:
        response = first.download(run_id, kind, fmt)
        assert response.status_code == 200 and "-draft" in response.headers["content-disposition"]
        content[kind, fmt] = response.content
    markdown = content["functions", "md"].decode()
    assert digest in markdown and design.versions.pack_version in markdown
    assert "FUNC-01" in markdown and "REQ-01" in markdown and "C R" in markdown
    rows = list(csv.reader(io.StringIO(content["rtm", "csv"].decode("utf-8-sig"))))
    assert [row[9] for row in rows[1:]] == [
        "연결",
        "미연결",
        "제외",
        "확인(원문 없음)",
    ]
    assert rows[2][6] == "" and rows[3][4:] == [
        "'=1+1",
        "",
        "",
        "",
        "",
        "제외",
        "안내 문단",
    ]
    book = load_workbook(io.BytesIO(content["rtm", "xlsx"]))
    assert book["RTM"]["E4"].value == "=1+1" and book["RTM"]["E4"].data_type == "s"
    meta = dict(book["문서 정보"].iter_rows(min_row=2, values_only=True))
    assert meta["모델 해시 (model_hash)"] == digest
    assert (meta["제외 건수"], meta["확인(원문 없음) 건수"]) == (1, 1)
    assert len(first.artifacts(run_id)) == 5
    with TestClient(main.create_app(first.settings, first.pool)) as other:
        for kind, fmt in DOCUMENTS:
            assert (
                other.get(
                    f"/runs/{run_id}/artifacts/{kind}",
                    params={
                        "file_format": fmt,
                        "revision": 0,
                    },
                ).status_code
                == 404
            )
    assert first.review(run_id, "hold").status_code == 202
    first.runner.run_pending()
    assert first.generated == [0]
    restarted = world(previous=first)
    assert restarted.review(run_id, "approve").status_code == 202
    restarted.runner.run_pending()
    assert restarted.status(run_id)["status"] == "completed" and restarted.generated == []
    for kind, fmt in DOCUMENTS:
        response = restarted.download(run_id, kind, fmt)
        assert response.content == content[kind, fmt]
        assert "-draft" not in response.headers["content-disposition"]
        assert response.headers["etag"] == f'"{hashlib.sha256(response.content).hexdigest()}"'
    with first.pool.connection() as conn:
        basis = conn.execute(
            "SELECT a.kind,a.file_format,b.artifact_hash,b.validation_id FROM approval_basis b "
            "JOIN approval p USING(approval_id) JOIN artifact a USING(artifact_id) "
            "WHERE p.run_id=%s",
            (UUID(run_id),),
        ).fetchall()
    assert len(basis) == 5
    for row in basis:
        key = (row["kind"], row["file_format"])
        if key in content:
            assert row["artifact_hash"] == hashlib.sha256(content[key]).hexdigest()
            assert row["validation_id"] is None


@pytest.mark.parametrize("pack", DOMAINS)
def test_rework_keeps_previous_drafts_and_approves_only_current_revision(
    world: Callable[..., _World], pack: str
) -> None:
    w = world(pack)
    run_id = w.create()
    w.prepare(run_id)
    before = {key: w.download(run_id, *key).content for key in DOCUMENTS}
    assert w.review(run_id, "revise").status_code == 202
    w.runner.run_pending()
    assert (w.status(run_id)["status"], w.status(run_id)["revision"]) == ("awaiting_review", 1)
    assert w.generated == [0, 1]
    after = {key: w.download(run_id, *key, revision=1).content for key in DOCUMENTS}
    assert after["functions", "md"] != before["functions", "md"]
    assert after["rtm", "xlsx"] != before["rtm", "xlsx"]
    assert w.review(run_id, "approve").status_code == 202
    w.runner.run_pending()
    for key in DOCUMENTS:
        assert w.download(run_id, *key, revision=1).content == after[key]
        old = w.download(run_id, *key)
        assert old.content == before[key] and "-draft" in old.headers["content-disposition"]


def test_existing_review_checkpoint_does_not_generate_new_documents_retroactively(
    world: Callable[..., _World], monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as old_version:
        old_version.setattr(main, "document_node", lambda root: lambda state: {})
        first = world()
    run_id = first.create()
    first.prepare(run_id)
    assert len(first.artifacts(run_id)) == 2

    restarted = world(previous=first)
    assert restarted.review(run_id, "approve").status_code == 202
    restarted.runner.run_pending()
    assert restarted.status(run_id)["status"] == "completed"
    assert restarted.generated == [] and len(restarted.artifacts(run_id)) == 2
    for key in DOCUMENTS:
        assert restarted.download(run_id, *key).status_code == 409


@pytest.mark.parametrize("pack", DOMAINS)
def test_failed_normalization_never_calls_document_generators(
    world: Callable[..., _World], pack: str
) -> None:
    w = world(pack, keyed=False)
    run_id = w.create()
    w.prepare(run_id)
    assert w.generated == [] and w.design(run_id).normalized is None
    assert w.review(run_id, "approve").status_code == 422
    for key in DOCUMENTS:
        assert w.download(run_id, *key).status_code == 409


@pytest.mark.parametrize("boundary", ["cancel", "lease"])
def test_late_document_result_is_not_published_after_cancel_or_lease_loss(
    world: Callable[..., _World], boundary: str
) -> None:
    def after(state: GraphState) -> None:
        with w.pool.connection() as conn:
            if boundary == "cancel":
                runs.request_cancel(conn, UUID(run_id), w.client.cookies[SESSION_COOKIE], 0)
            else:
                conn.execute(
                    "UPDATE job_lease SET lease_until=now() WHERE run_id=%s", (UUID(run_id),)
                )
                assert lease.acquire(conn, UUID(run_id), "other-worker", 60)

    w = world(after_documents=after)
    run_id = w.create()
    w.prepare(run_id, final="cancelled" if boundary == "cancel" else "generating")
    for key in DOCUMENTS:
        assert w.download(run_id, *key).status_code == 409


@pytest.mark.parametrize("part", ["create_function_spec_artifact", "create_rtm_artifacts"])
def test_generator_error_preserves_completed_sql_without_publishing_partial_documents(
    world: Callable[..., _World], monkeypatch: pytest.MonkeyPatch, part: str
) -> None:
    from specton import document_node

    written = Event()
    w = world()
    original = w.graph.checkpointer.put_writes

    def observe(config: Any, writes: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(config, writes, *args, **kwargs)
        if any(key == "validation_attempts" and value for key, value in writes):
            written.set()
        return result

    def fail(*args: Any, **kwargs: Any) -> Any:
        assert written.wait(10)
        raise OSError("fixture private document renderer failure")

    monkeypatch.setattr(w.graph.checkpointer, "put_writes", observe)
    monkeypatch.setattr(document_node, part, fail)
    run_id = w.create()
    w.prepare(run_id, final="failed")
    assert "private" not in str(w.status(run_id)["error"])
    assert w.download(run_id, "ddl", "sql").status_code == 200
    for key in DOCUMENTS:
        assert w.download(run_id, *key).status_code == 409


@pytest.mark.parametrize("pack", DOMAINS)
def test_checkpoint_replay_does_not_regenerate_or_duplicate_document_events(
    world: Callable[..., _World], monkeypatch: pytest.MonkeyPatch, pack: str
) -> None:
    import specton.runner as runner_module

    first = world(pack)
    original = runner_module.publish_artifacts

    def crash(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        if any(item["ref"].kind == "rtm" for item in args[3].values()):
            first.runner.request_stop()
            raise runner_module._Stop

    monkeypatch.setattr(runner_module, "publish_artifacts", crash)
    run_id = first.create()
    first.prepare(run_id, final="generating")
    assert first.generated == [0] and first.artifacts(run_id) == []
    monkeypatch.setattr(runner_module, "publish_artifacts", original)
    restarted = world(previous=first)
    restarted.runner.run_pending()
    assert restarted.status(run_id)["status"] == "awaiting_review" and restarted.generated == []
    assert len(restarted.artifacts(run_id)) == 5
    with restarted.pool.connection() as conn:
        events = runs.events_after(conn, UUID(run_id), restarted.client.cookies[SESSION_COOKIE], 0)
    assert sum(e.event == "artifact" for e in events) == 5


@pytest.mark.parametrize("key", DOCUMENTS)
def test_modified_document_cannot_be_promoted_after_approval(
    world: Callable[..., _World], key: tuple[str, str]
) -> None:
    w = world()
    run_id = w.create()
    w.prepare(run_id)
    assert w.review(run_id, "approve").status_code == 202
    with w.pool.connection() as conn:
        stored = conn.execute(
            "SELECT a.storage_ref FROM artifact a JOIN model_snapshot s USING(snapshot_id) "
            "WHERE s.run_id=%s AND s.revision=0 AND a.kind=%s AND a.file_format=%s",
            (UUID(run_id), *key),
        ).fetchone()
    assert stored is not None
    (w.settings.storage_dir / stored["storage_ref"]).write_bytes(b"changed after approval")
    w.runner.run_pending()
    assert w.status(run_id)["status"] == "failed"
    assert all(not item["approved"] for item in w.artifacts(run_id))


@pytest.mark.parametrize("pack", DOMAINS)
@pytest.mark.parametrize("broken", [False, True])
def test_native_all_outputs_match_manifest_and_rule07_blocks_failed_sql(
    world: Callable[..., _World], monkeypatch: pytest.MonkeyPatch, pack: str, broken: bool
) -> None:
    """실제 6개 출력·SQL 결함·최종 승인과 manifest의 모델/바이트 정합성을 함께 확인한다."""
    if os.environ.get("SPECTON_TEST_NATIVE_PDF") != "1":
        pytest.skip("실제 PDF 도구 환경에서 SPECTON_TEST_NATIVE_PDF=1로 실행")
    assert shutil.which("mmdc") is not None
    from specton import ddl_adapter

    original = ddl_adapter.generate_ddl
    calls = 0

    def generate(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if broken and calls == 1:
            # 문법·허용 문장은 통과하고 실제 PostgreSQL 실행에서 실패하는 정밀도다.
            sql = result.sql.replace("varchar(10)", "numeric(1001)", 1)
            assert sql != result.sql
            return result.model_copy(update={"sql": sql})
        return result

    monkeypatch.setattr(ddl_adapter, "generate_ddl", generate)
    w = world(pack, pdf=True)
    run_id = w.create()
    w.prepare(run_id)
    if broken:
        design = w.design(run_id)
        assert design.revision == 0 and not design.branch_results
        (finding,) = [f for f in design.findings if f.rule_code == "RULE-07"]
        assert finding.severity == "critical" and finding.target_stage is None
        assert [(t.kind, t.id) for t in finding.targets] == [("entity", "ENT-01")]
        assert w.review(run_id, "approve").status_code == 422
        assert all(not a["approved"] for a in w.artifacts(run_id))
        assert w.download(run_id, "erd", "pdf").status_code == 409
        assert w.review(run_id, "revise").status_code == 202
        w.runner.run_pending()
        assert w.status(run_id)["status"] == "awaiting_review"

    config = {"configurable": {"thread_id": run_id}}
    state = w.graph.get_state(config).values
    design = state["design"]
    assert design.revision == int(broken) and not design.findings
    items = [
        a for a in state["generated_artifacts"].values() if a["ref"].revision == design.revision
    ]
    expected = {("ddl", "sql"), ("erd", "mmd"), ("erd", "pdf"), *DOCUMENTS}
    draft = build_manifest(design, items)
    assert draft["approved"] is False
    assert {(f["kind"], f["file_format"]) for f in draft["files"]} == expected
    assert draft["model_hash"] == model_hash(design)
    assert draft["source_hash"] == design.versions.document_hash
    assert draft["pack_version"] == design.versions.pack_version
    assert json.loads(render_manifest(draft)) == draft
    assert render_manifest(build_manifest(design, reversed(items))) == render_manifest(draft)
    assert w.download(run_id, "erd", "pdf", design.revision).status_code == 409

    # 보류·재시작 후에도 같은 후보와 manifest 입력을 사용한다.
    assert w.review(run_id, "hold").status_code == 202
    w.runner.run_pending()
    restarted = world(previous=w)
    assert restarted.review(run_id, "approve").status_code == 202
    restarted.runner.run_pending()
    assert restarted.status(run_id)["status"] == "completed" and restarted.generated == []
    state = restarted.graph.get_state(config).values
    approved = build_manifest(
        state["design"],
        [a for a in state["generated_artifacts"].values() if a["ref"].revision == design.revision],
    )
    assert approved == {**draft, "approved": True}
    for item in approved["files"]:
        response = restarted.download(run_id, item["kind"], item["file_format"], design.revision)
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == item["hash"]
        assert "-draft" not in response.headers["content-disposition"]
    with w.pool.connection() as conn:
        rows = conn.execute(
            "SELECT a.kind,a.file_format,b.artifact_hash,b.validation_id FROM approval_basis b "
            "JOIN approval p USING(approval_id) JOIN artifact a USING(artifact_id) "
            "WHERE p.run_id=%s",
            (UUID(run_id),),
        ).fetchall()
    assert len(rows) == 6
    assert {(r["kind"], r["file_format"], r["artifact_hash"]) for r in rows} == {
        (f["kind"], f["file_format"], f["hash"]) for f in approved["files"]
    }
    assert all((r["validation_id"] is not None) == (r["kind"] == "ddl") for r in rows)
