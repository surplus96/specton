"""검증·사람 승인한 현재 산출물을 같은 바이트의 승인본으로 인계한다 (#17·#167)."""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from specton.artifacts import artifact_key, artifact_path, write_artifact
from specton.graph import GraphState, Node


def export_node(storage_dir: Path) -> Node:
    def export(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        generated = {}
        for item in state.get("generated_artifacts", {}).values():
            ref = item["ref"]
            if ref.revision != design.revision:
                continue
            content = artifact_path(storage_dir, design.run_id, ref).read_bytes()
            if hashlib.sha256(content).hexdigest() != ref.hash:
                raise ValueError("승인본 파일이 승인한 해시와 다릅니다")
            approved = write_artifact(
                storage_dir, design, ref.kind, ref.file_format, content, approved=True
            )
            generated[artifact_key(ref)] = approved
        return {"generated_artifacts": generated}

    return export
