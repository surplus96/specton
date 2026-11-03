"""요청마다 쓰는 의존성: 설정, DB 연결.

연결은 요청 처리 동안만 빌리고 돌려준다. SSE는 이 의존성을 쓰지 않고 확인할 때마다 빌린다.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from psycopg import Connection
from psycopg.rows import DictRow

from specton.config import Settings
from specton.persistence.db import Pool


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


def get_conn(pool: Annotated[Pool, Depends(get_pool)]) -> Iterator[Connection[DictRow]]:
    with pool.connection() as conn:
        yield conn


SettingsDep = Annotated[Settings, Depends(get_settings)]
PoolDep = Annotated[Pool, Depends(get_pool)]
ConnDep = Annotated[Connection[DictRow], Depends(get_conn)]
