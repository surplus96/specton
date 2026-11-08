"""R1 #17·#167: 재고·설비의 실제 API·DDL·검증·수정·복구·취소·승인·다운로드."""

import hashlib
import re
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
from specton.validate.sandbox import _statement_texts

pytestmark = pytest.mark.db
DOMAINS = {
    "inventory": ("창고", "창고코드", "창고명"),
    "maintenance": ("설비", "설비코드", "설비명"),
}


def _requirements(state: GraphState) -> dict[str, Any]:
    (block,) = state["design"].source_requirements
    req = Requirement(
        id="REQ-01", source_id=block.source_id, source_ref=block.source_ref,
        source_text=block.source_text, text=block.source_text, draft_text=block.source_text,
        type="FR", analysis_version=1,
    )  # fmt: skip
    return {"design": state["design"].evolve(requirements=(req,))}


def _entities(state: GraphState) -> dict[str, Any]:
    pack = state["design"].versions.pack_id
    assert pack is not None
    name, key, _ = DOMAINS[pack]
    entity = Entity.model_validate({
        "id": "ENT-01", "pack": pack, "name": name, "description": name,
        "req_ids": ["REQ-01"], "attributes": [{
            "id": "ATTR-01", "name": key, "data_type": "varchar", "length": 10,
            "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
        }],
    })  # fmt: skip
    return {"design": state["design"].evolve(entities=(entity,))}


SECOND_ENTITY = {"inventory": ("품목", "품목코드"), "maintenance": ("부품", "부품코드")}


def _two_entities(state: GraphState) -> dict[str, Any]:
    """표가 둘인 설계. 문장 번호 → 원래 엔티티 연결이 표 순서와 맞는지 실제 DB로 본다."""
    pack = state["design"].versions.pack_id
    assert pack is not None
    pairs = (DOMAINS[pack][:2], SECOND_ENTITY[pack])
    entities = tuple(
        Entity.model_validate(
            {
                "id": f"ENT-0{i}",
                "pack": pack,
                "name": name,
                "description": name,
                "req_ids": ["REQ-01"],
                "attributes": [
                    {
                        "id": f"ATTR-0{i}",
                        "name": key,
                        "data_type": "varchar",
                        "length": 10,
                        "is_key": True,
                        "nullable": False,
                        "req_ids": ["REQ-01"],
                    }
                ],
            }
        )
        for i, (name, key) in enumerate(pairs, start=1)
    )
    return {"design": state["design"].evolve(entities=entities)}


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
        pack: str,
        design: Callable[[GraphState], Mapping[str, Any]] | None = None,
        validate: Callable[[bytes, Settings], SqlValidation] | None = None,
        router: Callable[[GraphState], Mapping[str, Any]] | None = None,
    ) -> None:
        self.pool, self.settings, self.client = pool, settings, client
        self.pack = pack
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

        nodes = {"a01": _requirements, "a03": design or _entities, "a09": router or unexpected}
        nodes.update({name: review(name) for name in REVIEWERS})
        with patch.context() as context:
            context.setattr(main, "openai_agent_nodes", lambda settings: nodes)
            context.setattr(main, "document_node", lambda root: lambda state: {})
            if status != "real" or validate is not None:

                def validate_bytes(sql: bytes) -> SqlValidation:
                    self.calls.append(sql)
                    return validate(sql, settings) if validate is not None else _result(sql, status)

                context.setattr(
                    main, "ddl_node", lambda settings: ddl_node(settings, validate=validate_bytes)
                )
            self.graph = main.create_graph(settings, create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def create(self) -> str:
        name, _, _ = DOMAINS[self.pack]
        content = (
            f"요구사항 ID,요구사항명,상세 내용\nREQ-001,{name} 등록,{name}를 등록한다\n".encode()
        )
        response = self.client.post(
            "/runs", data={"pack": self.pack}, files={"file": ("req.csv", content, "text/csv")}
        )
        assert response.status_code == 202
        return str(response.json()["run_id"])

    def view(self, run_id: str, revision: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"section": "design"}
        if revision is not None:
            params["revision"] = revision
        response = self.client.get(f"/runs/{run_id}/view", params=params)
        assert response.status_code == 200
        return dict(response.json())

    def approve(self, run_id: str) -> Any:
        return self.answer(run_id, "approve")

    def answer(self, run_id: str, decision: str) -> Any:
        status = self.client.get(f"/runs/{run_id}").json()
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
def pipeline(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., _Pipeline]]:
    settings = Settings(_env_file=None, storage_dir=tmp_path, require_sql_validation=True)
    runners = []
    with ExitStack() as stack:

        def make(
            status: str = "real",
            previous: _Pipeline | None = None,
            *,
            pack: str | None = None,
            design: Callable[[GraphState], Mapping[str, Any]] | None = None,
            validate: Callable[[bytes, Settings], SqlValidation] | None = None,
            router: Callable[[GraphState], Mapping[str, Any]] | None = None,
        ) -> _Pipeline:
            client = stack.enter_context(TestClient(main.create_app(settings, pool)))
            if previous is not None:
                previous.runner.stop()
                client.cookies.update(previous.client.cookies)
            selected_pack = pack or (previous.pack if previous else "inventory")
            item = _Pipeline(
                pool, settings, client, monkeypatch, status, selected_pack, design, validate, router
            )
            runners.append(item.runner)
            return item

        yield make
        for runner in runners:
            runner.stop()


