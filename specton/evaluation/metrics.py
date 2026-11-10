"""분모를 보존하는 순수 채점 함수. 허용 경고를 오탐·정탐으로 바꿔 세지 않는다."""

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from specton.evaluation.models import Classification, Matching


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
    return Counts(len(items.matches), len(items.predicted - predicted), len(items.gold - gold))


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


def warnings(items: Classification) -> dict[str, Any]:
    gold = {i.id: i for i in items.gold}
    predicted = {i.id: i for i in items.predicted}
    counts = Counts()
    permitted = 0
    for alignment in items.alignments:
        expected, actual = gold.pop(alignment.gold), predicted.pop(alignment.predicted)
        counts.tp += len(expected.required_warnings & actual.warnings)
        counts.fn += len(expected.required_warnings - actual.warnings)
        counts.fp += len(actual.warnings - expected.required_warnings - expected.allowed_warnings)
        permitted += len(actual.warnings & expected.allowed_warnings)
    counts.fn += sum(len(i.required_warnings) for i in gold.values())
    counts.fp += sum(len(i.warnings) for i in predicted.values())
    return {**counts.report(), "permitted": permitted}


def splits(items: Classification) -> dict[str, Any]:
    expected = Counter(i.source_id for i in items.gold)
    actual = Counter(i.source_id for i in items.predicted)
    sources = sorted(expected.keys() | actual.keys())
    correct = sum(expected[s] == actual[s] for s in sources)
    return {
        "correct": correct,
        "total": len(sources),
        "accuracy": correct / len(sources) if sources else None,
        "counts": {s: {"expected": expected[s], "actual": actual[s]} for s in sources},
    }
