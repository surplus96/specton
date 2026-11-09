"""실제 API·정리·SQL 검증·규칙·저장·재작업·승인. 에이전트 판단만 고정 응답이다."""

import hashlib
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from specton.api import main
from specton.config import Settings
from specton.contracts import BranchResult, Entity, Function, Requirement
from specton.contracts.base import TargetStage
from specton.graph import REVIEWERS, GraphState
from specton.persistence.db import Pool, create_checkpointer
from specton.persistence.validations import current_validation
from specton.runner import Runner

pytestmark = pytest.mark.db
DOMAINS = {"inventory": ("창고", "창고코드"), "maintenance": ("설비", "설비코드")}


class _World:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        client: TestClient,
        patch: pytest.MonkeyPatch,
        pack: str,
        kind: str,
        repair: bool,
    ) -> None:
        self.pool, self.settings, self.client = pool, settings, client
        self.pack, self.kind, self.repair = pack, kind, repair
        self.visited: list[tuple[str, int]] = []
        self.routed: list[tuple[str, ...]] = []
        nodes = {
            "a01": self._requirements,
            "a02": self._functions,
            "a03": self._entities,
            "a09": self._router,
        }
        nodes.update({name: self._review(name) for name in REVIEWERS})
        with patch.context() as context:
            context.setattr(main, "openai_agent_nodes", lambda settings: nodes)
            self.graph = main.create_graph(settings, create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def _broken(self, state: GraphState) -> bool:
        return not (self.repair and state["design"].revision > 0)

    def _requirements(self, state: GraphState) -> dict[str, Any]:
        (block,) = state["design"].source_requirements
        assert block.source_text is not None
        requirements = tuple(
            Requirement(
                id=f"REQ-{i:02}", source_id=block.source_id, source_ref=block.source_ref,
                source_text=block.source_text, text=block.source_text, draft_text=block.source_text,
                type="NFR" if self.kind == "nfr" else "FR",
                nfr_category="performance" if self.kind == "nfr" else None, analysis_version=1,
            )
            for i in range(1, 3 if self.kind == "unlinked_fr" else 2)
        )  # fmt: skip
        return {"design": state["design"].evolve(requirements=requirements)}

    def _functions(self, state: GraphState) -> dict[str, Any]:
        design = state["design"]
        self.visited.append(("functions", design.revision))
        ids = tuple(r.id for r in design.requirements)
        if self.kind == "unlinked_fr" and self._broken(state):
            ids = ids[:1]
        functions = (
            ()
            if self.kind == "nfr" or (self.kind == "unlinked_entity" and self._broken(state))
            else (Function(id="FUNC-01", name="조회", description="대상을 조회한다", req_ids=ids),)
        )
        return {"design": design.evolve(functions=functions)}

    def _entities(self, state: GraphState) -> dict[str, Any]:
        design = state["design"]
        self.visited.append(("data_model", design.revision))
        name, key = DOMAINS[self.pack]
        exemptions = {
            "invalid_exemption": [{"operation": "U", "reason": "soft_delete"}],
            "soft_delete": [{"operation": "D", "reason": "soft_delete"}],
            "immutable_ledger": [
                {"operation": "U", "reason": "immutable_ledger"},
                {"operation": "D", "reason": "immutable_ledger"},
            ],
        }.get(self.kind, [])
        if self.kind == "invalid_exemption" and not self._broken(state):
            exemptions = []
        entity = Entity.model_validate({
            "id": "ENT-01", "pack": self.pack, "name": name, "description": name,
            "req_ids": ["REQ-01"], "crud_exemptions": exemptions, "attributes": [{
                "id": "ATTR-01", "name": key, "data_type": "varchar", "length": 10,
                "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
            }],
        })  # fmt: skip
        used = not (self.kind == "unused_entity" and self._broken(state))
        functions = tuple(
            f.evolve(entity_ops=({"entity_id": entity.id, "operations": ("R",)},) if used else ())
            for f in design.functions
        )
        return {"design": design.evolve(entities=(entity,), functions=functions)}

    def _router(self, state: GraphState) -> dict[str, Any]:
        self.routed.append(tuple(f.rule_code for f in state.get("unrouted", ())))
        stage = None
        if state.get("revising"):
            stage = (
                TargetStage.FUNCTIONS
                if self.kind in ("unlinked_fr", "unlinked_entity")
                else TargetStage.DATA_MODEL
            )
        return {"router_stage": stage}

    @staticmethod
    def _review(name: str) -> Callable[[GraphState], dict[str, Any]]:
        def node(state: GraphState) -> dict[str, Any]:
            return {
                "branches": {
                    name: BranchResult(branch=name, revision=state["design"].revision, ok=True)
                }
            }

        return node

    def create(self) -> str:
        name, _ = DOMAINS[self.pack]
        response = self.client.post(
            "/runs",
            data={"pack": self.pack},
            files={
                "file": (
                    "requirements.csv",
                    (
                        f"요구사항 ID,요구사항명,상세 내용\nSRC-01,{name} 조회,{name}를 조회한다\n"
                    ).encode(),
                    "text/csv",
                ),
            },
        )
        assert response.status_code == 202
        return str(response.json()["run_id"])

    def prepare(self, run_id: str) -> None:
        self.runner.run_pending()
        status = self.status(run_id)
        if status["status"] == "awaiting_requirements":
            response = self.client.post(
                f"/runs/{run_id}/resume",
                json={
                    "interrupt_id": status["interrupt"]["interrupt_id"],
                    "expected_revision": status["revision"],
                    "response": {"kind": "requirements", "answers": []},
                },
            )
            assert response.status_code == 202
            self.runner.run_pending()

    def status(self, run_id: str) -> dict[str, Any]:
        return dict(self.client.get(f"/runs/{run_id}").json())

    def findings(self, run_id: str, revision: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"section": "review"}
        if revision is not None:
            params["revision"] = revision
        response = self.client.get(f"/runs/{run_id}/view", params=params)
        assert response.status_code == 200
        return list(response.json()["items"])

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
                    "feedback": "누락된 연결을 수정한다",
                },
            },
        )


