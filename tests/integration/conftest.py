"""DB 테스트 공용 fixture. 테스트마다 임시 schema를 만들어 쓰고 지운다."""

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest

from specton.config import Settings
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
