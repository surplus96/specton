"""R1 #17·#167: 실제 API 그래프·DDL·SQL 검증·저장·재시작·승인·같은 해시 다운로드."""

import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from specton.api import main
from specton.config import Settings
from specton.contracts import (
    VALIDATION_STEPS,
    BranchResult,
    Entity,
    Requirement,
    SqlValidation,
    ValidationIssue,
    ValidationStep,
)
from specton.ddl_node import ddl_node
from specton.graph import REVIEWERS, GraphState
from specton.persistence.db import Pool, create_checkpointer
from specton.persistence.validations import current_validation
from specton.runner import Runner

pytestmark = pytest.mark.db
CSV = "요구사항 ID,요구사항명,상세 내용\nINV-001,창고 등록,창고를 등록한다\n".encode()


def _requirements(state: GraphState) -> dict[str, Any]:
    (block,) = state["design"].source_requirements
    req = Requirement(
        id="REQ-01", source_id=block.source_id, source_ref=block.source_ref,
        source_text=block.source_text, text="창고를 등록한다", draft_text="창고를 등록한다",
        type="FR", analysis_version=1,
    )  # fmt: skip
    return {"design": state["design"].evolve(requirements=(req,))}


def _entities(state: GraphState) -> dict[str, Any]:
    entity = Entity.model_validate({
        "id": "ENT-01", "pack": "inventory", "name": "창고", "description": "창고",
        "req_ids": ["REQ-01"], "attributes": [{
            "id": "ATTR-01", "name": "창고코드", "data_type": "varchar", "length": 10,
            "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
        }],
    })  # fmt: skip
    return {"design": state["design"].evolve(entities=(entity,))}


def _result(sql: bytes, status: str) -> SqlValidation:
    values = {
        "failed": ("passed", "passed", "failed", "passed", "passed"),
        "error": ("passed", "passed", "error", "not_run", "not_run"),
        "unverified": ("passed", "passed", "not_run", "not_run", "not_run"),
    }[status]
    from specton.persistence.validations import REQUIRED_VERSIONS

    return SqlValidation(
        status=status, artifact_hash=hashlib.sha256(sql).hexdigest(), **REQUIRED_VERSIONS,
        steps=tuple(
            ValidationStep(
                name=name, status=value,
                issues=(ValidationIssue(code="fixture_error"),)
                if value in ("failed", "error") else (),
            )
            for name, value in zip(VALIDATION_STEPS, values, strict=True)
        ),
    )  # fmt: skip


class _Pipeline:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        client: TestClient,
        patch: pytest.MonkeyPatch,
        status: str,
    ) -> None:
        self.pool, self.settings, self.client = pool, settings, client
        self.calls: list[bytes] = []
        self.reviewed: list[str] = []

        def review(name: str) -> Callable[[GraphState], Mapping[str, Any]]:
            def node(state: GraphState) -> Mapping[str, Any]:
                self.reviewed.append(name)
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

        def unexpected(state: GraphState) -> Mapping[str, Any]:
            pytest.fail("SQL 검증 실패를 A09·자동 설계 재작업으로 보내면 안 됩니다")

        nodes = {"a01": _requirements, "a03": _entities, "a09": unexpected}
        nodes.update({name: review(name) for name in REVIEWERS})
        with patch.context() as context:
            context.setattr(main, "openai_agent_nodes", lambda settings: nodes)
            if status != "real":

                def validate(sql: bytes) -> SqlValidation:
                    self.calls.append(sql)
                    return _result(sql, status)

                context.setattr(
                    main, "ddl_node", lambda settings: ddl_node(settings, validate=validate)
                )
            self.graph = main.create_graph(settings, create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def create(self) -> str:
        response = self.client.post(
            "/runs", data={"pack": "inventory"}, files={"file": ("req.csv", CSV, "text/csv")}
        )
        assert response.status_code == 202
        return str(response.json()["run_id"])

    def view(self, run_id: str) -> dict[str, Any]:
        response = self.client.get(f"/runs/{run_id}/view", params={"section": "design"})
        assert response.status_code == 200
        return dict(response.json())

    def approve(self, run_id: str) -> Any:
        status = self.client.get(f"/runs/{run_id}").json()
        return self.client.post(
            f"/runs/{run_id}/resume",
            json={
                "interrupt_id": status["interrupt"]["interrupt_id"],
                "expected_revision": status["revision"],
                "response": {"kind": "review", "decision": "approve", "feedback": ""},
            },
        )


@pytest.fixture
def pipeline(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., _Pipeline]]:
    settings = Settings(_env_file=None, storage_dir=tmp_path, require_sql_validation=True)
    runners = []
    with ExitStack() as stack:

        def make(status: str = "real", previous: _Pipeline | None = None) -> _Pipeline:
            client = stack.enter_context(TestClient(main.create_app(settings, pool)))
            if previous is not None:
                previous.runner.stop()
                client.cookies.update(previous.client.cookies)
            item = _Pipeline(pool, settings, client, monkeypatch, status)
            runners.append(item.runner)
            return item

        yield make
        for runner in runners:
            runner.stop()


