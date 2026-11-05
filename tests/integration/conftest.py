"""DB 테스트 공용 fixture. 테스트마다 임시 schema를 만들어 쓰고 지운다."""

from collections.abc import Callable, Iterator
from uuid import uuid4

import psycopg
import pytest

from specton.config import Settings
from specton.contracts import (
    Attribute,
    DesignState,
    Entity,
    Finding,
    Function,
    Requirement,
    SourceRef,
    SourceRequirement,
)
from specton.contracts.base import RequirementType
from specton.persistence.db import Pool, apply_schema, create_pool


@pytest.fixture
def pool() -> Iterator[Pool]:
    settings = Settings(_env_file=None)
    schema = f"test_{uuid4().hex[:12]}"
    try:
        with psycopg.connect(str(settings.app_database_url), autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA {schema}")  # type: ignore[arg-type]
    except psycopg.OperationalError:
        pytest.skip("로컬 DB가 없습니다 (docker compose up -d db)")
    p = create_pool(settings, schema=schema)
    try:
        apply_schema(p)
        yield p
    finally:
        p.close()
        with psycopg.connect(str(settings.app_database_url), autocommit=True) as admin:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")  # type: ignore[arg-type]


StateFactory = Callable[[str, str], DesignState]


@pytest.fixture
def sample_state() -> StateFactory:
    """`sample_state(run_id, document_id)`로 화면 조회·저장 테스트용 설계 상태를 만든다."""
    return _sample_state


def _sample_state(run_id: str, document_id: str) -> DesignState:
    """원문 1건과 요구사항·기능·엔티티·지적 각 1건."""
    src = SourceRef(file_format="xlsx", sheet="요구사항", row=5)
    attribute = Attribute(
        id="ATTR-01", name="주문번호", data_type="varchar", length=20, is_key=True,
        nullable=False, req_ids=["REQ-01"],
    )  # fmt: skip
    finding = Finding(
        id="A05-1-1", source="llm", reviewer_id="A05", kind="missing_line", severity="major",
        targets=[{"kind": "entity", "id": "ENT-01"}],
        evidence=[{"req_id": "REQ-01", "quote": "주문을 취소"}],
        suggestion="취소 사유 칸을 둔다", fingerprint="fp-1", iteration=1,
    )  # fmt: skip
    return DesignState(
        run_id=run_id,
        source_requirements=[
            SourceRequirement(
                document_id=document_id,
                block_id="B-1",
                source_ref=src,
                source_text="주문을 취소할 수 있다",
                extraction_status="pass",
            )
        ],
        requirements=[
            Requirement(
                id="REQ-01",
                source_ref=src,
                text="주문을 취소할 수 있다",
                draft_text="주문을 취소할 수 있다",
                type=RequirementType.FR,
                analysis_version=1,
            )
        ],
        functions=[
            Function(
                id="FUNC-01", name="주문 취소", description="주문을 취소한다", req_ids=["REQ-01"]
            )
        ],
        entities=[
            Entity(
                id="ENT-01",
                pack="inventory",
                name="주문",
                description="고객 주문",
                attributes=[attribute],
                req_ids=["REQ-01"],
            )
        ],
        findings=[finding],
    )
