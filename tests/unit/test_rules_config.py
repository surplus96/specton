"""`domain_packs/common/rules.yaml`의 값이 계약 열거형과 맞는지 (#89).

규칙 검사(#15)·팩 로더(#11)가 읽기 전까지 이 파일을 쓰는 코드가 없으므로, 값 오류를 여기서 막는다.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from specton.contracts.base import Crud, TargetStage
from specton.contracts.findings import Severity

RULES = Path(__file__).resolve().parents[2] / "domain_packs/common/rules.yaml"


def _config() -> dict[str, Any]:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _checks() -> list[dict[str, Any]]:
    config = _config()
    return [*config["rules"], *config["standard_compliance"]["checks"]]


def test_check_ids_are_unique() -> None:
    ids = [c["id"] for c in _checks()]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("check", _checks(), ids=lambda c: c["id"])
def test_severity_and_stage_are_contract_values_or_undecided(check: dict[str, Any]) -> None:
    assert check["severity"] is None or check["severity"] in {s.value for s in Severity}
    assert check["target_stage"] is None or check["target_stage"] in {s.value for s in TargetStage}


def test_rule_violations_are_critical() -> None:
    """ADR-0010: 규칙 위반은 critical."""
    assert {r["severity"] for r in _config()["rules"]} == {Severity.CRITICAL.value}


def test_crud_exemptions_name_operations() -> None:
    reasons = _config()["crud_exemption_reasons"]

    assert all(ops and set(ops) <= {c.value for c in Crud} for ops in reasons.values())
    # 사용 중지는 사용여부를 바꾸는 수정(U)이므로 soft_delete는 삭제만 면제한다
    assert reasons["soft_delete"] == [Crud.DELETE.value]
