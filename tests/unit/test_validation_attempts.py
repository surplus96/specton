"""#167: 검증 시도는 새 호출마다 구분하고 체크포인트 재개 때는 그대로 읽는다."""

import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.artifacts import GeneratedArtifact, artifact_key, write_artifact
from specton.contracts import DesignState, SqlValidation, ValidationIssue, ValidationStep
from specton.contracts.validation import VALIDATION_STEPS, overall_status
from specton.graph import GraphState, build_graph, initial_state
from specton.model_hash import model_hash
from specton.persistence.db import checkpoint_serde
from specton.validation_attempts import merge_validation_attempts, run_validation_attempt

SQL = b"CREATE TABLE fixture (id integer PRIMARY KEY);\n"


def _result(payload: bytes, status: str = "passed") -> SqlValidation:
    statuses = {
        "passed": ("passed",) * 5,
        "failed": ("failed", "not_run", "not_run", "not_run", "not_run"),
        "error": ("passed", "passed", "error", "passed", "passed"),
        "unverified": ("passed", "passed", "not_run", "not_run", "not_run"),
    }[status]
    steps = tuple(
        ValidationStep(
            name=name,
            status=value,
            issues=(ValidationIssue(code="fixture_error"),) if value in ("failed", "error") else (),
        )
        for name, value in zip(VALIDATION_STEPS, statuses, strict=True)
    )
    return SqlValidation(
        status=overall_status(steps),
        artifact_hash=hashlib.sha256(payload).hexdigest(),
        validator_version="fixture-v1",
        policy_version="fixture-p1",
        postgres_version="postgresql-18",
        steps=steps,
    )


@pytest.fixture
def design() -> DesignState:
    return DesignState(run_id=str(uuid4()), revision=1)


@pytest.fixture
def artifact(tmp_path: Path, design: DesignState) -> GeneratedArtifact:
    return write_artifact(tmp_path, design, "ddl", "sql", SQL)


@pytest.mark.parametrize("status", ["passed", "failed", "error", "unverified"])
def test_attempt_keeps_the_exact_result_and_artifact_context(
    design: DesignState,
    artifact: GeneratedArtifact,
    status: str,
) -> None:
    result = _result(SQL, status)
    received = []

    def validate(payload: bytes) -> SqlValidation:
        received.append(payload)
        return result

    attempt = run_validation_attempt(design, artifact, SQL, validate)

    assert str(UUID(attempt["validation_id"])) == attempt["validation_id"]
    assert attempt["run_id"] == design.run_id
    assert attempt["artifact"] == artifact
    assert attempt["result"] is result
    assert received == [SQL]
    assert artifact["model_hash"] == model_hash(design)
    # 호출자가 원래 인계 dict를 바꾸어도 이미 반환한 검증 문맥은 바뀌지 않는다.
    artifact["model_hash"] = "f" * 64
    assert attempt["artifact"]["model_hash"] == model_hash(design)


def test_same_sql_and_versions_get_a_new_id_for_each_call(
    design: DesignState,
    artifact: GeneratedArtifact,
) -> None:
    first = run_validation_attempt(design, artifact, SQL, _result)
    second = run_validation_attempt(design, artifact, SQL, _result)

    assert first["result"] == second["result"]
    assert first["validation_id"] != second["validation_id"]
    assert (
        len(
            merge_validation_attempts(
                {first["validation_id"]: first},
                {second["validation_id"]: second},
            )
        )
        == 2
    )


@pytest.mark.parametrize("mismatch", ["sql", "revision", "model", "run", "kind"])
def test_inconsistent_input_stops_before_calling_validator(
    tmp_path: Path,
    design: DesignState,
    artifact: GeneratedArtifact,
    mismatch: str,
) -> None:
    if mismatch == "revision":
        design = design.evolve(revision=2)
    elif mismatch == "model":
        artifact["model_hash"] = "f" * 64
    elif mismatch == "run":
        design = design.evolve(run_id=str(uuid4()))
    elif mismatch == "kind":
        artifact = write_artifact(tmp_path, design, "erd", "mmd", SQL)
    called = []

    def validate(payload: bytes) -> SqlValidation:
        called.append(payload)
        return _result(payload)

    with pytest.raises(ValueError):
        run_validation_attempt(
            design, artifact, SQL + b"-- changed" if mismatch == "sql" else SQL, validate
        )
    assert called == []


def test_result_for_other_sql_is_rejected(design: DesignState, artifact: GeneratedArtifact) -> None:
    with pytest.raises(ValueError, match="해시"):
        run_validation_attempt(design, artifact, SQL, lambda _: _result(b"other SQL"))


def test_unexpected_validator_exception_is_not_a_fabricated_result(
    design: DesignState,
    artifact: GeneratedArtifact,
) -> None:
    error = RuntimeError("fixture connection failure")

    def broken(_: bytes) -> SqlValidation:
        raise error

    with pytest.raises(RuntimeError) as caught:
        run_validation_attempt(design, artifact, SQL, broken)
    assert caught.value is error