@pytest.mark.parametrize("pack", DOMAINS)
def test_real_api_ddl_validation_restart_approve_and_download_same_hash(
    pipeline: Callable[..., _Pipeline],
    pack: str,
) -> None:
    first = pipeline(pack=pack)
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
        if status == "failed":
            assert any(
                finding.rule_code == "RULE-07" and finding.severity == "critical"
                for finding in forced["design"].findings
            )
        else:
            assert all(finding.rule_code != "RULE-07" for finding in forced["design"].findings)
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


def _data_model_router(state: GraphState) -> dict[str, Any]:
    from specton.contracts.base import TargetStage

    return {"router_stage": TargetStage.DATA_MODEL}


def _revised_entities(state: GraphState) -> dict[str, Any]:
    from specton.contracts import Attribute

    update = _entities(state)
    design = update["design"]
    if design.revision:
        entity = design.entities[0]
        _, _, name = DOMAINS[design.versions.pack_id]
        attribute = Attribute(
            id="ATTR-02",
            name=name,
            data_type="varchar",
            length=200,
            is_key=False,
            nullable=True,
            req_ids=["REQ-01"],
        )
        update["design"] = design.evolve(
            entities=(entity.evolve(attributes=(*entity.attributes, attribute)),)
        )
    return update


def _download(w: _Pipeline, run_id: str, revision: int = 0) -> Any:
    return w.client.get(
        f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": revision}
    )


@pytest.mark.parametrize("pack", DOMAINS)
def test_user_revision_keeps_both_sql_histories_and_approves_only_the_new_revision(
    pipeline: Callable[..., _Pipeline],
    pack: str,
) -> None:
    first = pipeline(pack=pack, design=_revised_entities, router=_data_model_router)
    run_id = first.create()
    first.runner.run_pending()
    original = _download(first, run_id)
    assert original.status_code == 200
    with first.pool.connection() as conn:
        before = current_validation(conn, UUID(run_id), 0)
    assert before is not None and before.result.status == "passed"
    assert first.answer(run_id, "revise").status_code == 202

    restarted = pipeline(previous=first, design=_revised_entities, router=_data_model_router)
    restarted.runner.run_pending()
    status = restarted.client.get(f"/runs/{run_id}").json()
    assert (status["status"], status["revision"]) == ("awaiting_review", 1)
    replacement = _download(restarted, run_id, 1)
    assert replacement.status_code == 200 and replacement.content != original.content
    with restarted.pool.connection() as conn:
        after = current_validation(conn, UUID(run_id), 1)
        assert current_validation(conn, UUID(run_id), 0) == before
    assert after is not None and after.result.status == "passed"
    assert after.validation_id != before.validation_id and after.model_hash != before.model_hash
    assert after.result.artifact_hash != before.result.artifact_hash
    assert restarted.approve(run_id).status_code == 202
    restarted.runner.run_pending()
    assert restarted.client.get(f"/runs/{run_id}").json()["status"] == "completed"
    assert _download(restarted, run_id, 0).content == original.content
    approved = _download(restarted, run_id, 1)
    assert approved.content == replacement.content
    assert "-draft" not in approved.headers["content-disposition"]
    assert "-draft" in _download(restarted, run_id, 0).headers["content-disposition"]
    with restarted.pool.connection() as conn:
        basis = conn.execute(
            "SELECT s.revision, b.validation_id FROM approval_basis b "
            "JOIN approval p USING (approval_id) "
            "JOIN model_snapshot s ON s.snapshot_id=p.snapshot_id "
            "JOIN artifact a USING (artifact_id) WHERE p.run_id=%s AND a.kind='ddl'",
            (UUID(run_id),),
        ).fetchall()
    assert basis == [{"revision": 1, "validation_id": after.validation_id}]


