"""#18 리뷰 합류·근거 확인·지적 병합 (04 문서 "지적 확정 절차", TC-F14)."""

from typing import Any

import pytest

from specton.contracts import BranchResult, DesignState, Entity, Finding, Function, Requirement
from specton.review.merge import merge_review

EXPECTED = ("A05", "A07")


def _state() -> DesignState:
    req = Requirement(
        id="REQ-01",
        source_ref={"kind": "csv", "row": 2},
        text="수불 문서에는 하나 이상의 품목 내역을\n등록한다.",
        original_text="수불 문서에는 하나 이상의 품목 내역을 등록한다.",
        type="FR",
        analysis_version=1,
    )
    entity = Entity(
        id="ENT-01",
        pack="inventory",
        name="수불내역",
        description="수불 문서의 품목 내역",
        attributes=[
            {"id": "ATTR-01", "name": "품목코드", "data_type": "integer", "req_ids": ["REQ-01"]}
        ],
        req_ids=["REQ-01"],
    )
    function = Function(id="FUNC-01", name="수불 등록", description="등록", req_ids=["REQ-01"])
    return DesignState(
        run_id="run-1",
        revision=2,
        iteration=1,
        requirements=[req],
        entities=[entity],
        functions=[function],
    )


def _finding(number: int, **changes: Any) -> Finding:
    values: dict[str, Any] = {
        "id": f"A05-1-{number}",
        "source": "llm",
        "reviewer_id": "A05",
        "kind": "missing_line",
        "severity": "major",
        "targets": [{"kind": "entity", "id": "ENT-01"}],
        "evidence": [{"req_id": "REQ-01", "quote": "하나 이상의 품목 내역"}],
        "suggestion": "내역 엔티티를 문서와 1:N으로 잇는다",
        "target_stage": "data_model",
        "fingerprint": f"fp-{number}",
        "iteration": 1,
    }
    return Finding.model_validate({**values, **changes})


def _rule(number: int, **changes: Any) -> Finding:
    values: dict[str, Any] = {
        "id": f"RULE-1-{number}",
        "source": "rule",
        "reviewer_id": None,
        "rule_code": "RULE-03",
        "kind": "missing_pk",
        "severity": "critical",
        "evidence": [{"quote": "ENT-01에 기본 키가 없습니다"}],
        "fingerprint": f"rule-fp-{number}",
    }
    return _finding(number, **{**values, **changes})


def _branch(name: str, *findings: Finding, ok: bool = True, revision: int = 2) -> BranchResult:
    if not ok:
        return BranchResult(branch=name, revision=revision, ok=False, error_code="LLM_TIMEOUT")
    return BranchResult(branch=name, revision=revision, ok=True, findings=findings)


class TestJoin:
    def test_collects_findings_of_all_branches(self) -> None:
        a05 = _finding(1)
        a07 = _finding(2, id="A07-1-1", reviewer_id="A07")

        merged = merge_review(_state(), [_branch("A07", a07), _branch("A05", a05)], EXPECTED)

        assert merged.findings == (a05, a07)
        assert merged.complete
        assert merged.failed_branches == ()

    def test_failed_branch_marks_review_incomplete_but_keeps_others(self) -> None:
        a05 = _finding(1)

        merged = merge_review(_state(), [_branch("A05", a05), _branch("A07", ok=False)], EXPECTED)

        assert merged.findings == (a05,)
        assert not merged.complete
        assert merged.failed_branches == ("A07",)

    def test_missing_branch_counts_as_failed(self) -> None:
        merged = merge_review(_state(), [_branch("A05")], EXPECTED)

        assert merged.failed_branches == ("A07",)

    def test_rejects_result_of_another_revision(self) -> None:
        with pytest.raises(ValueError, match="revision"):
            merge_review(_state(), [_branch("A05", revision=1), _branch("A07")], EXPECTED)

    def test_rejects_unexpected_or_duplicated_branch(self) -> None:
        with pytest.raises(ValueError, match="A06"):
            merge_review(_state(), [_branch("A05"), _branch("A06")], EXPECTED)
        with pytest.raises(ValueError, match="A05"):
            merge_review(_state(), [_branch("A05"), _branch("A05")], EXPECTED)


