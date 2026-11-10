"""평가 설계에 실제 정리를 적용한다. 사전을 보완하거나 실패를 미탐으로 바꾸지 않는다."""

from pathlib import Path

from specton.codegen.normalize_step import normalize_design
from specton.contracts import DesignState
from specton.contracts.normalized import Normalized
from specton.model_hash import model_hash
from specton.packs.build import pack_content_hash, read_lock_versions
from specton.packs.loader import load_pack


def prepare_normalized(state: DesignState, *, root: Path) -> DesignState:
    pack_id = state.versions.pack_id
    if pack_id is None:
        raise ValueError("평가 팩이 없습니다")
    pack = load_pack(pack_id, root=root)
    if pack.manifest.status != "approved" or pack.common.manifest.status != "approved":
        raise ValueError("평가에는 승인된 도메인·공통 팩이 필요합니다")
    for manifest in (pack.manifest, pack.common.manifest):
        folder = root / manifest.name
        recorded = read_lock_versions(folder).get(manifest.version)
        if recorded != pack_content_hash(folder):
            raise ValueError(f"{manifest.name}: 승인 팩 내용이 pack.lock과 다릅니다")
    versioned = state.evolve(versions=state.versions.evolve(pack_version=pack.manifest.version))
    result = normalize_design(versioned, root=root)
    if not isinstance(result, Normalized):
        detail = ", ".join(f"{p.code.value}:{p.target}" for p in result.problems)
        raise ValueError(f"정리에 실패했습니다 ({detail})")
    return versioned.evolve(normalized=result.model)


def state_provenance(state: DesignState) -> dict[str, str]:
    normalized = state.normalized
    if normalized is None:
        return {}
    return {
        "pack": normalized.pack,
        "pack_version": normalized.pack_version,
        "common_version": normalized.common_version or "",
        "policy_digest": normalized.policy_digest or "",
        "lexicon_digest": normalized.lexicon_digest,
        "rules_version": normalized.rules_version,
        "model_hash": model_hash(state),
    }