@pytest.mark.parametrize("pack", DOMAINS)
def test_real_normalization_repair_has_no_fake_sql_for_the_failed_revision(
    pipeline: Callable[..., _Pipeline],
    pack: str,
) -> None:
    def repair(state: GraphState) -> Mapping[str, Any]:
        update = _entities(state)
        design = update["design"]
        entity = design.entities[0]
        if not design.revision:
            entity = entity.evolve(attributes=(entity.attributes[0].evolve(is_key=False),))
        return {"design": design.evolve(entities=(entity,))}

    w = pipeline(pack=pack, design=repair)
    run_id = w.create()
    w.runner.run_pending()
    current = w.client.get(f"/runs/{run_id}").json()
    assert (current["status"], current["revision"]) == ("awaiting_review", 1)
    assert _download(w, run_id, 0).status_code == 409
    assert _download(w, run_id, 1).status_code == 200
    with w.pool.connection() as conn:
        assert current_validation(conn, UUID(run_id), 0) is None
        stored = current_validation(conn, UUID(run_id), 1)
        row = conn.execute("SELECT count(*) AS n FROM artifact_validation").fetchone()
    assert stored is not None and stored.result.status == "passed"
    assert row is not None and row["n"] == 1
    assert w.approve(run_id).status_code == 202
    w.runner.run_pending()
    assert w.client.get(f"/runs/{run_id}").json()["status"] == "completed"


@pytest.mark.parametrize("pack", DOMAINS)
def test_real_sandbox_sql_defect_is_preserved_and_a_new_revision_can_be_approved(
    pipeline: Callable[..., _Pipeline],
    monkeypatch: pytest.MonkeyPatch,
    pack: str,
) -> None:
    from specton import ddl_adapter

    generate = ddl_adapter.generate_ddl
    generated = []
    broken_sql: list[str] = []

    def broken_once(*args: Any, **kwargs: Any) -> Any:
        result = generate(*args, **kwargs)
        generated.append(result)
        if len(generated) == 1:
            # 원래 표·컬럼을 유지하고 두 번째 CREATE TABLE의 첫 타입만 DB가 거절하는 값으로 바꾼다.
            # 0번이 아닌 문장을 망가뜨려야 문장 번호 → 표 순서가 틀렸을 때 시험이 실패한다.
            second = result.sql.index("CREATE TABLE", result.sql.index("CREATE TABLE") + 1)
            sql = result.sql[:second] + result.sql[second:].replace(
                "varchar(10)", "numeric(1001)", 1
            )
            assert sql != result.sql
            broken_sql.append(sql)
            return result.model_copy(update={"sql": sql})
        return result

    monkeypatch.setattr(ddl_adapter, "generate_ddl", broken_once)
    w = pipeline(pack=pack, router=_data_model_router, design=_two_entities)
    run_id = w.create()
    w.runner.run_pending()
    assert w.client.get(f"/runs/{run_id}").json()["status"] == "awaiting_review"
    assert w.reviewed == [] and w.approve(run_id).status_code == 422
    with w.pool.connection() as conn:
        failed = current_validation(conn, UUID(run_id), 0)
    assert failed is not None and failed.result.status == "failed"
    assert [step.status for step in failed.result.steps] == [
        "passed",
        "passed",
        "failed",
        "passed",
        "passed",
    ]
    assert failed.result.steps[2].issues[0].sqlstate == "22023"
    # 실제 격리 DB 실행 실패가 망가뜨린 표의 원래 엔티티에 대한 RULE-07 지적이 된다. 기대 대상은
    # 변환기의 문장 순서 가정을 쓰지 않고, 망가뜨린 문장의 표 물리명에서 읽는다.
    design = w.graph.get_state({"configurable": {"thread_id": run_id}}).values["design"]
    assert design.normalized is not None
    texts = _statement_texts(broken_sql[0])
    [broken] = [i for i, text in enumerate(texts) if "numeric(1001)" in text]
    assert broken == 1 and len(design.normalized.tables) == 2
    created = re.match(r'\s*CREATE TABLE "([^"]+)"', texts[broken])
    assert created is not None
    [source] = [t for t in design.normalized.tables if t.physical_name == created.group(1)]
    issue = failed.result.steps[2].issues[0]
    assert issue.statement_index == broken
    rule07 = [f for f in design.findings if f.rule_code == "RULE-07"]
    assert [(f.kind, f.severity, [(t.kind, t.id) for t in f.targets]) for f in rule07] == [
        ("execute:" + issue.code, "critical", [("entity", source.entity_id)])
    ]
    assert _download(w, run_id).content == broken_sql[0].encode("utf-8")
    assert w.answer(run_id, "revise").status_code == 202
    w.runner.run_pending()
    with w.pool.connection() as conn:
        passed = current_validation(conn, UUID(run_id), 1)
        assert current_validation(conn, UUID(run_id), 0) == failed
    assert passed is not None and passed.result.status == "passed"
    assert w.approve(run_id).status_code == 202
    w.runner.run_pending()
    assert w.client.get(f"/runs/{run_id}").json()["status"] == "completed"