@pytest.fixture
def world(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., _World]]:
    worlds: list[_World] = []
    with ExitStack() as stack:

        def make(
            pack: str = "inventory",
            kind: str = "unused_entity",
            repair: bool = False,
            limit: int = 3,
            previous: _World | None = None,
        ) -> _World:
            settings = Settings(
                _env_file=None,
                openai_api_key=None,
                storage_dir=tmp_path,
                require_sql_validation=True,
                max_rework_iterations=limit,
            )
            client = stack.enter_context(TestClient(main.create_app(settings, pool)))
            if previous is not None:
                previous.runner.stop()
                client.cookies.update(previous.client.cookies)
                pack, kind = previous.pack, previous.kind
            result = _World(pool, settings, client, monkeypatch, pack, kind, repair)
            worlds.append(result)
            return result

        yield make
        for item in worlds:
            item.runner.stop()


@pytest.mark.parametrize("pack", DOMAINS)
@pytest.mark.parametrize(
    "kind,stage",
    [
        ("unlinked_fr", "functions"),
        ("unlinked_entity", "functions"),
        ("unused_entity", "data_model"),
        ("invalid_exemption", "data_model"),
    ],
)
def test_rules_rework_from_the_mapped_stage_then_allow_approval(
    world: Callable[..., _World], pack: str, kind: str, stage: str
) -> None:
    w = world(pack, kind, repair=True)
    run_id = w.create()
    w.prepare(run_id)
    assert (w.status(run_id)["status"], w.status(run_id)["revision"]) == ("awaiting_review", 1)
    assert w.findings(run_id) == []
    old = w.findings(run_id, 0)
    assert old and all(f["severity"] == "critical" for f in old)
    assert {f["target_stage"] for f in old} == {stage}
    assert w.visited.count(("functions", 1)) == (stage == "functions")
    assert w.visited.count(("data_model", 1)) == 1 and w.routed == []
    assert w.answer(run_id, "approve").status_code == 202
    w.runner.run_pending()
    assert w.status(run_id)["status"] == "completed"