@pytest.mark.parametrize("change", ["result", "model"])
def test_replaying_one_id_is_idempotent_but_changed_payload_is_a_conflict(
    design: DesignState,
    artifact: GeneratedArtifact,
    change: str,
) -> None:
    attempt = run_validation_attempt(design, artifact, SQL, _result)
    key = attempt["validation_id"]
    old = {key: attempt}

    assert merge_validation_attempts(old, old) == old
    changed = attempt.copy()
    if change == "result":
        changed["result"] = _result(SQL, "error")
    else:
        changed["artifact"] = {**artifact, "model_hash": "f" * 64}
    with pytest.raises(ValueError, match="같은"):
        merge_validation_attempts(old, {key: changed})
    assert old[key]["result"].status == "passed"


def test_mismatched_map_key_is_rejected(design: DesignState, artifact: GeneratedArtifact) -> None:
    attempt = run_validation_attempt(design, artifact, SQL, _result)
    with pytest.raises(ValueError, match="ID"):
        merge_validation_attempts({}, {str(uuid4()): attempt})


@pytest.mark.parametrize("status", ["passed", "failed", "error", "unverified"])
def test_checkpoint_restart_keeps_the_id_and_does_not_revalidate(
    tmp_path: Path,
    design: DesignState,
    status: str,
) -> None:
    calls = []

    def generate(state: GraphState) -> dict[str, Any]:
        current = state["design"]
        item = write_artifact(tmp_path, current, "ddl", "sql", SQL)
        calls.append(current.revision)
        attempt = run_validation_attempt(current, item, SQL, lambda b: _result(b, status))
        return {
            "generated_artifacts": {artifact_key(item["ref"]): item},
            "validation_attempts": {attempt["validation_id"]: attempt},
        }

    saver = InMemorySaver(serde=checkpoint_serde())
    graph = build_graph({"ddl": generate}, checkpointer=saver)
    config = {"configurable": {"thread_id": design.run_id}}
    graph.invoke(initial_state(design), config)
    saved = graph.get_state(config).values["validation_attempts"]
    assert len(saved) == 1
    (attempt,) = saved.values()
    assert type(attempt["result"]) is SqlValidation
    assert attempt["result"].status == status
    assert attempt["artifact"]["model_hash"] == model_hash(design)

    # 새 그래프가 같은 저장소에서 재개해도 완료한 검증 노드는 다시 호출하지 않는다.
    restarted = build_graph({"ddl": generate}, checkpointer=saver)
    result = restarted.invoke(Command(resume={"decision": "hold"}), config)
    assert result["validation_attempts"] == saved
    assert calls == [1]
    assert model_hash(result["design"]) == model_hash(design)


def test_new_model_and_revision_keep_old_attempt_for_the_same_sql(
    tmp_path: Path,
    design: DesignState,
) -> None:
    calls = []

    def generate(state: GraphState) -> dict[str, Any]:
        current = state["design"]
        item = write_artifact(tmp_path, current, "ddl", "sql", SQL)
        calls.append(current.revision)
        attempt = run_validation_attempt(current, item, SQL, _result)
        return {
            "generated_artifacts": {artifact_key(item["ref"]): item},
            "validation_attempts": {attempt["validation_id"]: attempt},
        }

    saver = InMemorySaver(serde=checkpoint_serde())
    graph = build_graph({"ddl": generate}, checkpointer=saver)
    config = {"configurable": {"thread_id": design.run_id}}
    graph.invoke(initial_state(design), config)
    old = graph.get_state(config).values["validation_attempts"]
    changed = design.evolve(
        revision=2,
        requirements=[
            {
                "id": "REQ-01",
                "text": "고정 시험 요구사항",
                "draft_text": "고정 시험 요구사항",
                "type": "FR",
                "source_ref": {"file_format": "csv", "row": 2},
                "analysis_version": 1,
            }
        ],
    )
    graph.update_state(config, {"design": changed}, as_node="a04")

    graph.invoke(None, config)

    attempts = graph.get_state(config).values["validation_attempts"]
    assert calls == [1, 2]
    assert len(attempts) == 2
    assert all(attempts[k] == v for k, v in old.items())
    assert {a["artifact"]["model_hash"] for a in attempts.values()} == {
        model_hash(design),
        model_hash(changed),
    }
    assert {a["artifact"]["ref"].revision for a in attempts.values()} == {1, 2}
    assert len({a["result"].artifact_hash for a in attempts.values()}) == 1


def test_attempts_from_different_runs_cannot_be_merged(
    tmp_path: Path,
    design: DesignState,
    artifact: GeneratedArtifact,
) -> None:
    other = design.evolve(run_id=str(uuid4()))
    second_file = write_artifact(tmp_path, other, "ddl", "sql", SQL)
    first = run_validation_attempt(design, artifact, SQL, _result)
    second = run_validation_attempt(other, second_file, SQL, _result)

    with pytest.raises(ValueError, match="서로 다른 실행"):
        merge_validation_attempts(
            {first["validation_id"]: first},
            {second["validation_id"]: second},
        )


def test_legacy_checkpoint_without_attempts_does_not_get_fake_results(design: DesignState) -> None:
    legacy = initial_state(design)
    legacy.pop("validation_attempts", None)
    saver = InMemorySaver(serde=checkpoint_serde())
    graph = build_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": design.run_id}}

    result = graph.invoke(legacy, config)

    assert result.get("validation_attempts", {}) == {}
