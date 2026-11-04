"""DB 표의 CHECK 목록·API 경로가 계약과 같은지 (PR #108 리뷰, 06 문서).

DB 없이 `schema.sql`과 앱의 OpenAPI를 읽어 대조한다.
"""

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import get_args

import pytest

from specton.api.main import create_app
from specton.config import Settings
from specton.contracts import ArtifactRef, ExtractionStatus, RunState, SourceRef, SseEventType

SCHEMA = files("specton.persistence").joinpath("schema.sql").read_text(encoding="utf-8")
DRAFT = json.loads(Path("docs/api/openapi.json").read_text(encoding="utf-8"))


def _check_values(table: str, column: str) -> set[str]:
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SCHEMA, re.S)
    assert body is not None, table
    found = re.search(rf"\b{column}\s+text[^,]*?CHECK \({column} IN \((.*?)\)\)", body[1], re.S)
    assert found is not None, f"{table}.{column}"
    return set(re.findall(r"'([^']+)'", found[1]))


@pytest.mark.parametrize(
    ("table", "column", "expected"),
    [
        ("run", "status", {s.value for s in RunState}),
        ("run_event", "event_type", {e.value for e in SseEventType}),
        ("source_block", "extraction_status", {s.value for s in ExtractionStatus}),
        ("artifact", "kind", set(get_args(ArtifactRef.model_fields["kind"].annotation))),
        (
            "artifact",
            "file_format",
            set(get_args(ArtifactRef.model_fields["file_format"].annotation)),
        ),
        (
            "document",
            "file_format",
            set(get_args(SourceRef.model_fields["file_format"].annotation)),
        ),
    ],
)
def test_schema_checks_match_contracts(table: str, column: str, expected: set[str]) -> None:
    assert _check_values(table, column) == expected


def _operations(spec: dict) -> dict[str, tuple[str, str, set[str]]]:  # type: ignore[type-arg]
    """operationId → (메서드, 경로, 응답 코드). `default` 응답은 뺀다."""
    found = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and "operationId" in op:
                codes = set(op.get("responses", {})) - {"default"}
                found[op["operationId"]] = (method, path, codes)
    return found


def test_implemented_routes_match_the_openapi_draft() -> None:
    """구현한 엔드포인트의 경로·메서드와 정상 응답 코드가 초안과 같다."""
    generated = _operations(create_app(Settings(_env_file=None)).openapi())
    draft = _operations(DRAFT)

    for op_id, (method, path, codes) in generated.items():
        assert op_id in draft, op_id
        assert (method, path) == draft[op_id][:2], op_id
        success = {c for c in codes if c.startswith("2")}
        assert success <= draft[op_id][2], op_id


def _query_params(spec: dict) -> dict[str, set[str]]:  # type: ignore[type-arg]
    """operationId → 쿼리 매개변수 이름."""
    found = {}
    for item in spec["paths"].values():
        for op in item.values():
            if isinstance(op, dict) and "operationId" in op:
                params = op.get("parameters", [])
                found[op["operationId"]] = {p["name"] for p in params if p["in"] == "query"}
    return found


def test_implemented_query_params_match_the_openapi_draft() -> None:
    """쿼리 이름이 초안과 같다 (예: 산출물 `file_format`, #16)."""
    generated = _query_params(create_app(Settings(_env_file=None)).openapi())
    draft = _query_params(DRAFT)

    for op_id, names in generated.items():
        assert names == draft[op_id], op_id
