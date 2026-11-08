"""#17: 실제 파일·병렬 그래프·Postgres·승인·다운로드. 실제 DDL·ERD 인계도 확인한다."""

import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.serde.event_hooks import SerdeEvent, register_serde_event_listener

import specton.runner as runner_module
from specton.api.main import create_app
from specton.api.session import SESSION_COOKIE
from specton.artifacts import GeneratedArtifact, artifact_key, write_artifact
from specton.codegen.normalize_step import normalize_design
from specton.config import Settings
from specton.contracts import Entity, Normalized, NormalizedModel, Requirement, RunStatus
from specton.contracts.base import TargetStage
from specton.ddl_adapter import DdlArtifact, create_ddl_artifact
from specton.erd_node import erd_node
from specton.graph import GraphState, Node, build_graph
from specton.persistence.db import Pool, create_checkpointer
from specton.persistence.runs import events_after, request_cancel
from specton.persistence.snapshots import add_artifact
from specton.runner import Runner

pytestmark = pytest.mark.db

OUTPUTS = {
    "ddl": ("sql", b"CREATE TABLE fixture (id bigint PRIMARY KEY);"),
    "erd": ("mmd", b"erDiagram\n  fixture { bigint id PK }"),
    "rtm": ("csv", b"req_id,table\nREQ-01,fixture\n"),
}
Mutate = Callable[[GraphState, GeneratedArtifact], None]


def _normalize(state: GraphState) -> Mapping[str, Any]:
    # 저장 계약 시험을 위한 고정 모델. 실제 정리 알고리즘 시험은 별도 integration에 있다.
    model = NormalizedModel(
        pack="inventory", pack_version="fixture", rules_version="fixture",
        lexicon_digest="fixture", tables=(), foreign_keys=(),
    )  # fmt: skip
    return {"design": state["design"].evolve(normalized=model)}


def _real_normalize(state: GraphState) -> Mapping[str, Any]:
    design = state["design"].evolve(
        requirements=(Requirement(
            id="REQ-01", source_ref={"file_format": "csv", "row": 2}, type="FR",
            text="창고를 등록한다", draft_text="창고를 등록한다", analysis_version=1,
        ),),
        entities=(Entity.model_validate({
            "id": "ENT-01", "pack": "inventory", "name": "창고", "description": "창고",
            "req_ids": ["REQ-01"], "attributes": [{
                "id": "ATTR-01", "name": "창고코드", "data_type": "varchar", "length": 10,
                "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
            }],
        }),),
    )  # fmt: skip
    result = normalize_design(design)
    assert isinstance(result, Normalized), result
    return {"design": design.evolve(normalized=result.model)}