class TestGrounding:
    def _rejected(self, finding: Finding) -> list[tuple[str, str]]:
        merged = merge_review(_state(), [_branch("A05", finding), _branch("A07")], EXPECTED)
        assert merged.findings == ()
        return [(r.reason, r.detail) for r in merged.rejected]

    def test_rejects_unknown_target(self) -> None:
        finding = _finding(1, targets=[{"kind": "entity", "id": "ENT-99"}])

        assert self._rejected(finding) == [("unknown_target", "entity:ENT-99")]

    def test_rejects_target_of_wrong_kind(self) -> None:
        finding = _finding(1, targets=[{"kind": "relationship", "id": "ENT-01"}])

        assert self._rejected(finding) == [("unknown_target", "relationship:ENT-01")]

    def test_rejects_unknown_evidence_requirement(self) -> None:
        finding = _finding(1, evidence=[{"req_id": "REQ-09", "quote": "품목 내역"}])

        assert self._rejected(finding) == [("unknown_req_id", "REQ-09")]

    def test_rejects_quote_not_in_requirement(self) -> None:
        finding = _finding(1, evidence=[{"req_id": "REQ-01", "quote": "품목은 삭제할 수 없다"}])

        assert self._rejected(finding) == [("quote_not_found", "REQ-01: 품목은 삭제할 수 없다")]

    def test_accepts_known_attribute_and_function_targets(self) -> None:
        finding = _finding(
            1,
            targets=[{"kind": "attribute", "id": "ATTR-01"}, {"kind": "function", "id": "FUNC-01"}],
        )

        merged = merge_review(_state(), [_branch("A05", finding), _branch("A07")], EXPECTED)

        assert merged.findings == (finding,)

    def test_quote_ignores_line_breaks_and_spacing(self) -> None:
        finding = _finding(1, evidence=[{"req_id": "REQ-01", "quote": "품목  내역을 등록한다."}])

        merged = merge_review(_state(), [_branch("A05", finding), _branch("A07")], EXPECTED)

        assert merged.findings == (finding,)

    def test_quote_without_req_id_may_come_from_any_requirement(self) -> None:
        finding = _finding(1, evidence=[{"quote": "하나 이상의 품목"}])

        merged = merge_review(_state(), [_branch("A05", finding), _branch("A07")], EXPECTED)

        assert merged.findings == (finding,)

    def test_rule_findings_skip_quote_check_and_come_first(self) -> None:
        rule = _rule(1)
        llm = _finding(1)

        merged = merge_review(
            _state(), [_branch("A05", llm), _branch("A07")], EXPECTED, rule_findings=[rule]
        )

        assert merged.findings == (rule, llm)

    def test_rule_findings_must_come_from_rules(self) -> None:
        with pytest.raises(ValueError, match="A05-1-1"):
            merge_review(_state(), [], EXPECTED, rule_findings=[_finding(1)])


class TestMerge:
    def test_same_fingerprint_merges_keeping_all_evidence(self) -> None:
        first = _finding(1, fingerprint="same", severity="minor", target_stage=None)
        second = _finding(
            2,
            fingerprint="same",
            target_stage="functions",
            evidence=[
                {"req_id": "REQ-01", "quote": "하나 이상의 품목 내역"},
                {"req_id": "REQ-01", "quote": "수불 문서에는"},
            ],
        )

        merged = merge_review(_state(), [_branch("A05", first, second), _branch("A07")], EXPECTED)

        (only,) = merged.findings
        assert only.id == first.id
        assert only.severity == "major"
        assert only.target_stage == "functions"
        assert [e.quote for e in only.evidence] == ["하나 이상의 품목 내역", "수불 문서에는"]

    def test_merge_keeps_earliest_target_stage(self) -> None:
        first = _finding(1, fingerprint="same", target_stage="data_model")
        second = _finding(2, fingerprint="same", target_stage="requirements")

        merged = merge_review(_state(), [_branch("A05", first, second), _branch("A07")], EXPECTED)

        assert merged.findings[0].target_stage == "requirements"

    def test_rule_and_llm_findings_on_same_target_stay_separate(self) -> None:
        rule = _rule(1)
        llm = _finding(1)

        merged = merge_review(
            _state(), [_branch("A05", llm), _branch("A07")], EXPECTED, rule_findings=[rule]
        )

        assert len(merged.findings) == 2
