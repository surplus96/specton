"""분모를 보존하는 순수 채점 함수. 허용 경고를 오탐·정탐으로 바꿔 세지 않는다."""

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from specton.evaluation.models import Classification, Matching, WarningPolicy


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def report(self) -> dict[str, Any]:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        denominator = 2 * self.tp + self.fp + self.fn
        return {
            **asdict(self),
            "precision": precision,
            "recall": recall,
            "f1": 2 * self.tp / denominator if denominator else None,
        }


def matching_counts(items: Matching) -> Counts:
    gold = {i for m in items.matches for i in m.gold}
    predicted = {i for m in items.matches for i in m.predicted}
    permitted = items.permitted.predicted
    return Counts(
        len(items.matches), len(items.predicted - predicted - permitted), len(items.gold - gold)
    )


def classification(items: Classification) -> dict[str, Any]:
    gold = {i.id: i for i in items.gold}
    predicted = {i.id: i for i in items.predicted}
    matrix: Counter[tuple[str, str]] = Counter()
    for alignment in items.alignments:
        matrix[gold.pop(alignment.gold).label, predicted.pop(alignment.predicted).label] += 1
    matrix.update((i.label, "missing") for i in gold.values())
    matrix.update(("extra", i.label) for i in predicted.values())
    by_label = {
        label: Counts(
            matrix[label, label],
            sum(n for (a, b), n in matrix.items() if b == label and a != label),
            sum(n for (a, b), n in matrix.items() if a == label and b != label),
        )
        for label in ("FR", "NFR")
    }
    reports = {k: v.report() for k, v in by_label.items()}
    f1s = [r["f1"] for r in reports.values() if r["f1"] is not None]
    return {
        "labels": reports,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "confusion": {
            a: {b: matrix[a, b] for b in ("FR", "NFR", "missing")} for a in ("FR", "NFR", "extra")
        },
    }


def warning_counts(policy: WarningPolicy, actual: frozenset[str]) -> tuple[Counts, int]:
    alternatives = {kind for group in policy.required_warning_groups for kind in group}
    return Counts(
        len(policy.required_warnings & actual)
        + sum(bool(group & actual) for group in policy.required_warning_groups),
        len(actual - policy.required_warnings - policy.allowed_warnings - alternatives),
        len(policy.required_warnings - actual)
        + sum(not group & actual for group in policy.required_warning_groups),
    ), len(actual & policy.allowed_warnings)


def warnings(items: Classification) -> dict[str, Any]:
    gold = {i.id: i for i in items.gold}
    predicted = {i.id: i for i in items.predicted}
    results = []
    for alignment in items.alignments:
        expected, actual = gold.pop(alignment.gold), predicted.pop(alignment.predicted)
        if expected.source_id not in items.source_warnings:
            results.append(warning_counts(expected, actual.warnings))
    results.extend(
        warning_counts(i, frozenset())
        for i in gold.values()
        if i.source_id not in items.source_warnings
    )
    results.extend(
        (Counts(fp=len(i.warnings)), 0)
        for i in predicted.values()
        if i.source_id not in items.source_warnings
    )
    for source, policy in items.source_warnings.items():
        actual_warnings = frozenset(
            kind for i in items.predicted if i.source_id == source for kind in i.warnings
        )
        results.append(warning_counts(policy, actual_warnings))
    counts = Counts(*(sum(asdict(c)[k] for c, _ in results) for k in ("tp", "fp", "fn")))
    return {
        **counts.report(),
        "permitted": sum(n for _, n in results),
        "source_policies": len(items.source_warnings),
    }


def splits(items: Classification) -> dict[str, Any]:
    expected = Counter(i.source_id for i in items.gold)
    actual = Counter(i.source_id for i in items.predicted)
    sources = sorted(expected.keys() | actual.keys())
    allowed = {s: items.allowed_split_counts.get(s, frozenset({expected[s]})) for s in sources}
    correct = sum(actual[s] in allowed[s] for s in sources)
    return {
        "correct": correct,
        "total": len(sources),
        "accuracy": correct / len(sources) if sources else None,
        "counts": {
            s: {"expected": expected[s], "allowed": sorted(allowed[s]), "actual": actual[s]}
            for s in sources
        },
    }