@pytest.mark.parametrize("pack", DOMAINS)
@pytest.mark.parametrize("kind", ["unlinked_fr", "unused_entity", "invalid_exemption"])
def test_repeated_critical_findings_block_approval_until_a_user_revision(
    world: Callable[..., _World], pack: str, kind: str
) -> None:
    w = world(pack, kind)
    run_id = w.create()
    w.prepare(run_id)
    before = w.status(run_id)
    assert (before["status"], before["revision"]) == ("awaiting_review", 1)
    first, repeated = w.findings(run_id, 0), w.findings(run_id)
    assert {f["fingerprint"] for f in first} == {f["fingerprint"] for f in repeated}
    assert {f["iteration"] for f in repeated} == {f["iteration"] + 1 for f in first}
    assert {f["id"] for f in repeated}.isdisjoint(f["id"] for f in first)
    with w.pool.connection() as conn:
        approvals = conn.execute(
            "SELECT * FROM approval WHERE run_id=%s ORDER BY approval_id", (UUID(run_id),)
        ).fetchall()
    assert w.answer(run_id, "approve").status_code == 422
    assert w.status(run_id) == before
    with w.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT * FROM approval WHERE run_id=%s ORDER BY approval_id", (UUID(run_id),)
            ).fetchall()
            == approvals
        )
        assert conn.execute("SELECT COUNT(*) AS n FROM approval_basis").fetchone()["n"] == 0
        stored = current_validation(conn, UUID(run_id), 1)
    assert stored is not None and stored.result.status == "passed"
    w.repair = True
    assert w.answer(run_id, "revise").status_code == 202
    w.runner.run_pending()
    assert w.status(run_id)["revision"] == 2 and w.findings(run_id) == []
    assert w.answer(run_id, "approve").status_code == 202
    w.runner.run_pending()
    assert w.status(run_id)["status"] == "completed"
    response = w.client.get(
        f"/runs/{run_id}/artifacts/ddl", params={"file_format": "sql", "revision": 2}
    )
    assert response.status_code == 200 and "-draft" not in response.headers["content-disposition"]
    with w.pool.connection() as conn:
        valid = current_validation(conn, UUID(run_id), 2)
    assert (
        valid is not None
        and valid.result.artifact_hash == hashlib.sha256(response.content).hexdigest()
    )


@pytest.mark.parametrize("pack", DOMAINS)
def test_nfr_only_unused_entity_is_sent_to_a09_not_forced_to_a_design_stage(
    world: Callable[..., _World], pack: str
) -> None:
    w = world(pack, "nfr")
    run_id = w.create()
    w.prepare(run_id)
    assert (w.status(run_id)["status"], w.status(run_id)["revision"]) == ("awaiting_review", 0)
    (finding,) = w.findings(run_id)
    assert (finding["rule_code"], finding["target_stage"]) == ("RULE-06", None)
    assert w.routed == [("RULE-06",)]
    assert w.answer(run_id, "approve").status_code == 422


@pytest.mark.parametrize("pack", DOMAINS)
def test_api_settings_zero_limit_stops_before_any_automatic_rework(
    world: Callable[..., _World], pack: str
) -> None:
    w = world(pack, "unlinked_entity", repair=True, limit=0)
    run_id = w.create()
    w.prepare(run_id)
    assert (w.status(run_id)["status"], w.status(run_id)["revision"]) == ("awaiting_review", 0)
    assert w.findings(run_id) and w.visited == [("functions", 0), ("data_model", 0)]
    assert w.routed == [] and w.answer(run_id, "approve").status_code == 422
    artifacts = w.client.get(f"/runs/{run_id}/view", params={"section": "design"}).json()[
        "artifacts"
    ]
    kinds = {a["kind"] for a in artifacts}
    assert "functions" not in kinds and {"rtm", "ddl", "erd"} <= kinds


@pytest.mark.parametrize("pack", DOMAINS)
@pytest.mark.parametrize("kind", ["healthy", "soft_delete", "immutable_ledger"])
def test_read_only_design_and_valid_exemptions_do_not_require_all_crud(
    world: Callable[..., _World], pack: str, kind: str
) -> None:
    w = world(pack, kind)
    run_id = w.create()
    w.prepare(run_id)
    assert (w.status(run_id)["status"], w.status(run_id)["revision"]) == ("awaiting_review", 0)
    assert w.findings(run_id) == [] and w.routed == []
    assert w.answer(run_id, "approve").status_code == 202
    w.runner.run_pending()
    assert w.status(run_id)["status"] == "completed"


@pytest.mark.parametrize("pack", DOMAINS)
def test_held_checkpoint_keeps_critical_findings_after_restart(
    world: Callable[..., _World], pack: str
) -> None:
    first = world(pack)
    run_id = first.create()
    first.prepare(run_id)
    expected = first.findings(run_id)
    restarted = world(previous=first)
    assert restarted.answer(run_id, "hold").status_code == 202
    restarted.runner.run_pending()
    assert restarted.findings(run_id) == expected and restarted.visited == []
    assert restarted.answer(run_id, "approve").status_code == 422
