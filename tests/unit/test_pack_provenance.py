"""공통 팩·검사 정책 고정이 모델 해시에 들어가되 옛 승인 해시는 바꾸지 않는다."""

import hashlib
import json
import shutil

from specton.codegen.normalize_step import normalize_from_state
from specton.contracts import DesignState
from specton.contracts.normalized import Normalized, NormalizedModel
from specton.model_hash import MODEL_FIELDS, model_hash
from specton.packs.build import DEFAULT_ROOT
from specton.packs.provenance import policy_digest
from tests.unit.test_design_rules_node import state


def test_old_normalized_checkpoint_keeps_its_previous_model_hash():
    old = dict(
        pack="inventory",
        pack_version="old",
        rules_version="old",
        lexicon_digest="old",
        tables=[],
        foreign_keys=[],
    )
    design = DesignState(run_id="legacy", normalized=NormalizedModel.model_validate(old))
    payload = {name: [] for name in MODEL_FIELDS}
    payload["normalized"] = old
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert model_hash(design) == expected
    assert (
        model_hash(
            design.evolve(
                normalized=design.normalized.evolve(
                    common_version="0.1.4",
                    policy_digest="new-policy",
                )
            )
        )
        != expected
    )


def test_new_normalization_preserves_common_version_and_policy_digest():
    graph = state(used=True)
    result = normalize_from_state(graph)
    assert isinstance(result, Normalized)
    assert result.model.common_version == "0.1.5"
    assert result.model.policy_digest == policy_digest(DEFAULT_ROOT, "inventory")


def test_policy_digest_detects_settings_and_source_changes(tmp_path):
    root = tmp_path / "packs"
    shutil.copytree(DEFAULT_ROOT, root)
    original = policy_digest(root, "inventory")
    assert original == policy_digest(DEFAULT_ROOT, "inventory")
    for relative in (
        "common/rules.yaml",
        "inventory/standard_selection.yaml",
        "sources/sources.yaml",
    ):
        path = root / relative
        before = path.read_text()
        path.write_text(before + "\n# local change\n")
        assert policy_digest(root, "inventory") != original
        path.write_text(before)
    assert policy_digest(root, "inventory") == original
