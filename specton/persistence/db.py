"""DB 연결 풀·표 생성·LangGraph checkpointer (ADR-0012).

앱 저장과 checkpointer는 같은 풀을 쓴다. 연결은 짧게 빌리고 돌려준다:
LLM 호출 중이나 SSE 스트림이 열려 있는 동안 연결을 잡고 있지 않는다.
"""

import importlib
import inspect
import pkgutil
from enum import Enum
from importlib.resources import files
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

import specton.contracts
from specton.config import Settings
from specton.contracts.base import Contract

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


# 그래프 상태에 들어가는, 계약 밖의 타입 (R1 그래프). 상태에 새 타입을 넣으면 여기에 더한다
GRAPH_STATE_TYPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("specton.review.rework", "HitlReason"),
        ("specton.review.rework", "ReworkAction"),
    }
)


def _contract_types() -> frozenset[tuple[str, str]]:
    """`specton/contracts/`에 정의된 계약 모델과 열거형 전부. 모듈·타입이 늘면 따라 는다."""
    modules = [
        importlib.import_module(f"specton.contracts.{m.name}")
        for m in pkgutil.iter_modules(specton.contracts.__path__)
    ]
    return frozenset(
        (module.__name__, name)
        for module in modules
        for name, obj in vars(module).items()
        if inspect.isclass(obj)
        and obj.__module__ == module.__name__
        and issubclass(obj, (Contract, Enum))
    )


# 체크포인트에서 다시 읽어도 되는 우리 타입 (#131). 목록에 없는 타입은 LangGraph가 막는다
CHECKPOINT_TYPES = _contract_types() | GRAPH_STATE_TYPES


def checkpoint_serde() -> JsonPlusSerializer:
    """`CHECKPOINT_TYPES`만 허용하는 체크포인트 직렬화기.

    목록을 직접 넘기면 `LANGGRAPH_STRICT_MSGPACK` 설정과 상관없이 목록 밖 타입은 막힌다.
    그래프 단위 테스트의 `InMemorySaver`도 이것을 쓰면 같은 규칙으로 시험할 수 있다.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


def create_checkpointer(pool: Pool) -> PostgresSaver:
    """LangGraph 체크포인트 저장소. `thread_id`는 `run_id`다 (ADR-0012)."""
    saver = PostgresSaver(pool, serde=checkpoint_serde())
    saver.setup()
    return saver
