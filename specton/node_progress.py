"""실행기가 공개하는 노드 메타데이터. 그래프 입력·출력 원문은 공개하지 않는다 (#289)."""

from collections.abc import Mapping
from typing import Any

from specton.contracts import DesignState

NODES = frozenset(
    (
        "parse",
        "a01",
        "a02",
        "a03",
        "a04",
        "normalize",
        "ddl",
        "erd",
        "rtm",
        "rules",
        "A05",
        "A06",
        "A07",
        "A08",
        "a09",
        "export",
    )
)
STAGES = {
    "parse": "parsing",
    "a01": "analysing",
    "a02": "designing",
    "a03": "designing",
    "a04": "designing",
    "normalize": "designing",
    "ddl": "generating",
    "erd": "generating",
    "rtm": "generating",
    "rules": "reviewing",
    "export": "exporting",
}


def normalization_summary(design: DesignState) -> dict[str, Any] | None:
    model = design.normalized
    if model is None:
        return None
    return {
        "tables": len(model.tables),
        "columns": sum(len(t.columns) for t in model.tables),
        "foreign_keys": len(model.foreign_keys),
        "pack_id": model.pack,
        "pack_version": model.pack_version,
        "common_version": model.common_version,
    }


def node_result(name: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """task result에서 허용한 수치·분류만 고른다. 내부 예외·프롬프트를 직렬화하지 않는다."""
    summary: dict[str, Any] = {}
    if name == "ddl" and result.get("ddl_validation_status") is not None:
        summary["validation_status"] = result["ddl_validation_status"].value
    if name == "normalize":
        design = result.get("design")
        if isinstance(design, DesignState):
            summary["normalization"] = normalization_summary(design)
        summary["normalization_failed"] = bool(result.get("normalization_failed"))
        summary["problem_kinds"] = [f.kind for f in result.get("rule_findings", ())]
    if name == "a09" and result.get("router_decision") is not None:
        summary["router_decision"] = result["router_decision"]
    branches = result.get("branches", {})
    if branches:
        summary["reviewers"] = list(branches)
        summary["failed_branches"] = [name for name, branch in branches.items() if not branch.ok]
    return summary
