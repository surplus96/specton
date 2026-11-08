"""설계 상태 → RTM 엑셀·CSV 초안 파일 → 공통 산출물 인계 (#14).

DB에 쓰지 않는다. 파일과 메타데이터는 기존 실행기가 게시한다. 실제 그래프 등록은
ERD(#178)처럼 실행기 연결(#17)에서 한다.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from specton.artifacts import GeneratedArtifact, artifact_key, write_artifact
from specton.codegen.rtm import render_rtm_csv, render_rtm_xlsx
from specton.contracts import DesignState
from specton.graph import GraphState, Node


def create_rtm_artifacts(design: DesignState, *, storage_dir: Path) -> list[GeneratedArtifact]:
    """같은 revision의 RTM을 `.xlsx`·`.csv` 초안 두 파일로 저장한다."""
    return [
        write_artifact(storage_dir, design, "rtm", "xlsx", render_rtm_xlsx(design)),
        write_artifact(storage_dir, design, "rtm", "csv", render_rtm_csv(design)),
    ]


def rtm_node(storage_dir: Path) -> Node:
    """생성 가지. 결과는 기존 체크포인트 채널로만 반환한다."""

    def generate(state: GraphState) -> Mapping[str, Any]:
        generated = create_rtm_artifacts(state["design"], storage_dir=storage_dir)
        return {"generated_artifacts": {artifact_key(g["ref"]): g for g in generated}}

    return generate
