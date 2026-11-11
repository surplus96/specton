"""오프라인 통합 보고. 미실행·실패와 측정하지 않은 값을 따로 보존한다."""

from dataclasses import asdict
from typing import Any

from specton.evaluation import metrics
from specton.evaluation.models import (
    Alignment,
    Classification,
    Document,
    Evaluation,
    Matching,
    Prediction,
    Truth,
    WarningPolicy,
)


def combined_classification(documents: list[Document]) -> Classification:
    """문서마다 ID 공간을 분리해 반복 REQ-01·원문 ID가 섞이지 않게 한다."""
    gold: list[Truth] = []
    predicted: list[Prediction] = []
    alignments: list[Alignment] = []
    source_warnings: dict[str, WarningPolicy] = {}
    allowed_split_counts: dict[str, frozenset[int]] = {}
    for index, doc in enumerate(documents):
        prefix = f"{index}:"
        gold.extend(
            i.model_copy(update={"id": prefix + i.id, "source_id": prefix + i.source_id})
            for i in doc.classification.gold
        )
        predicted.extend(
            i.model_copy(update={"id": prefix + i.id, "source_id": prefix + i.source_id})
            for i in doc.classification.predicted
        )
        alignments.extend(
            i.model_copy(update={"gold": prefix + i.gold, "predicted": prefix + i.predicted})
            for i in doc.classification.alignments
        )
        source_warnings.update(
            {
                prefix + source: policy
                for source, policy in doc.classification.source_warnings.items()
            }
        )
        allowed_split_counts.update(
            {
                prefix + source: counts
                for source, counts in doc.classification.allowed_split_counts.items()
            }
        )
    return Classification(
        gold=tuple(gold),
        predicted=tuple(predicted),
        alignments=tuple(alignments),
        source_warnings=source_warnings,
        allowed_split_counts=allowed_split_counts,
    )


def object_scores(documents: list[Document], *, detection: bool = False) -> dict[str, Any]:
    keys = (
        ("rule", "llm", "filtered")
        if detection
        else ("functions", "entities", "attributes", "relationships")
    )
    report = {}
    for key in keys:
        measured: list[Matching] = [
            value
            for d in documents
            for name, value in (d.detections if detection else d.objects).items()
            if name == key
        ]
        counts = [metrics.matching_counts(i) for i in measured]
        total = metrics.Counts(
            *(sum(asdict(c)[field] for c in counts) for field in ("tp", "fp", "fn"))
        )
        f1s = [c.report()["f1"] for c in counts if c.report()["f1"] is not None]
        report[key] = {
            "reported_documents": len(measured),
            "micro": total.report(),
            "macro_f1": sum(f1s) / len(f1s) if f1s else None,
            "permitted_predictions": sum(len(i.permitted.predicted) for i in measured),
        }
        if detection:
            report[key]["normal_false_positives"] = sum(
                metrics.matching_counts(d.detections[key]).fp
                for d in documents
                if key in d.detections and d.detections[key].normal
            )
    return report


def usage(documents: list[Document]) -> dict[str, Any]:
    fields = ("wall_time_ms", "input_tokens", "output_tokens", "retries", "reworks", "cost_usd")
    return {
        name: {
            "reported_runs": sum(getattr(d, name) is not None for d in documents),
            "total": sum(getattr(d, name) for d in documents if getattr(d, name) is not None)
            if any(getattr(d, name) is not None for d in documents)
            else None,
        }
        for name in fields
    }


def condition_report(documents: list[Document]) -> dict[str, Any]:
    done = [d for d in documents if d.status == "completed"]
    items = combined_classification(done)
    classification = metrics.classification(items)
    macro = [metrics.classification(d.classification)["macro_f1"] for d in done]
    measured = [value for value in macro if value is not None]
    return {
        "total_runs": len(documents),
        "completed_runs": len(done),
        "excluded_from_quality": [
            {"run_id": d.run_id, "status": d.status} for d in documents if d.status != "completed"
        ],
        "classification": classification,
        "document_macro_f1": sum(measured) / len(measured) if measured else None,
        "warnings": metrics.warnings(items),
        "splits": metrics.splits(items),
        "objects": object_scores(done),
        "detections": object_scores(done, detection=True),
        "ddl": {
            "passed": sum(d.ddl == "passed" for d in documents),
            "total": len(documents),
            "success_rate": sum(d.ddl == "passed" for d in documents) / len(documents),
            "statuses": {
                s: sum(d.ddl == s for d in documents)
                for s in ("passed", "failed", "error", "unverified", "not_generated")
            },
        },
        "usage": usage(documents),
    }


def build_report(batch: Evaluation) -> dict[str, Any]:
    conditions = sorted({d.condition for d in batch.documents})
    return {
        "scoring_policy": "offline-v2",
        "dataset": batch.dataset,
        "gold_version": batch.gold_version,
        "gold_variant": batch.gold_variant,
        "gold_hash": batch.gold_hash,
        "approval_ref": batch.approval_ref,
        "planned_document_ids": sorted(batch.planned_document_ids),
        "denominator_policy": {
            "quality": "completed runs only; failures and not-run are listed separately",
            "ddl": "all planned runs, including failed and not-run",
            "zero": "undefined precision/recall/F1 are null; macro averages defined scores",
            "matching": "one approved equivalence group is one TP; unmatched items are FP/FN",
            "permitted_warnings": "reported separately, neither TP nor FP",
            "source_warnings": "union of child warnings per original source; no duplicate counts",
            "warning_alternatives": "one required OR group is one TP or one FN",
            "permitted_defects": "approved permitted matches are neither TP, FP nor FN",
            "optional_objects": "approved optional object matches are neither TP, FP nor FN",
            "splits": "approved count alternatives; semantic equivalence needs separate approval",
        },
        "conditions": {
            c: condition_report([d for d in batch.documents if d.condition == c])
            for c in conditions
        },
        "runs": [run_report(d) for d in batch.documents],
    }


def run_report(doc: Document) -> dict[str, Any]:
    result = doc.model_dump(mode="json", exclude={"classification", "objects", "detections"})
    result["quality"] = None
    if doc.status == "completed":
        result["quality"] = {
            "classification": metrics.classification(doc.classification),
            "warnings": metrics.warnings(doc.classification),
            "splits": metrics.splits(doc.classification),
            "objects": object_scores([doc]),
            "detections": object_scores([doc], detection=True),
        }
    return result