def _environment_error(sql: bytes, settings: Settings) -> SqlValidation:
    from specton.validate.sandbox import validate_sql

    # 접속은 제한 sandbox 계정만 사용한다. 사전 검사에서 앱 DB와 같다는 환경 오류를 재현한다.
    invalid = settings.model_copy(update={"app_database_url": settings.sandbox_database_url})
    return validate_sql(sql, settings=invalid)


@pytest.mark.parametrize("pack", DOMAINS)
def test_real_sandbox_environment_error_is_stored_before_the_run_fails(
    pipeline: Callable[..., _Pipeline],
    pack: str,
) -> None:
    w = pipeline(pack=pack, validate=_environment_error)
    run_id = w.create()
    w.runner.run_pending()
    current = w.client.get(f"/runs/{run_id}").json()
    assert current["status"] == "failed" and current["error"]["code"] == "INTERNAL"
    with w.pool.connection() as conn:
        stored = current_validation(conn, UUID(run_id), 0)
    assert stored is not None and stored.result.status == "error"
    assert [step.status for step in stored.result.steps] == [
        "passed",
        "passed",
        "error",
        "passed",
        "passed",
    ]
    assert _download(w, run_id).content == w.calls[0]
    assert w.reviewed == []


@pytest.mark.parametrize("pack", DOMAINS)
@pytest.mark.parametrize("boundary", ["cancel", "lease"])
@pytest.mark.parametrize("outcome", ["passed", "error"])
def test_real_validation_late_result_never_publishes_after_cancel_or_lease_loss(
    pipeline: Callable[..., _Pipeline],
    pack: str,
    boundary: str,
    outcome: str,
) -> None:
    from specton.api.session import SESSION_COOKIE
    from specton.persistence import lease, runs
    from specton.validate.sandbox import validate_sql

    def validate(sql: bytes, settings: Settings) -> SqlValidation:
        result = (
            validate_sql(sql, settings=settings)
            if outcome == "passed"
            else _environment_error(sql, settings)
        )
        assert result.status == outcome
        with w.pool.connection() as conn:
            if boundary == "cancel":
                runs.request_cancel(conn, UUID(run_id), w.client.cookies[SESSION_COOKIE], 0)
            else:
                conn.execute(
                    "UPDATE job_lease SET lease_until=now() WHERE run_id=%s", (UUID(run_id),)
                )
                assert lease.acquire(conn, UUID(run_id), "new-worker", 60)
        return result

    w = pipeline(pack=pack, validate=validate)
    run_id = w.create()
    w.runner.run_pending()
    current = w.client.get(f"/runs/{run_id}").json()
    assert current["status"] == ("cancelled" if boundary == "cancel" else "generating")
    assert len(w.calls) == 1 and w.reviewed == []
    assert w.view(run_id)["artifacts"] == []
    with w.pool.connection() as conn:
        assert current_validation(conn, UUID(run_id), 0) is None
        row = conn.execute("SELECT count(*) AS n FROM artifact_validation").fetchone()
        events = runs.events_after(conn, UUID(run_id), w.client.cookies[SESSION_COOKIE], 0)
        if boundary == "lease":
            holder = conn.execute(
                "SELECT holder FROM job_lease WHERE run_id=%s", (UUID(run_id),)
            ).fetchone()
            assert holder is not None and holder["holder"] == "new-worker"
    assert row is not None and row["n"] == 0
    assert not any(event.event == "artifact" for event in events)


