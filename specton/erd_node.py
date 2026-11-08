"""저장된 정리 결과 → Mermaid 초안 파일 → 공통 산출물 인계 (#17).

정리 결과를 다시 만들거나 DB에 쓰지 않는다. 파일과 메타데이터는 기존 실행기가 게시한다.
PDF와 업무 영역별 출력은 #13의 후속 구현이며 여기서는 상세 ERD 한 파일을 만든다.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from specton.artifacts import GeneratedArtifact, artifact_key, write_artifact
from specton.codegen.erd import render_erd
from specton.contracts import DesignState
from specton.graph import GraphState, Node


def create_erd_artifact(design: DesignState, *, storage_dir: Path) -> GeneratedArtifact:
    """같은 revision의 정리 모델·관계를 UTF-8 `.mmd` 초안으로 저장한다."""
    model = design.normalized
    if model is None:
        raise ValueError("ERD 생성: 정리 결과가 없습니다 (DesignState.normalized)")
    if (design.versions.pack_id, design.versions.pack_version) != (model.pack, model.pack_version):
        raise ValueError("ERD 생성: 실행과 정리 결과의 팩·버전이 다릅니다")
    content = render_erd(model, design.relationships).encode("utf-8")
    return write_artifact(storage_dir, design, "erd", "mmd", content)


def erd_node(storage_dir: Path) -> Node:
    """API의 병렬 생성 가지. 결과는 기존 체크포인트 채널로만 반환한다."""

    def generate(state: GraphState) -> Mapping[str, Any]:
        if state.get("normalization_failed"):
            raise ValueError("ERD 생성: 정리에 실패한 상태입니다")
        generated = create_erd_artifact(state["design"], storage_dir=storage_dir)
        return {"generated_artifacts": {artifact_key(generated["ref"]): generated}}

    return generate