class _World:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        client: TestClient,
        mutate: Mutate | None = None,
        *,
        real_ddl: bool = False,
        real_erd: bool = False,
    ) -> None:
        self.pool, self.settings, self.client, self.mutate = pool, settings, client, mutate
        self.real_ddl, self.real_erd = real_ddl, real_erd
        self.ddl_results: list[DdlArtifact] = []
        self.generated: list[tuple[str, int]] = []
        nodes = {name: self._generator(name) for name in OUTPUTS}
        nodes.update(
            normalize=_real_normalize if real_ddl or real_erd else _normalize,
            rules=self._rules, export=self._export,
            a09=lambda state: {"router_stage": TargetStage.DATA_MODEL},
        )  # fmt: skip
        self.graph = build_graph(nodes, checkpointer=create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def _generator(self, name: str) -> Node:
        def node(state: GraphState) -> Mapping[str, Any]:
            self.generated.append((name, state["design"].revision))
            if name == "ddl" and self.real_ddl:
                result = create_ddl_artifact(
                    state["design"],
                    storage_dir=self.settings.storage_dir,
                    root=self.settings.pack_root,
                )
                self.ddl_results.append(result)
                item = result.generated
            elif name == "erd" and self.real_erd:
                update = erd_node(self.settings.storage_dir)(state)
                (item,) = update["generated_artifacts"].values()
            else:
                file_format, content = OUTPUTS[name]
                item = write_artifact(
                    self.settings.storage_dir,
                    state["design"],
                    name,
                    file_format,
                    b"DRAFT\n" + content,
                )  # type: ignore[arg-type]
            if name == "ddl" and self.mutate is not None:
                self.mutate(state, item)
            return {"generated_artifacts": {artifact_key(item["ref"]): item}}

        return node

    def _rules(self, state: GraphState) -> Mapping[str, Any]:
        assert {ref.kind for ref in state["design"].artifacts} == set(OUTPUTS)
        assert all(ref.revision == state["design"].revision for ref in state["design"].artifacts)
        return {}

    def _export(self, state: GraphState) -> Mapping[str, Any]:
        result = {}
        for name, (file_format, content) in OUTPUTS.items():
            item = write_artifact(
                self.settings.storage_dir,
                state["design"],
                name,
                file_format,
                content,
                approved=True,
            )  # type: ignore[arg-type]
            result[artifact_key(item["ref"])] = item
        item = write_artifact(
            self.settings.storage_dir,
            state["design"],
            "erd",
            "pdf",
            b"%PDF-fixture",
            approved=True,
        )
        result[artifact_key(item["ref"])] = item
        return {"generated_artifacts": result}

    def create(self) -> str:
        response = self.client.post(
            "/runs", data={"pack": "inventory"},
            files={"file": ("req.csv", b"id,text\n1,fixture\n", "text/csv")},
        )  # fmt: skip
        assert response.status_code == 202, response.text
        return str(response.json()["run_id"])

    def status(self, run_id: str) -> RunStatus:
        return RunStatus.model_validate(self.client.get(f"/runs/{run_id}").json())

    def answer(self, run_id: str, decision: str) -> None:
        status = self.status(run_id)
        assert status.interrupt is not None and status.interrupt.kind == "review"
        response = self.client.post(f"/runs/{run_id}/resume", json={
            "interrupt_id": status.interrupt.interrupt_id, "expected_revision": status.revision,
            "response": {"kind": "review", "decision": decision, "feedback": "fixture"},
        })  # fmt: skip
        assert response.status_code == 202, response.text

    def artifacts(self, run_id: str, revision: int = 0) -> list[dict[str, Any]]:
        response = self.client.get(
            f"/runs/{run_id}/view", params={"section": "design", "revision": revision}
        )
        assert response.status_code == 200
        return list(response.json()["artifacts"])

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return [
                event.data.payload
                for event in events_after(
                    conn, UUID(run_id), self.client.cookies[SESSION_COOKIE], 0
                )
                if event.event == "artifact"
            ]

    def download(self, run_id: str, kind: str, file_format: str, revision: int = 0) -> Any:
        return self.client.get(
            f"/runs/{run_id}/artifacts/{kind}",
            params={"file_format": file_format, "revision": revision},
        )


@pytest.fixture
def world(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., _World]]:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    settings = Settings(_env_file=None, storage_dir=tmp_path / "storage")
    worlds: list[_World] = []
    serde_events: list[SerdeEvent] = []
    unregister = register_serde_event_listener(serde_events.append)
    with ExitStack() as stack:

        def make(
            previous: _World | None = None,
            mutate: Mutate | None = None,
            *,
            real_ddl: bool = False,
            real_erd: bool = False,
        ) -> _World:
            client = stack.enter_context(TestClient(create_app(settings, pool)))
            if previous is not None:
                previous.runner.stop()
                client.cookies.update(previous.client.cookies)
            result = _World(pool, settings, client, mutate, real_ddl=real_ddl, real_erd=real_erd)
            worlds.append(result)
            return result

        try:
            yield make
        finally:
            for item in worlds:
                item.runner.stop()
            unregister()
    assert serde_events == []


