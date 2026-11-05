"""FastAPI 앱 진입점."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from specton import __version__
from specton.agent_nodes import openai_design_nodes
from specton.api.errors import install_error_handlers
from specton.api.runs import router as runs_router
from specton.config import Settings, get_settings
from specton.graph import GraphState, build_graph
from specton.parse_node import parse_node
from specton.persistence.db import Pool, apply_schema, create_checkpointer, create_pool
from specton.runner import Runner


class HealthResponse(BaseModel):
    status: str
    version: str


def create_graph(
    settings: Settings, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """실행기가 돌릴 그래프 (#17). 문서 읽기·설계 노드(A01~A04)는 실제 노드, 나머지는 빈 노드다."""
    nodes = {"parse": parse_node(settings.storage_dir), **openai_design_nodes(settings)}
    return build_graph(nodes, checkpointer=checkpointer)


def create_app(settings: Settings | None = None, pool: Pool | None = None) -> FastAPI:
    """앱을 만든다. `pool`을 주면 그 풀을 쓰고 열고 닫지 않는다 (테스트용).

    시작 순서는 docs/11을 따른다: DB 연결 → 앱 표·checkpointer 준비 → 실행기 → API.
    중지할 때는 실행기를 먼저 멈춰 실행 중인 run을 노드 경계에서 저장하고 lease를 반납한다.
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pool is not None:
            yield
            return
        owned = create_pool(settings, open=False)
        owned.open(wait=True)
        runner: Runner | None = None
        try:
            apply_schema(owned)
            graph = create_graph(settings, create_checkpointer(owned))
            runner = Runner(owned, graph, settings)
            runner.start()
            app.state.pool, app.state.runner = owned, runner
            yield
        finally:
            if runner is not None:
                runner.stop()
            owned.close()

    app = FastAPI(title="Specton", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    if pool is not None:
        app.state.pool = pool
    install_error_handlers(app)
    app.include_router(runs_router)

    @app.get("/health", operation_id="health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app


app = create_app()
