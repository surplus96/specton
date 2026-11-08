"""최종 검토 직전 manifest 승인 후보를 저장한다. 앱 DB 게시·승인은 실행기 책임이다.

후보의 JSON은 승인 후 공개할 내용(approved=true)이며 ArtifactRef는 approved=false다.
승인 전 다운로드를 막고, 실제 승인은 DB와 approval_basis가 결정한다. 자신의 해시는 제외한다.
"""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from specton.artifacts import GeneratedArtifact, artifact_key, write_artifact
from specton.codegen.manifest import build_manifest, render_manifest
from specton.contracts import DesignState
from specton.graph import GraphState, Node


def approved_manifest_content(design: DesignState, generated: Iterable[GeneratedArtifact]) -> bytes:
    """같은 revision의 파일을 승인한 뒤 공개할 JSON 바이트. 실제 승인 기록은 만들지 않는다."""
    files: list[GeneratedArtifact] = [
        {**item, "ref": item["ref"].evolve(approved=True)}
        for item in generated
        if item["ref"].revision == design.revision and item["ref"].kind != "manifest"
    ]
    return render_manifest(build_manifest(design, files))


def manifest_node(storage_dir: Path) -> Node:
    def prepare(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        files = [
            item
            for item in state.get("generated_artifacts", {}).values()
            if item["ref"].revision == design.revision and item["ref"].kind != "manifest"
        ]
        if not files:
            return {}  # 정리 실패에는 가짜 manifest를 만들지 않는다
        if design.normalized is None:
            raise ValueError("manifest 생성: 성공한 정리 결과가 없습니다")
        content = approved_manifest_content(design, files)
        generated = write_artifact(storage_dir, design, "manifest", "json", content)
        return {"generated_artifacts": {artifact_key(generated["ref"]): generated}}

    return prepare
