"""#17: 실제 정리 실패를 실행기·Postgres·HTTP 재개까지 연결한다.

설계와 #15 분류 정책만 고정 응답을 주입한다. 문서 업로드·파싱, 정리 함수와 어댑터,
체크포인트·모델 저장, 조회·승인 API는 실제 구현을 사용한다. LLM은 호출하지 않는다.
"""

import shutil
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from fastapi.testclient import TestClient
from httpx import Response
from langgraph.checkpoint.serde.event_hooks import SerdeEvent, register_serde_event_listener

from specton.api.main import create_app
from specton.api.session import SESSION_COOKIE
from specton.config import Settings
from specton.contracts import (
    BranchResult,
    DesignState,
    Entity,
    Finding,
    Requirement,
    RunStatus,
    SseEvent,
)
from specton.contracts.base import TargetStage
from specton.contracts.normalized import Problem, ProblemCode
from specton.graph import REVIEWERS, GraphState, Node, build_graph
from specton.normalization_node import FailureMapper, FailureReview, normalization_node
from specton.packs.build import DEFAULT_ROOT, read_yaml
from specton.parse_node import parse_node
from specton.persistence.db import Pool, create_checkpointer
from specton.persistence.runs import events_after
from specton.runner import Runner

pytestmark = pytest.mark.db

CSV = "요구사항 ID,요구사항명,상세 내용\nMNT-001,설비 등록,설비는 설비코드로 구분한다\n"
DOWNSTREAM = ("ddl", "erd", "rtm", "rules", *REVIEWERS, "export")


def _requirement(state: GraphState) -> Mapping[str, Any]:
    (source,) = state["design"].source_requirements
    assert source.source_text is not None
    requirement = Requirement(
        id="REQ-01", source_id=source.source_id, source_ref=source.source_ref,
        source_text=source.source_text, text=source.source_text, draft_text=source.source_text,
        type="FR", analysis_version=1,
    )  # fmt: skip
    return {"design": state["design"].evolve(requirements=(requirement,))}


def _entity(*, keyed: bool = True, name: str = "설비") -> Entity:
    return Entity.model_validate({
        "id": "ENT-eq", "pack": "maintenance", "name": name, "description": "설비",
        "req_ids": ["REQ-01"], "attributes": [{
            "id": "ATTR-eq", "name": "설비코드", "data_type": "varchar", "length": 10,
            "is_key": keyed, "nullable": False, "req_ids": ["REQ-01"],
        }],
    })  # fmt: skip


def _finding(problem: Problem, iteration: int, *, manual: bool) -> Finding:
    """이 합성 사례 한 건에만 쓰는 #15 고정 응답. 운영 분류 정책을 구현하지 않는다."""
    return Finding(
        id=f"fixture-{iteration}", source="rule", rule_code="RULE-05" if manual else "RULE-03",
        kind=problem.code.value, severity="critical", targets=({"kind": "entity", "id": "ENT-eq"},),
        evidence=({"quote": problem.detail},), suggestion="시험 설계를 보완한다",
        target_stage=None if manual else TargetStage.DATA_MODEL,
        fingerprint=f"fixture-{problem.code.value}", iteration=iteration,
    )  # fmt: skip


def _unexpected(*args: Any) -> Any:
    pytest.fail("실행 오류 변환기 또는 불필요한 A09가 호출됐습니다")