@pytest.mark.parametrize("pack", DOMAINS)
@pytest.mark.parametrize("outcome", ["passed", "error"])
@pytest.mark.parametrize("boundary", [None, "cancel", "lease", "restart"])
def test_completed_sql_validation_survives_another_generator_failure(
    pipeline: Callable[..., _Pipeline],
    monkeypatch: pytest.MonkeyPatch,
    pack: str,
    outcome: str,
    boundary: str | None,
) -> None:
    from threading import Event

    from specton.validate.sandbox import validate_sql

    written = Event()

    def erd_factory(root: Path) -> Callable[[GraphState], Mapping[str, Any]]:
        def fail(state: GraphState) -> Mapping[str, Any]:
            assert written.wait(5), "DDL 노드의 체크포인트 pending writes가 저장되지 않았습니다"
            raise OSError("fixture ERD failure after SQL validation")

        return fail

    def validate(sql: bytes, settings: Settings) -> SqlValidation:
        if outcome == "error":
            return _environment_error(sql, settings)
        return validate_sql(sql, settings=settings)

    monkeypatch.setattr(main, "erd_node", erd_factory)
    w = pipeline(pack=pack, validate=validate)
    checkpointer = w.graph.checkpointer
    original = checkpointer.put_writes

    def observe(config: Any, writes: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(config, writes, *args, **kwargs)
        if any(key == "validation_attempts" and value for key, value in writes):
            written.set()
        return result

    monkeypatch.setattr(checkpointer, "put_writes", observe)
    run_id = w.create()
    if boundary is not None:
        import specton.runner as runner_module
        from specton.api.session import SESSION_COOKIE
        from specton.persistence import lease, runs

        recover = runner_module._Job._save_completed_sql

        def interrupt(job: Any) -> None:
            if boundary == "restart":
                recover(job)
                w.runner.request_stop()
                raise runner_module._Stop
            with w.pool.connection() as conn:
                if boundary == "cancel":
                    runs.request_cancel(conn, UUID(run_id), w.client.cookies[SESSION_COOKIE], 0)
                else:
                    conn.execute(
                        "UPDATE job_lease SET lease_until=now() WHERE run_id=%s", (UUID(run_id),)
                    )
                    assert lease.acquire(conn, UUID(run_id), "new-worker", 60)
            recover(job)

        monkeypatch.setattr(runner_module._Job, "_save_completed_sql", interrupt)
    w.runner.run_pending()
    assert written.is_set() and len(w.calls) == 1
    expected = {
        None: "failed",
        "cancel": "cancelled",
        "lease": "generating",
        "restart": "generating",
    }[boundary]
    assert w.client.get(f"/runs/{run_id}").json()["status"] == expected
    assert w.reviewed == []
    with w.pool.connection() as conn:
        stored = current_validation(conn, UUID(run_id), 0)
    if boundary in ("cancel", "lease"):
        assert stored is None and w.view(run_id)["artifacts"] == []
        return
    assert stored is not None and stored.result.status == outcome
    if boundary == "restart":
        monkeypatch.setattr(runner_module._Job, "_save_completed_sql", recover)
        restarted = pipeline(previous=w, validate=validate)
        restarted.runner.run_pending()
        assert restarted.client.get(f"/runs/{run_id}").json()["status"] == "failed"
        assert restarted.calls == [] and restarted.reviewed == []
        with restarted.pool.connection() as conn:
            assert current_validation(conn, UUID(run_id), 0) == stored
            row = conn.execute("SELECT count(*) AS n FROM artifact_validation").fetchone()
            assert row is not None and row["n"] == 1
    response = _download(w, run_id)
    assert response.status_code == 200 and response.content == w.calls[0]
    assert stored.result.artifact_hash == hashlib.sha256(response.content).hexdigest()
    assert [item["kind"] for item in w.view(run_id)["artifacts"]] == ["ddl"]
