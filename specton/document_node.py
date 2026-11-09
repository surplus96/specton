"""#17 문서 생성 가지: 같은 고정 모델의 기능 명세·RTM을 공통 저장 경로에 인계한다.

기존 `rtm` 가지를 사용하여 체크포인트 노드 구성을 유지한다. 생성·파일 쓰기만 수행하며
DB 게시·승인·재시작 복구는 기존 실행기와 export가 담당한다.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from specton.artifacts import artifact_key
from specton.function_spec_node import create_function_spec_artifact
from specton.graph import GraphState, Node
from specton.rtm_node import create_rtm_artifacts


def document_node(storage_dir: Path) -> Node:
    """명세 Markdown과 RTM Excel·CSV를 같은 revision·모델의 초안으로 반환한다."""

    def generate(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        model = design.normalized
        if state.get("normalization_failed") or model is None:
            raise ValueError("문서 생성: 성공한 정리 결과가 없습니다")
        if (design.versions.pack_id, design.versions.pack_version) != (
            model.pack,
            model.pack_version,
        ):
            raise ValueError("문서 생성: 실행과 정리 결과의 팩·버전이 다릅니다")
        # 기능이 없으면 빈 명세서를 성공 파일로 만들지 않는다. RTM과 후속 RULE-02에서
        # 미연결 FR을 드러내고 재작업하게 한다. 명세 렌더러 자체의 입력 검사는 유지한다.
        generated = (
            [create_function_spec_artifact(design, storage_dir=storage_dir)]
            if design.functions
            else []
        )
        generated.extend(create_rtm_artifacts(design, storage_dir=storage_dir))
        return {"generated_artifacts": {artifact_key(item["ref"]): item for item in generated}}

    return generate