def test_real_api_ddl_validation_restart_approve_and_download_same_hash(
    pipeline: Callable[..., _Pipeline],
) -> None:
    first = pipeline()
    run_id = first.create()
    first.runner.run_pending()
    assert first.client.get(f"/runs/{run_id}").json()["status"] == "awaiting_review"
    assert set(first.reviewed) == set(REVIEWERS)
    with first.pool.connection() as conn:
        stored = current_validation(conn, UUID(run_id), 0)
    assert stored is not None and stored.result.status == "passed"
    assert all(step.status == "passed" for step in stored.result.steps)
    draft = first.client.get(
        f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": 0}
    )
    assert draft.status_code == 200
    assert hashlib.sha256(draft.content).hexdigest() == stored.result.artifact_hash
    sql = next(a for a in first.view(run_id)["artifacts"] if a["kind"] == "ddl")
    assert sql["validation"]["status"] == "passed" and sql["validation"]["validated_at"]

    restarted = pipeline(previous=first)
    assert restarted.approve(run_id).status_code == 202
    restarted.runner.run_pending()
    assert restarted.client.get(f"/runs/{run_id}").json()["status"] == "completed"
    assert restarted.reviewed == []
    approved = restarted.client.get(
        f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": 0}
    )
    assert (
        approved.content == draft.content
        and "-draft" not in approved.headers["content-disposition"]
    )
    assert all(item["approved"] for item in restarted.view(run_id)["artifacts"])
    with first.pool.connection() as conn:
        replay = current_validation(conn, UUID(run_id), 0)
        basis = conn.execute(
            "SELECT b.artifact_hash, b.validation_id FROM approval_basis b "
            "JOIN approval p USING (approval_id) JOIN artifact a USING (artifact_id) "
            "WHERE p.run_id = %s AND a.kind = 'ddl'",
            (UUID(run_id),),
        ).fetchone()
    assert replay == stored
    assert basis == {
        "artifact_hash": stored.result.artifact_hash,
        "validation_id": stored.validation_id,
    }


@pytest.mark.parametrize("status", ["failed", "unverified", "error"])
def test_sql_failure_is_saved_but_never_approved_or_auto_reworked(
    pipeline: Callable[..., _Pipeline],
    status: str,
) -> None:
    w = pipeline(status)
    run_id = w.create()
    w.runner.run_pending()
    current = w.client.get(f"/runs/{run_id}").json()
    assert current["status"] == ("failed" if status == "error" else "awaiting_review")
    assert w.reviewed == [] and len(w.calls) == 1
    with w.pool.connection() as conn:
        stored = current_validation(conn, UUID(run_id), 0)
        approvals = conn.execute("SELECT count(*) AS n FROM approval").fetchone()
    assert stored is not None and stored.result.status == status
    assert approvals is not None and approvals["n"] == 0
    downloaded = w.client.get(
        f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": 0}
    )
    assert downloaded.content == w.calls[0]
    assert stored.result.artifact_hash == hashlib.sha256(downloaded.content).hexdigest()
    if status != "error":
        assert w.approve(run_id).status_code == 422
        assert w.client.get(f"/runs/{run_id}").json()["status"] == "awaiting_review"
        forced = w.graph.invoke(
            Command(resume={"decision": "approve"}),
            {"configurable": {"thread_id": run_id}},
        )
        assert forced["design"].status == "awaiting_review"
        assert all(not item["ref"].approved for item in forced["generated_artifacts"].values())
    else:
        assert current["error"]["code"] == "INTERNAL"
        assert "fixture_error" not in str(current["error"])


