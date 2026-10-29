"""지적 지문 (04 문서 "지적 확정 절차"). 리뷰어와 규칙 검사(#15)가 같은 함수를 쓴다.

지문이 같으면 같은 문제로 보고 병합하고(#18), 이전 반복과 같으면 반복 지적으로 본다(ADR-0010).
"""

import hashlib
import json
from collections.abc import Iterable

from specton.contracts.findings import FindingTarget

FINGERPRINT_LENGTH = 16


def fingerprint(origin: str, kind: str, targets: Iterable[FindingTarget]) -> str:
    """출처·지적 종류·대상이 같으면 같다. 문구와 대상 순서는 보지 않는다.

    origin은 LLM 지적이면 reviewer_id(A05 등), 규칙 지적이면 rule_code(RULE-01 등)다.
    """
    keys = sorted(f"{t.kind}:{t.id}" for t in targets)
    payload = json.dumps([origin, kind, keys], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]
