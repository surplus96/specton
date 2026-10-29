"""지적 지문: 리뷰어(LLM)와 규칙 검사(#15)가 같은 함수로 만든다."""

from specton.contracts.findings import FindingTarget
from specton.review.fingerprint import fingerprint


def _targets(*ids: str) -> list[FindingTarget]:
    return [FindingTarget(kind="entity", id=i) for i in ids]


def test_same_origin_kind_and_targets_give_same_print() -> None:
    assert fingerprint("A05", "missing_fk", _targets("ENT-01")) == fingerprint(
        "A05", "missing_fk", _targets("ENT-01")
    )


def test_target_order_does_not_matter() -> None:
    assert fingerprint("RULE-04", "bad_parent_key", _targets("ENT-01", "ENT-02")) == fingerprint(
        "RULE-04", "bad_parent_key", _targets("ENT-02", "ENT-01")
    )


def test_origin_kind_or_targets_change_the_print() -> None:
    base = fingerprint("A05", "missing_fk", _targets("ENT-01"))

    assert fingerprint("A08", "missing_fk", _targets("ENT-01")) != base
    assert fingerprint("A05", "wrong_cardinality", _targets("ENT-01")) != base
    assert fingerprint("A05", "missing_fk", _targets("ENT-02")) != base
