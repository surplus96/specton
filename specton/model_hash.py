"""생성기와 모델 스냅샷이 공유하는 설계 해시. 파일 해시와는 별개다."""

import hashlib
import json
from typing import Any

from specton.contracts import DesignState

MODEL_FIELDS = ("requirements", "functions", "entities", "relationships")


def model_payload(state: DesignState) -> dict[str, Any]:
    model: dict[str, Any] = {
        name: [item.model_dump(mode="json") for item in getattr(state, name)]
        for name in MODEL_FIELDS
    }
    if state.normalized is not None:
        normalized = state.normalized.model_dump(mode="json")
        # 새 선택 필드가 없는 옛 스냅샷은 기존 해시를 그대로 유지한다.
        for key in ("common_version", "policy_digest"):
            if normalized[key] is None:
                del normalized[key]
        model["normalized"] = normalized
    return model


def model_hash(state: DesignState) -> str:
    return hashlib.sha256(
        json.dumps(model_payload(state), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
