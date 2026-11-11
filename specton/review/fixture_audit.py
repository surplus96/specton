"""고정 평가 자료의 오프라인 검토 목록. 의미 정답·승인·독립성을 판정하지 않는다."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from specton.review.eval_fixtures import (
    NORMAL_KINDS,
    FixtureCase,
    FixtureError,
    load_fixture_set,
)

AUDIT_VERSION = "fixture-audit-v1"


def structure_hash(case: FixtureCase) -> str:
    """설명·근거를 제외한 ID/이름 포함 구조. 그래프 동형성·의미 동등성 검사가 아니다."""
    entities = []
    for entity in sorted(case.entities, key=lambda e: e.id):
        item = entity.model_dump(mode="json", exclude={"description", "req_ids"})
        item["attributes"] = (
            sorted(
                [
                    a.model_dump(mode="json", exclude={"description", "req_ids"})
                    for a in entity.attributes
                ],
                key=lambda a: a["id"],
            )
            if entity.attributes is not None
            else None
        )
        entities.append(item)
    relationships = [
        r.model_dump(mode="json", exclude={"rationale", "req_ids"})
        for r in sorted(case.relationships, key=lambda r: r.id)
    ]
    data = json.dumps(
        {"entities": entities, "relationships": relationships},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(data.encode()).hexdigest()


def _case_review(case: FixtureCase) -> dict[str, Any]:
    kinds = {e.id: "entity" for e in case.entities}
    kinds.update({a.id: "attribute" for e in case.entities for a in e.attributes or ()})
    kinds.update({r.id: "relationship" for r in case.relationships})
    return {
        "case_id": case.case_id,
        "case": case.case,
        "source_id": case.source_id,
        "structure_hash": structure_hash(case),
        "entities_with_implicit_attributes": [e.id for e in case.entities if e.attributes is None],
        "expected": [
            {"target": e.target, "target_kind": kinds[e.target], "defect": e.defect}
            for e in case.expected
        ],
    }


def audit(path: Path) -> dict[str, Any]:
    # 파싱한 입력과 해시 대상이 달라지지 않게 중간 변경을 확인한다.
    original = path.read_bytes()
    fixtures = load_fixture_set(path)
    if path.read_bytes() != original:
        raise FixtureError("점검 중 입력 파일이 변경됐습니다")
    groups: dict[str, list[str]] = defaultdict(list)
    for case in fixtures.cases:
        if case.case in NORMAL_KINDS:
            groups[structure_hash(case)].append(case.case_id)
    defects = sorted({e.defect for c in fixtures.cases for e in c.expected})
    return {
        "audit_version": AUDIT_VERSION,
        "fixture_sha256": hashlib.sha256(original).hexdigest(),
        "set": fixtures.set_name,
        "reviewer_id": fixtures.reviewer_id,
        "case_counts": dict(Counter(c.case for c in fixtures.cases)),
        "defect_counts": dict(Counter(e.defect for c in fixtures.cases for e in c.expected)),
        "normal_structure_count": len(groups),
        "same_normal_structure_groups": [ids for ids in groups.values() if len(ids) > 1],
        "source_ids_containing_defect_labels": [
            c.case_id
            for c in fixtures.cases
            if any(label in c.source_id.casefold() for label in defects)
        ],
        "cases": [_case_review(c) for c in fixtures.cases],
        "semantic_validation": "not_performed",
        "approval": "not_granted",
        "limitations": [
            "Same structure does not imply semantic equivalence; descriptions can change meaning.",
            "Different IDs/names may hide equivalent structures; graph isomorphism is not tested.",
            "Label matches are review hints, not proof of model-facing leakage.",
            "This audit does not establish normalization, gold correctness or independence.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = audit(args.fixtures)
        # 입력과 같은 경로를 포함해 기존 평가 자료를 덮어쓰지 않는다.
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (OSError, FixtureError) as exc:
        parser.exit(2, f"{exc}\n")
    print("오프라인 구조 점검 완료. 의미·정답·승인은 별도 검토가 필요합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
