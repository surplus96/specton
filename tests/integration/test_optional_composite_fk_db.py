"""공유 필수 칼럼·선택 복합 FK의 생성 DDL을 격리 PostgreSQL에서 실행한다."""

from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from specton.codegen.ddl import generate_ddl
from specton.codegen.model import Normalized
from specton.codegen.normalize_step import normalize_design
from specton.contracts import DesignState, Table
from specton.persistence.db import Pool

pytestmark = pytest.mark.db
FIXTURE = Path(__file__).parents[1] / "data/optional_composite_fk.json"


def _insert(conn: psycopg.Connection, table: Table, values: dict[str, str | None]) -> None:
    columns = {c.attribute_id: c.physical_name for c in table.columns}
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table.physical_name),
            sql.SQL(", ").join(sql.Identifier(columns[key]) for key in values),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        tuple(values.values()),
    )


def test_generated_shared_optional_fk_preserves_required_item_integrity(pool: Pool) -> None:
    result = normalize_design(DesignState.model_validate_json(FIXTURE.read_text()))
    assert isinstance(result, Normalized), result
    tables = {t.entity_id: t for t in result.model.tables}
    with pool.connection() as conn:
        conn.execute(generate_ddl(result.model, max_bytes=63).sql, prepare=False)
        for code in ("A", "B"):
            _insert(conn, tables["ENT-ITEM"], {"ATTR-ITEM": code})
        for code, lot in (("A", "L1"), ("B", "L2")):
            _insert(conn, tables["ENT-LOT"], {"ATTR-LOT-ITEM": code, "ATTR-LOT-NO": lot})
        for id, code, lot in (("1", "A", None), ("2", "A", "L1")):
            _insert(
                conn,
                tables["ENT-STOCK"],
                {"ATTR-STOCK": id, "ATTR-STOCK-ITEM": code, "ATTR-STOCK-LOT": lot},
            )
        invalid = (
            ("3", None, None, psycopg.errors.NotNullViolation),
            ("4", "X", None, psycopg.errors.ForeignKeyViolation),
            ("5", "A", "LX", psycopg.errors.ForeignKeyViolation),
            ("6", "A", "L2", psycopg.errors.ForeignKeyViolation),
        )
        for id, code, lot, error in invalid:
            with pytest.raises(error), conn.transaction():
                _insert(
                    conn,
                    tables["ENT-STOCK"],
                    {"ATTR-STOCK": id, "ATTR-STOCK-ITEM": code, "ATTR-STOCK-LOT": lot},
                )
