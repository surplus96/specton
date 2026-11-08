"""설계 상태 → 기능 명세서 Markdown 초안 파일 → 공통 산출물 인계 (#14).

DB에 쓰지 않는다. 파일과 메타데이터는 기존 실행기가 게시한다. 실제 그래프 등록은
ERD(#178)처럼 실행기 연결(#17)에서 한다. PDF는 승인 때 #13의 공용 엔진이 만든다.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from specton.artifacts import GeneratedArtifact, artifact_key, write_artifact
from specton.codegen.function_spec import render_function_spec
from specton.contracts import DesignState
from specton.graph import GraphState, Node


def create_function_spec_artifact(design: DesignState, *, storage_dir: Path) -> GeneratedArtifact:
    """같은 revision의 기능·엔티티로 UTF-8 `.md` 초안을 저장한다."""
    content = render_function_spec(design).encode("utf-8")
    return write_artifact(storage_dir, design, "functions", "md", content)


def function_spec_node(storage_dir: Path) -> Node:
    """생성 가지. 결과는 기존 체크포인트 채널로만 반환한다."""

    def generate(state: GraphState) -> Mapping[str, Any]:
        generated = create_function_spec_artifact(state["design"], storage_dir=storage_dir)
        return {"generated_artifacts": {artifact_key(generated["ref"]): generated}}

    return generate
