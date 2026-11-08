"""실제 DDL 생성·5단계 SQL 검증의 API 그래프 가지 (#17·#167).

노드는 앱 DB에 쓰지 않는다. SQL 결함·미검증은 사람 조치로, 환경·정리 오류는 실행기가
동일 SQL과 검증 기록을 저장한 뒤 실행 실패로 처리한다. RULE-07 Finding 생성은 R4 범위다.
"""

from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

from specton.artifacts import artifact_key
from specton.config import Settings
from specton.contracts import SqlValidation
from specton.ddl_adapter import create_ddl_artifact
from specton.graph import GraphState, Node
from specton.validate.sandbox import validate_sql
from specton.validation_attempts import run_validation_attempt


def ddl_node(
    settings: Settings, *, validate: Callable[[bytes], SqlValidation] | None = None
) -> Node:
    validator = validate if validate is not None else partial(validate_sql, settings=settings)

    def generate(state: GraphState) -> Mapping[str, Any]:
        if state.get("normalization_failed"):
            raise ValueError("DDL 생성: 정리에 실패한 상태입니다")
        design = state["design"]
        result = create_ddl_artifact(
            design, storage_dir=settings.storage_dir, root=settings.pack_root
        )
        attempt = run_validation_attempt(
            design, result.generated, result.prepared.sql_bytes, validator
        )
        return {
            "generated_artifacts": {artifact_key(result.generated["ref"]): result.generated},
            "validation_attempts": {attempt["validation_id"]: attempt},
            "ddl_validation_status": attempt["result"].status,
        }

    return generate