class _Pipeline:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        client: TestClient,
        design: Node,
        mapper: FailureMapper,
    ) -> None:
        self.pool, self.settings, self.client = pool, settings, client
        self.visited: list[tuple[str, int]] = []
        nodes = {name: self._downstream(name) for name in DOWNSTREAM}
        nodes.update(
            parse=parse_node(settings.storage_dir), a01=_requirement, a03=design,
            normalize=normalization_node(mapper, root=settings.pack_root), a09=_unexpected,
        )  # fmt: skip
        self.graph = build_graph(nodes, checkpointer=create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def _downstream(self, name: str) -> Node:
        def node(state: GraphState) -> Mapping[str, Any]:
            revision = state["design"].revision
            self.visited.append((name, revision))
            if name in REVIEWERS:
                return {"branches": {name: BranchResult(branch=name, revision=revision, ok=True)}}
            return {}

        return node

    def create(self) -> str:
        response = self.client.post(
            "/runs", data={"pack": "maintenance"},
            files={"file": ("requirements.csv", CSV.encode(), "text/csv")},
        )  # fmt: skip
        assert response.status_code == 202, response.text
        return str(response.json()["run_id"])

    def status(self, run_id: str) -> RunStatus:
        response = self.client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        return RunStatus.model_validate(response.json())

    def answer(self, run_id: str, decision: str) -> Response:
        status = self.status(run_id)
        assert status.interrupt is not None and status.interrupt.kind == "review"
        return self.client.post(f"/runs/{run_id}/resume", json={
            "interrupt_id": status.interrupt.interrupt_id, "expected_revision": status.revision,
            "response": {"kind": "review", "decision": decision, "feedback": ""},
        })  # fmt: skip

    def models(self, run_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT revision, normalized_model, model_hash FROM model_snapshot "
                "WHERE run_id = %s ORDER BY revision",
                (UUID(run_id),),
            ).fetchall()

    def events(self, run_id: str) -> list[SseEvent]:
        with self.pool.connection() as conn:
            return events_after(conn, UUID(run_id), self.client.cookies[SESSION_COOKIE], 0)


@pytest.fixture
def pipeline(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., _Pipeline]]:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    root = tmp_path / "packs"
    for pack in ("common", "maintenance"):
        shutil.copytree(DEFAULT_ROOT / pack, root / pack)
    settings = Settings(_env_file=None, pack_root=root, storage_dir=tmp_path / "storage")
    worlds: list[_Pipeline] = []
    events: list[SerdeEvent] = []
    unregister = register_serde_event_listener(events.append)
    with ExitStack() as stack:

        def make(
            design: Node, mapper: FailureMapper, *, previous: _Pipeline | None = None
        ) -> _Pipeline:
            client = stack.enter_context(TestClient(create_app(settings, pool)))
            if previous is not None:
                previous.runner.stop()
                client.cookies.update(previous.client.cookies)
            result = _Pipeline(pool, settings, client, design, mapper)
            worlds.append(result)
            return result

        try:
            yield make
        finally:
            for world in worlds:
                world.runner.stop()
            unregister()
    assert events == []


def test_actual_missing_key_is_reworked_and_both_revisions_survive_restart(
    pipeline: Callable[..., _Pipeline],
) -> None:
    seen: list[tuple[int, bool]] = []

    def design(state: GraphState) -> Mapping[str, Any]:
        current = state["design"]
        seen.append((current.revision, current.normalized is None))
        return {"design": current.evolve(entities=(_entity(keyed=current.revision > 0),))}

    def classify(design: DesignState, problems: tuple[Problem, ...]) -> FailureReview:
        (problem,) = problems
        assert problem.code is ProblemCode.NO_PRIMARY_KEY
        return FailureReview(
            findings=(_finding(problem, design.iteration, manual=False),),
            requires_manual_review=False,
        )

    first = pipeline(design, classify)
    run_id = first.create()
    first.runner.run_pending()

    assert (first.status(run_id).status, first.status(run_id).revision) == ("awaiting_review", 1)
    assert seen == [(0, True), (1, True)]
    assert set(first.visited) == {(name, 1) for name in DOWNSTREAM if name != "export"}
    failed, repaired = first.models(run_id)
    assert [failed["revision"], repaired["revision"]] == [0, 1]
    assert "normalized" not in failed["normalized_model"]
    assert repaired["normalized_model"]["normalized"]["tables"][0]["physical_name"] == "eqpm"
    review = first.client.get(f"/runs/{run_id}/view", params={"section": "review", "revision": 0})
    assert [item["kind"] for item in review.json()["items"]] == ["no_primary_key"]
    current_review = first.client.get(f"/runs/{run_id}/view", params={"section": "review"})
    assert current_review.json()["items"] == []

    restarted = pipeline(design, classify, previous=first)
    assert restarted.answer(run_id, "approve").status_code == 202
    restarted.runner.run_pending()

    assert restarted.status(run_id).status == "completed"
    assert seen == [(0, True), (1, True)]
    assert restarted.visited == [("export", 1)]
    assert restarted.models(run_id) == [failed, repaired]
    with restarted.pool.connection() as conn:
        approved = conn.execute(
            "SELECT s.revision, s.model_hash FROM approval a "
            "JOIN model_snapshot s USING (snapshot_id) "
            "WHERE a.run_id = %s AND a.decision = 'approve'",
            (UUID(run_id),),
        ).fetchall()
    assert approved == [{"revision": 1, "model_hash": repaired["model_hash"]}]


