"""DB 연결 풀·표 생성·LangGraph checkpointer (ADR-0012).

앱 저장과 checkpointer는 같은 풀을 쓴다. 연결은 짧게 빌리고 돌려준다:
LLM 호출 중이나 SSE 스트림이 열려 있는 동안 연결을 잡고 있지 않는다.
"""

from importlib.resources import files
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from specton.config import Settings

Pool = ConnectionPool[Connection[DictRow]]


def create_pool(settings: Settings, *, schema: str | None = None, open: bool = True) -> Pool:
    """앱 DB 연결 풀. `schema`는 테스트 격리용 search_path다.

    checkpointer가 요구하는 대로 autocommit·dict 행을 쓴다. 여러 문장을 묶을 때는
    `conn.transaction()`으로 감싼다.
    """
    kwargs: dict[str, Any] = {"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0}
    if schema is not None:
        kwargs["options"] = f"-c search_path={schema}"
    return ConnectionPool(
        str(settings.app_database_url),
        min_size=1,
        max_size=settings.db_pool_size,
        kwargs=kwargs,
        connection_class=Connection[DictRow],
        open=open,
    )


def apply_schema(pool: Pool) -> None:
    """플랫폼 저장 표를 만든다. 이미 있는 표는 지우지 않고 빠진 칸만 더한다."""
    sql = files("specton.persistence").joinpath("schema.sql").read_text(encoding="utf-8")
    with pool.connection() as conn, conn.transaction():
        # 고정된 패키지 파일이다. 여러 문장이라 prepared statement로 보내지 않는다
        conn.execute(sql.encode(), prepare=False)


def create_checkpointer(pool: Pool) -> PostgresSaver:
    """LangGraph 체크포인트 저장소. `thread_id`는 `run_id`다 (ADR-0012)."""
    saver = PostgresSaver(pool)
    saver.setup()
    return saver