def test_parallel_drafts_restart_and_approved_downloads(world: Callable[..., _World]) -> None:
    first = world()
    run_id = first.create()
    first.runner.run_pending()
    assert first.status(run_id).status == "awaiting_review"
    drafts = first.artifacts(run_id)
    assert len(drafts) == len(first.events(run_id)) == 3
    paths = list((first.settings.storage_dir / run_id / "r0").iterdir())
    before = {path: path.read_bytes() for path in paths}
    for name, (file_format, content) in OUTPUTS.items():
        response = first.download(run_id, name, file_format)
        assert response.status_code == 200
        assert response.content == b"DRAFT\n" + content
        assert f"specton-{name}-r0-draft.{file_format}" in response.headers["content-disposition"]
        assert response.headers["etag"] == f'"{hashlib.sha256(response.content).hexdigest()}"'
    assert first.download(run_id, "erd", "pdf").status_code == 409

    restarted = world(previous=first)
    restarted.answer(run_id, "approve")
    restarted.runner.run_pending()
    assert restarted.status(run_id).status == "completed"
    assert restarted.generated == []
    refs = restarted.artifacts(run_id)
    assert len(refs) == 4 and all(ref["approved"] for ref in refs)
    assert len(restarted.events(run_id)) == 7  # 3 초안 + 4 승인본, 후속 체크포인트는 중복 없음
    assert all(path.read_bytes() == content for path, content in before.items())
    for name, (file_format, content) in OUTPUTS.items():
        response = restarted.download(run_id, name, file_format)
        assert response.content == content
        assert "-draft" not in response.headers["content-disposition"]
    assert restarted.download(run_id, "erd", "pdf").content == b"%PDF-fixture"
    with TestClient(create_app(restarted.settings, restarted.pool)) as other:
        assert (
            other.get(
                f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": 0}
            ).status_code
            == 404
        )
    with restarted.pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.model_hash, s.normalized_model, count(a.artifact_id) AS total "
            "FROM model_snapshot s JOIN artifact a USING (snapshot_id) "
            "JOIN approval p USING (snapshot_id) WHERE s.run_id = %s "
            "GROUP BY s.snapshot_id",
            (UUID(run_id),),
        ).fetchall()
    assert len(rows) == 1 and rows[0]["total"] == 4
    assert "normalized" in rows[0]["normalized_model"]
    checkpoint = restarted.graph.get_state({"configurable": {"thread_id": run_id}})
    assert {item["model_hash"] for item in checkpoint.values["generated_artifacts"].values()} == {
        rows[0]["model_hash"]
    }
    assert "storage_ref" not in str(refs + restarted.events(run_id))


@pytest.mark.parametrize("real_erd", [False, True])
def test_rework_keeps_old_revision_downloads(world: Callable[..., _World], real_erd: bool) -> None:
    first = world(real_erd=real_erd)
    run_id = first.create()
    first.runner.run_pending()
    old = first.artifacts(run_id)
    first.answer(run_id, "revise")
    first.runner.run_pending()
    assert (first.status(run_id).status, first.status(run_id).revision) == ("awaiting_review", 1)
    assert first.artifacts(run_id) == old
    current = first.artifacts(run_id, 1)
    assert len(current) == 3 and all(ref["revision"] == 1 for ref in current)
    assert len(first.events(run_id)) == 6
    assert first.download(run_id, "ddl", "sql", 0).status_code == 200
    assert first.download(run_id, "ddl", "sql", 1).status_code == 200


@pytest.mark.parametrize("invalid", ["model", "file", "missing", "path", "approval"])
def test_invalid_generation_publishes_no_metadata_or_events(
    world: Callable[..., _World], invalid: str
) -> None:
    def mutate(state: GraphState, item: GeneratedArtifact) -> None:
        if invalid == "model":
            item["model_hash"] = "wrong-model"
        elif invalid == "file":
            (w.settings.storage_dir / item["storage_ref"]).write_bytes(b"corrupted")
        elif invalid == "missing":
            (w.settings.storage_dir / item["storage_ref"]).unlink()
        elif invalid == "path":
            item["storage_ref"] = "../outside.sql"
        elif invalid == "approval":
            item["ref"] = item["ref"].evolve(approved=True)

    w = world(mutate=mutate)
    run_id = w.create()
    w.runner.run_pending()
    status = w.status(run_id)
    assert status.status == "failed" and status.error is not None
    assert status.error.code == "INTERNAL"
    assert w.artifacts(run_id) == w.events(run_id) == []
    response = w.download(run_id, "ddl", "sql")
    assert response.status_code == 409


