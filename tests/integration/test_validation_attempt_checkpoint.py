"""#167: 실제 PostgreSQL 체크포인트를 다시 열어도 검증 시도·문맥이 보존된다."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.types import Command

from specton.artifacts import artifact_key, write_artifact
from specton.contracts import DesignState, SqlValidation, ValidationIssue, ValidationStep
from specton.contracts.validation import VALIDATION_STEPS
from specton.graph import GraphState, build_graph, initial_state
from specton.persistence.db import Pool, create_checkpointer
from specton.validation_attempts import run_validation_attempt

pytestmark = pytest.mark.db


@pytest.mark.parametrize("status", ["passed", "failed", "error", "unverified"])
def test_recreated_postgres_checkpointer_preserves_the_same_attempt(
    pool: Pool,
    tmp_path: Path,
    status: str,
) -> None:
    sql = b"CREATE TABLE fixture (id integer PRIMARY KEY);\n"
    design = DesignState(run_id=str(uuid4()), revision=1)
    calls = []

    def generate(state: GraphState) -> dict[str, Any]:
        current = state["design"]
        item = write_artifact(tmp_path, current, "ddl", "sql", sql)

        def validate(payload: bytes) -> SqlValidation:
            assert payload == sql
            calls.append(current.revision)
            values = {
                "passed": ("passed",) * 5,
                "failed": ("failed", "not_run", "not_run", "not_run", "not_run"),
                "error": ("passed", "passed", "error", "not_run", "not_run"),
                "unverified": ("passed", "passed", "not_run", "not_run", "not_run"),
            }[status]
            steps = tuple(
                ValidationStep(
                    name=name,
                    status=value,
                    issues=(ValidationIssue(code="fixture_error"),)
                    if value in ("failed", "error")
                    else (),
                )
                for name, value in zip(VALIDATION_STEPS, values, strict=True)
            )
            return SqlValidation(
                status=status,
                artifact_hash=item["ref"].hash,
                validator_version="fixture-v1",
                policy_version="fixture-p1",
                postgres_version="postgresql-18",
                steps=steps,
            )

        attempt = run_validation_attempt(current, item, sql, validate)
        return {
            "generated_artifacts": {artifact_key(item["ref"]): item},
            "validation_attempts": {attempt["validation_id"]: attempt},
        }

    config = {"configurable": {"thread_id": design.run_id}}
    first = build_graph({"ddl": generate}, checkpointer=create_checkpointer(pool))
    first.invoke(initial_state(design), config)
    saved = first.get_state(config).values["validation_attempts"]
    assert len(saved) == 1

    # 새 checkpointer와 graph가 DB에서 다시 읽는다. SQL 검증 자체는 고정 응답으로 대신한다.
    restarted = build_graph({"ddl": generate}, checkpointer=create_checkpointer(pool))
    restored = restarted.get_state(config).values["validation_attempts"]
    assert restored == saved
    (attempt,) = restored.values()
    assert type(attempt["result"]) is SqlValidation
    assert attempt["result"].status == status
    if status in ("failed", "error"):
        issue = next(s.issues[0] for s in attempt["result"].steps if s.issues)
        assert type(issue) is ValidationIssue

    result = restarted.invoke(Command(resume={"decision": "hold"}), config)
    assert result["validation_attempts"] == saved
    assert calls == [1]
