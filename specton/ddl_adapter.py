"""정리된 설계 → DDL 바이트 → 사전 SQL 검사 (#17).

#165 생성기와 #169 검사기를 연결한다. SQL은 UTF-8로 한 번만 인코딩하며, 검사한 바이트를
그대로 반환한다. 호출자는 #163의 공통 저장 함수에도 이 바이트를 전달해야 한다.

이 결과는 호출 내부에서만 쓰며 GraphState·체크포인트의 새 계약으로 등록하지 않는다.
#163 공통 저장·#164 실제 정리 연결을 기반으로 한 API 그래프 등록·파일/DB 게시와
#167 검증 기록·승인 연결, #15 RULE-07 지적 변환은 후속 범위다.
현재 검사는 파싱·허용 AST까지이므로 정상 SQL도 전체 상태는 unverified다. 실패·장애 결과를
승인 가능 상태로 바꾸지 않으며, 생성기·팩 읽기 예외는 실행 오류로 그대로 전달한다.
"""

from dataclasses import dataclass
from pathlib import Path

from specton.codegen.ddl import DdlResult, generate_ddl
from specton.codegen.naming import DEFAULT_PACK_ROOT, load_naming_rules
from specton.contracts import DesignState
from specton.validate.allowed_sql import SqlValidation, check_allowed_sql


@dataclass(frozen=True)
class PreparedDdl:
    """동일 바이트의 생성 정보와 사전검사 결과. 사람 승인 여부를 표현하지 않는다."""

    sql_bytes: bytes
    generation: DdlResult
    validation: SqlValidation


def prepare_ddl(design: DesignState, *, root: Path = DEFAULT_PACK_ROOT) -> PreparedDdl:
    """저장된 정리 결과로 SQL과 사전검사 결과를 준비한다. 입력 상태는 바꾸지 않는다.

    정리 결과가 없으면 재정리하거나 빈 SQL을 만들지 않는다. 실행에 기록된 팩과 정리 결과의
    팩·버전이 다르면 다른 실행의 결과로 간주해 거절한다. 현재 팩 버전으로 덮어쓰지 않는다.
    """
    model = design.normalized
    if model is None:
        raise ValueError("DDL 준비: 정리 결과가 없습니다 (DesignState.normalized)")
    if (design.versions.pack_id, design.versions.pack_version) != (model.pack, model.pack_version):
        raise ValueError("DDL 준비: 실행과 정리 결과의 팩·버전이 다릅니다")

    rules = load_naming_rules(root)
    generation = generate_ddl(model, max_bytes=rules.max_bytes)
    sql_bytes = generation.sql.encode("utf-8")
    validation = check_allowed_sql(sql_bytes)
    return PreparedDdl(sql_bytes=sql_bytes, generation=generation, validation=validation)