@pytest.mark.parametrize(("real_ddl", "real_erd"), [(False, False), (True, False), (False, True)])
def test_checkpoint_ahead_of_app_recovers_files_without_regeneration_or_duplicate_events(
    world: Callable[..., _World], monkeypatch: pytest.MonkeyPatch, real_ddl: bool, real_erd: bool
) -> None:
    first = world(real_ddl=real_ddl, real_erd=real_erd)
    run_id = first.create()
    publish = runner_module.publish_artifacts

    def crash(*args: Any, **kwargs: Any) -> None:
        publish(*args, **kwargs)
        if args[3]:
            first.runner.request_stop()
            raise runner_module._Stop  # DB 저장 후 commit 전 프로세스 중단을 재현

    monkeypatch.setattr(runner_module, "publish_artifacts", crash)
    first.runner.run_pending()
    assert first.status(run_id).status == "generating"
    assert first.artifacts(run_id) == first.events(run_id) == []
    assert len(first.generated) == 3
    monkeypatch.setattr(runner_module, "publish_artifacts", publish)
    restarted = world(previous=first, real_ddl=real_ddl, real_erd=real_erd)
    restarted.runner.run_pending()
    assert restarted.status(run_id).status == "awaiting_review"
    assert restarted.generated == []
    assert len(restarted.artifacts(run_id)) == len(restarted.events(run_id)) == 3
    restarted.runner.run_pending()
    assert len(restarted.events(run_id)) == 3


@pytest.mark.parametrize(("real_ddl", "real_erd"), [(False, False), (True, False), (False, True)])
def test_cancel_at_generator_boundary_never_publishes_results(
    world: Callable[..., _World], real_ddl: bool, real_erd: bool
) -> None:
    def cancel(state: GraphState, item: GeneratedArtifact) -> None:
        with w.pool.connection() as conn:
            request_cancel(conn, UUID(state["design"].run_id), w.client.cookies[SESSION_COOKIE], 0)

    w = world(mutate=cancel, real_ddl=real_ddl, real_erd=real_erd)
    run_id = w.create()
    w.runner.run_pending()
    assert w.status(run_id).status == "cancelled"
    assert w.artifacts(run_id) == w.events(run_id) == []


def test_real_ddl_handoff_keeps_bytes_hash_and_model_after_restart(
    world: Callable[..., _World],
) -> None:
    first = world(real_ddl=True)
    run_id = first.create()
    first.runner.run_pending()
    assert first.status(run_id).status == "awaiting_review"
    (result,) = first.ddl_results
    assert result.prepared.validation.status == "unverified"
    ref = result.generated["ref"]
    assert ref.approved is False
    assert b'CREATE TABLE "wrhus"' in result.prepared.sql_bytes
    download = first.download(run_id, "ddl", "sql")
    assert download.content == result.prepared.sql_bytes
    assert download.headers["etag"] == f'"{result.prepared.validation.artifact_hash}"'
    with first.pool.connection() as conn:
        stored = conn.execute(
            "SELECT a.hash, a.storage_ref, a.approval_status, s.model_hash FROM artifact a "
            "JOIN model_snapshot s USING (snapshot_id) "
            "WHERE s.run_id = %s AND s.revision = 0 AND a.kind = 'ddl'",
            (UUID(run_id),),
        ).fetchone()
    assert stored is not None
    assert stored["hash"] == ref.hash == result.prepared.validation.artifact_hash
    assert stored["model_hash"] == result.generated["model_hash"]
    assert stored["storage_ref"] == result.generated["storage_ref"]
    assert stored["approval_status"] == "draft"
    assert len(first.events(run_id)) == 3

    restarted = world(previous=first, real_ddl=True)
    restarted.runner.run_pending()
    assert restarted.status(run_id).status == "awaiting_review"
    assert restarted.generated == []
    assert restarted.ddl_results == []
    assert restarted.download(run_id, "ddl", "sql").content == download.content
    assert len(restarted.events(run_id)) == 3
    assert "storage_ref" not in str(restarted.artifacts(run_id) + restarted.events(run_id))