def test_actual_unknown_name_blocks_approval_after_restart(
    pipeline: Callable[..., _Pipeline],
) -> None:
    attempts: list[int] = []

    def design(state: GraphState) -> Mapping[str, Any]:
        attempts.append(state["design"].revision)
        return {"design": state["design"].evolve(entities=(_entity(name="사전미등록XYZ"),))}

    def classify(design: DesignState, problems: tuple[Problem, ...]) -> FailureReview:
        (problem,) = problems
        assert (problem.code, problem.decision, problem.pending) == (
            ProblemCode.UNRESOLVED_NAME,
            "D5",
            True,
        )
        return FailureReview(
            findings=(_finding(problem, design.iteration, manual=True),),
            requires_manual_review=True,
        )

    first = pipeline(design, classify)
    run_id = first.create()
    first.runner.run_pending()
    before = first.status(run_id)
    assert (before.status, before.revision) == ("awaiting_review", 0)
    assert first.visited == []
    [snapshot] = first.models(run_id)
    assert "normalized" not in snapshot["normalized_model"]
    [interrupt] = [event for event in first.events(run_id) if event.event == "interrupt"]
    assert interrupt.data.payload["hitl_reason"] == "manual_review"

    restarted = pipeline(design, classify, previous=first)
    checkpoint = restarted.graph.get_state({"configurable": {"thread_id": run_id}})
    assert checkpoint.values["design"].normalized is None
    assert checkpoint.values["normalization_failed"] is True
    assert checkpoint.values["requires_manual_review"] is True
    events = restarted.events(run_id)
    review = restarted.client.get(f"/runs/{run_id}/view", params={"section": "review"})
    assert [item["kind"] for item in review.json()["items"]] == ["unresolved_name"]
    response = restarted.answer(run_id, "approve")
    assert (response.status_code, response.json()["code"]) == (422, "INVALID_RESPONSE")
    assert restarted.status(run_id) == before
    assert restarted.models(run_id) == [snapshot]
    assert restarted.events(run_id) == events
    with restarted.pool.connection() as conn:
        assert (
            conn.execute("SELECT 1 FROM approval WHERE run_id = %s", (UUID(run_id),)).fetchone()
            is None
        )
    assert restarted.answer(run_id, "hold").status_code == 202
    restarted.runner.run_pending()
    assert restarted.status(run_id).status == "awaiting_review"
    assert restarted.visited == []
    assert attempts == [0]


@pytest.mark.parametrize("failure", ["version_changed", "missing_naming_file"])
def test_pack_execution_failure_does_not_become_a_rule_or_an_approval(
    pipeline: Callable[..., _Pipeline], failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    def design(state: GraphState) -> Mapping[str, Any]:
        return {"design": state["design"].evolve(entities=(_entity(),))}

    world = pipeline(design, _unexpected)
    run_id = world.create()
    if failure == "version_changed":
        path = world.settings.pack_root / "maintenance/manifest.yaml"
        manifest = read_yaml(path)
        major = int(manifest["version"].split(".")[0])
        manifest["version"] = f"{major + 1}.0.0"
        path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    else:
        (world.settings.pack_root / "common/naming.yaml").unlink()
    world.runner.run_pending()

    status = world.status(run_id)
    assert status.status == "failed" and status.error is not None
    assert status.error.code == "INTERNAL"
    assert status.error.message == "실행 중 서버 오류가 발생했습니다."
    assert status.interrupt is None and world.visited == []
    models = world.models(run_id)
    assert models and all("normalized" not in row["normalized_model"] for row in models)
    review = world.client.get(f"/runs/{run_id}/view", params={"section": "review"})
    assert review.json()["items"] == []
    events = world.events(run_id)
    assert events[-1].event == "error" and events[-1].data.payload["code"] == "INTERNAL"
    assert not any(event.event in ("interrupt", "artifact", "completed") for event in events)
    errors = [
        record.exc_info[1]
        for record in caplog.records
        if record.name == "specton.runner" and record.exc_info
    ]
    (error,) = errors
    if failure == "version_changed":
        assert isinstance(error, ValueError) and "pack_mismatch" in str(error)
    else:
        assert isinstance(error, FileNotFoundError) and "naming.yaml" in str(error)
    stream = world.client.get(f"/runs/{run_id}/events")
    assert stream.status_code == 200 and "event: error" in stream.text
    assert "pack_mismatch" not in stream.text and "naming.yaml" not in stream.text
    response = world.client.post(f"/runs/{run_id}/resume", json={
        "interrupt_id": "no-review-on-failed-run", "expected_revision": status.revision,
        "response": {"kind": "review", "decision": "approve", "feedback": ""},
    })  # fmt: skip
    assert (response.status_code, response.json()["code"]) == (409, "INTERRUPT_STALE")
    assert world.status(run_id) == status and world.models(run_id) == models
    assert world.events(run_id) == events
    with world.pool.connection() as conn:
        assert (
            conn.execute("SELECT 1 FROM approval WHERE run_id = %s", (UUID(run_id),)).fetchone()
            is None
        )
