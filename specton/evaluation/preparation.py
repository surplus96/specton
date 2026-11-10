"""비공개 승인 정답 목록을 선택 대기 입력으로 바꾼다. 실행·채점하지 않는다."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Self

from pydantic import Field, model_validator

from specton.contracts.base import NfrCategory
from specton.evaluation.models import Classification, Record, Text, Truth, WarningPolicy, unique


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_record(record: Record) -> dict[str, Any]:
    """집합의 직렬화 순서를 고정해 프로세스마다 준비 파일 해시가 달라지지 않게 한다."""
    result: dict[str, Any] = json.loads(json.dumps(record.model_dump(), default=sorted))
    return result


def split_counts(cells: dict[str, Any]) -> list[int]:
    primary = cells["기대 분할 수"]
    if type(primary) is not int or primary < 1:
        raise ValueError("기대 분할 수는 양의 정수여야 합니다")
    raw = str(cells.get("허용 분할 수") or primary).strip()
    match = re.fullmatch(r"([1-9][0-9]*)(?:\s*[\u223c~\uff5e\u2013-]\s*([1-9][0-9]*))?", raw)
    if match is None:
        raise ValueError("허용 분할 수 형식을 확인해야 합니다")
    low, high = int(match[1]), int(match[2] or match[1])
    if high < low or high - low > 100:
        raise ValueError("허용 분할 수 범위를 확인해야 합니다")
    return sorted({primary, *range(low, high + 1)})


def review_row(row: dict[str, Any]) -> dict[str, Any]:
    cells = row["approved_cells"]
    tasks = ["select_variant_before_observations", "approve_source_id_mapping_and_alignment"]
    if cells.get("분할 결과별 정답") or cells.get("허용 분할 조합"):
        tasks.append("review_split_semantics")
    if cells["기대 분류"] == "혼합" or cells.get("허용 분류"):
        tasks.append("review_labels_per_child")
    if max(split_counts(cells)) > 1 and (cells.get("기대 경고(필수)") or cells.get("허용 경고")):
        tasks.append("allocate_source_warnings_to_children")
    return {
        "source_id": row["source_id"],
        "worksheet": row["worksheet"],
        "row": row["row"],
        "approved_cells": cells,
        "candidate_split_counts": split_counts(cells),
        "review_tasks": tasks,
        "selection": None,
    }


def prepare(catalog_path: Path) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("kind") != "scoring_preparation" or catalog.get("a01_gold_status") != "approved":
        raise ValueError("승인된 A01 준비 목록이 필요합니다")
    if not catalog["documents"]:
        raise ValueError("준비할 문서가 없습니다")
    unique([document["document_id"] for document in catalog["documents"]], "준비 문서")
    documents = []
    for document in catalog["documents"]:
        if not document["rows"]:
            raise ValueError("준비할 정답 행이 없습니다")
        unique([row["source_id"] for row in document["rows"]], "정답 원문")
        for prefix in ("input", "gold"):
            if digest(Path(document[f"{prefix}_file"])) != document[f"{prefix}_sha256"]:
                raise ValueError("입력·정답 원본 해시가 준비 목록과 다릅니다")
        documents.append(
            {
                "document_id": document["document_id"],
                "input_hash": document["input_sha256"],
                "gold_hash": document["gold_sha256"],
                "rows": [review_row(row) for row in document["rows"]],
            }
        )
    return {
        "kind": "gold_selection_plan",
        "ready_to_score": False,
        "catalog_hash": digest(catalog_path),
        "gold_version": catalog["gold_version"],
        "approval_ref": catalog["approval_ref"],
        "model_gold_status": catalog["model_gold_status"],
        "pack_version": catalog["pack_version"],
        "common_version": catalog["common_version"],
        "policy_digest": catalog["policy_digest"],
        "documents": documents,
    }


class Selection(Record):
    """사람이 승인한 분할별 라벨·경고. 원문 단위 경고를 자동 복제하지 않는다."""

    variant: Text
    approval_ref: Text
    items: tuple[Truth, ...] = Field(min_length=1)
    nfr_categories: dict[str, NfrCategory] = Field(default_factory=dict)
    source_warnings: WarningPolicy | None = None

    @model_validator(mode="after")
    def valid_categories(self) -> Self:
        policies = (
            {self.items[0].source_id: self.source_warnings}
            if self.source_warnings is not None
            else {}
        )
        Classification(gold=self.items, source_warnings=policies)
        required = {item.id for item in self.items if item.label == "NFR"}
        if self.nfr_categories.keys() != required:
            raise ValueError("NFR 항목마다 세부 분류를 명시해야 합니다")
        return self


def selected_gold(catalog_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """모든 행의 명시적 선택으로 정답만 변환한다. 관측·승인 대응은 별도로 필요하다."""
    baseline = prepare(catalog_path)
    if without_selections(plan) != baseline:
        raise ValueError("선택 계획의 원본·행·대안이 준비 목록과 다릅니다")
    documents = []
    for document in plan["documents"]:
        items: list[Truth] = []
        selections = []
        source_warnings: dict[str, WarningPolicy] = {}
        allowed_split_counts: dict[str, frozenset[int]] = {}
        for row in document["rows"]:
            choice = Selection.model_validate(row["selection"])
            if len(choice.items) not in row["candidate_split_counts"]:
                raise ValueError("승인된 분할 수 범위 밖입니다")
            if any(item.source_id != row["source_id"] for item in choice.items):
                raise ValueError("선택한 정답이 다른 원문을 가리킵니다")
            items.extend(choice.items)
            if choice.source_warnings is not None:
                source_warnings[row["source_id"]] = choice.source_warnings
            allowed_split_counts[row["source_id"]] = frozenset(row["candidate_split_counts"])
            selections.append(json_record(choice))
        gold = Classification(
            gold=tuple(items),
            source_warnings=source_warnings,
            allowed_split_counts=allowed_split_counts,
        )
        documents.append(
            {
                "document_id": document["document_id"],
                "input_hash": document["input_hash"],
                "gold_hash": document["gold_hash"],
                "selections": selections,
                "gold": json_record(gold)["gold"],
                "source_warnings": json_record(gold)["source_warnings"],
                "allowed_split_counts": json_record(gold)["allowed_split_counts"],
            }
        )
    return {
        "kind": "selected_gold_preparation",
        "ready_to_score": False,
        "catalog_hash": plan["catalog_hash"],
        "gold_version": plan["gold_version"],
        "approval_ref": plan["approval_ref"],
        "pack_version": plan["pack_version"],
        "common_version": plan["common_version"],
        "policy_digest": plan["policy_digest"],
        "model_gold_status": plan["model_gold_status"],
        "documents": documents,
    }


def without_selections(plan: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(json.dumps(plan))
    for document in result["documents"]:
        for row in document["rows"]:
            row["selection"] = None
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="비공개 A01 정답 선택 계획 준비 (LLM·DB 사용 안 함)"
    )
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--selections", type=Path, help="검토·선택을 마친 계획 JSON")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            selected_gold(args.catalog, json.loads(args.selections.read_text(encoding="utf-8")))
            if args.selections
            else prepare(args.catalog)
        )
        with args.out.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"준비 실패: {type(error).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
