"""정리된 설계 → DDL 바이트 → 사전 SQL 검사 (#17).

#165 생성기와 #169 검사기를 연결한다. SQL은 UTF-8로 한 번만 인코딩하며, 검사한 바이트를
그대로 반환한다. create_ddl_artifact는 #163의 공통 파일 저장 함수에 이 바이트를 전달한다.

이 결과는 호출 내부에서만 쓰며 GraphState·체크포인트의 새 계약으로 등록하지 않는다.
API의 ddl_node가 이 결과를 다섯 단계 검증기와 검증 시도 채널에 연결하고, 실행기가 DB에
게시한다. SQL 결함(failed)은 ddl_node가 RULE-07 지적으로 바꾼다 (review/ddl_findings.py).
이 함수의 사전 검사는 파싱·허용 AST까지라 정상 SQL도 이 결과의 상태는 unverified다. 격리 DB
실행·롤백·잔여 확인까지 하는 다섯 단계 검사는 ddl_node가 같은 바이트로 따로 한다. 실패·장애
결과를 승인 가능 상태로 바꾸지 않으며, 생성기·팩 읽기 예외는 실행 오류로 그대로 전달한다.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from specton.artifacts import GeneratedArtifact, write_artifact
from specton.codegen.ddl import DdlResult, generate_ddl
from specton.codegen.naming import DEFAULT_PACK_ROOT, load_naming_rules
from specton.contracts import DesignState, SqlValidation
from specton.validate.allowed_sql import check_allowed_sql


@dataclass(frozen=True)
class PreparedDdl:
    """동일 바이트의 생성 정보와 사전검사 결과. 사람 승인 여부를 표현하지 않는다."""

    sql_bytes: bytes
    generation: DdlResult
    validation: SqlValidation


@dataclass(frozen=True)
class DdlArtifact:
    """초안 파일 인계 정보와 해당 바이트의 생성·검사 결과. 호출 내부에서만 사용한다."""

    prepared: PreparedDdl
    generated: GeneratedArtifact


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


def create_ddl_artifact(
    design: DesignState, *, storage_dir: Path, root: Path = DEFAULT_PACK_ROOT
) -> DdlArtifact:
    """DDL을 준비하고 검사한 바이트 그대로 초안 파일에 쓴 뒤 두 결과를 함께 반환한다.

    failed·error도 SQL과 함께 보존한다. 호출자는 검사 결과를 기록하고 처리 경로를 결정해야
    한다. generated만 기존 그래프 채널로 인계할 수 있으며, 이 반환 객체 자체를 체크포인트에
    넣지 않는다. 실제 API에서는 ddl_node와 실행기가 공용 계약에 맞춰 검증 기록·오류 종료·승인에
    연결한다.
    """
    prepared = prepare_ddl(design, root=root)
    if hashlib.sha256(prepared.sql_bytes).hexdigest() != prepared.validation.artifact_hash:
        raise ValueError("DDL 파일 저장: 검사한 SQL 바이트의 해시가 다릅니다")
    generated = write_artifact(storage_dir, design, "ddl", "sql", prepared.sql_bytes)
    return DdlArtifact(prepared=prepared, generated=generated)