@pytest.mark.parametrize("alteration", ["sql_bytes", "unapproved_pdf"])
def test_export_rejects_bytes_or_files_outside_the_approval_basis(
    pipeline: Callable[..., _Pipeline],
    monkeypatch: pytest.MonkeyPatch,
    alteration: str,
) -> None:
    from specton.artifacts import artifact_key, write_artifact
    from specton.export_node import export_node

    def export_factory(root: Path) -> Callable[[GraphState], Mapping[str, Any]]:
        export = export_node(root)

        def changed(state: GraphState) -> Mapping[str, Any]:
            update = dict(export(state))
            if alteration == "sql_bytes":
                item = write_artifact(
                    root, state["design"], "ddl", "sql", b"-- changed after approval", approved=True
                )
            else:
                item = write_artifact(
                    root, state["design"], "erd", "pdf", b"%PDF-unapproved", approved=True
                )
            update["generated_artifacts"][artifact_key(item["ref"])] = item
            return update

        return changed

    monkeypatch.setattr(main, "export_node", export_factory)
    w = pipeline()
    run_id = w.create()
    w.runner.run_pending()
    before = w.view(run_id)["artifacts"]
    assert w.approve(run_id).status_code == 202
    w.runner.run_pending()
    assert w.client.get(f"/runs/{run_id}").json()["status"] == "failed"
    assert w.view(run_id)["artifacts"] == before  # SQL·ERD 게시도 같은 트랜잭션에서 롤백


def test_error_checkpoint_restart_saves_the_original_attempt_then_fails(
    pipeline: Callable[..., _Pipeline],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import specton.runner as runner_module

    first = pipeline("error")
    run_id = first.create()
    publish = runner_module.publish_validation_attempts

    def crash(*args: Any, **kwargs: Any) -> None:
        publish(*args, **kwargs)
        if args[3]:
            first.runner.request_stop()
            raise runner_module._Stop

    monkeypatch.setattr(runner_module, "publish_validation_attempts", crash)
    first.runner.run_pending()
    assert first.client.get(f"/runs/{run_id}").json()["status"] == "generating"
    checkpoint = first.graph.get_state({"configurable": {"thread_id": run_id}})
    (attempt,) = checkpoint.values["validation_attempts"].values()
    with first.pool.connection() as conn:
        assert current_validation(conn, UUID(run_id), 0) is None
    monkeypatch.setattr(runner_module, "publish_validation_attempts", publish)
    restarted = pipeline("error", previous=first)
    restarted.runner.run_pending()
    assert restarted.client.get(f"/runs/{run_id}").json()["status"] == "failed"
    assert restarted.calls == []
    with first.pool.connection() as conn:
        stored = current_validation(conn, UUID(run_id), 0)
        count = conn.execute("SELECT count(*) AS n FROM artifact_validation").fetchone()
    assert stored is not None and stored.result.status == "error"
    assert stored.validation_id == UUID(attempt["validation_id"])
    assert stored.validated_at == attempt["validated_at"]
    assert count is not None and count["n"] == 1


def test_generation_error_does_not_fabricate_sql_or_validation_records(
    pipeline: Callable[..., _Pipeline],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("fixture generator failure")

    monkeypatch.setattr("specton.ddl_adapter.generate_ddl", unavailable)
    w = pipeline()
    run_id = w.create()
    w.runner.run_pending()
    assert w.client.get(f"/runs/{run_id}").json()["status"] == "failed"
    assert not any(item["kind"] == "ddl" for item in w.view(run_id)["artifacts"])
    with w.pool.connection() as conn:
        row = conn.execute("SELECT count(*) AS n FROM artifact_validation").fetchone()
    assert row is not None and row["n"] == 0