def test_real_erd_handoff_keeps_bytes_hash_and_model_after_restart(
    world: Callable[..., _World],
) -> None:
    first = world(real_erd=True)
    run_id = first.create()
    first.runner.run_pending()
    assert first.status(run_id).status == "awaiting_review"
    response = first.download(run_id, "erd", "mmd")
    assert response.status_code == 200
    assert response.content.startswith(b"erDiagram\n")
    assert 'wrhus["창고"]' in response.text
    digest = hashlib.sha256(response.content).hexdigest()
    assert response.headers["etag"] == f'"{digest}"'
    assert "-draft.mmd" in response.headers["content-disposition"]
    with first.pool.connection() as conn:
        stored = conn.execute(
            "SELECT a.hash, a.approval_status, s.model_hash FROM artifact a "
            "JOIN model_snapshot s USING (snapshot_id) "
            "WHERE s.run_id = %s AND s.revision = 0 AND a.kind = 'erd'",
            (UUID(run_id),),
        ).fetchone()
    checkpoint = first.graph.get_state({"configurable": {"thread_id": run_id}})
    item = checkpoint.values["generated_artifacts"]["0:erd:mmd"]
    assert stored == {"hash": digest, "approval_status": "draft", "model_hash": item["model_hash"]}

    restarted = world(previous=first, real_erd=True)
    restarted.runner.run_pending()
    assert restarted.status(run_id).status == "awaiting_review"
    assert restarted.generated == []
    assert restarted.download(run_id, "erd", "mmd").content == response.content
    assert len(restarted.events(run_id)) == 3
    assert "storage_ref" not in str(restarted.artifacts(run_id) + restarted.events(run_id))


@pytest.mark.parametrize("stage", ["render_erd", "write_artifact"])
def test_real_erd_failure_is_an_execution_error_without_an_erd_download(
    stage: str, world: Callable[..., _World], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise OSError("fixture failure")

    monkeypatch.setattr(f"specton.erd_node.{stage}", unavailable)
    first = world(real_erd=True)
    run_id = first.create()
    first.runner.run_pending()
    status = first.status(run_id)
    assert status.status == "failed" and status.error is not None
    assert status.error.code == "INTERNAL"
    assert not any(item["kind"] == "erd" for item in first.artifacts(run_id))
    assert first.download(run_id, "erd", "mmd").status_code == 409


def test_approved_artifact_replacement_and_downgrade_are_rejected(
    world: Callable[..., _World], monkeypatch: pytest.MonkeyPatch
) -> None:
    from specton.persistence.errors import InvalidTransitionError

    publish = runner_module.publish_artifacts
    checked: list[bool] = []

    def protect(conn: Any, holder: str, state: Any, generated: Any, root: Path) -> None:
        publish(conn, holder, state, generated, root)
        item = generated.get("0:ddl:sql")
        if item is None or not item["ref"].approved or checked:
            return
        run_id = UUID(state.run_id)
        assert add_artifact(conn, run_id, holder, item["ref"], item["storage_ref"]) is False
        for ref, path in (
            (item["ref"].evolve(hash="changed"), item["storage_ref"]),
            (item["ref"], "other.sql"),
            (item["ref"].evolve(approved=False), item["storage_ref"]),
        ):
            with pytest.raises(InvalidTransitionError):
                add_artifact(conn, run_id, holder, ref, path)
        checked.append(True)

    monkeypatch.setattr(runner_module, "publish_artifacts", protect)
    w = world()
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, "approve")
    w.runner.run_pending()
    assert w.status(run_id).status == "completed"
    assert checked == [True]
    assert len(w.events(run_id)) == 7
    assert w.download(run_id, "ddl", "sql").content == OUTPUTS["ddl"][1]
