"""FastAPI 앱 진입점."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from specton import __version__
from specton.agent_nodes import openai_agent_nodes
from specton.api.errors import install_error_handlers
from specton.api.runs import router as runs_router
from specton.config import Settings, get_settings
from specton.ddl_node import ddl_node
from specton.design_rules_node import design_rules_node
from specton.document_node import document_node
from specton.erd_node import erd_node
from specton.export_node import export_node
from specton.graph import GraphState, Node, build_graph
from specton.manifest_node import manifest_node
from specton.normalization_node import normalization_node
from specton.parse_node import parse_node
from specton.pdf_adapter import erd_pdf_renderer
from specton.persistence.db import Pool, apply_schema, create_checkpointer, create_pool
from specton.review.normalization_findings import failure_mapper, rule_severities
from specton.runner import Runner


class HealthResponse(BaseModel):
    status: str
    version: str


def create_graph(
    settings: Settings,
    checkpointer: BaseCheckpointSaver[Any],
    agent_nodes: Mapping[str, Node] | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """문서·에이전트·정리·생성·SQL 검증·RULE-02·06을 연결한다. SC는 후속 범위다.

    `agent_nodes`(A01~A09)를 주지 않으면 실제 OpenAI client 노드를 쓴다. 시험은 고정 규칙 LLM
    노드를 넣어 나머지 실제 노드를 그대로 끝까지 돌린다 (#19 기본 흐름 검증).
    """
    mapper = failure_mapper(rule_severities(root=settings.pack_root))
    erd = (
        erd_node(settings.storage_dir, pdf=erd_pdf_renderer(settings))
        if settings.enable_erd_pdf
        else erd_node(settings.storage_dir)
    )
    nodes = {
        **(agent_nodes if agent_nodes is not None else openai_agent_nodes(settings)),
        "parse": parse_node(settings.storage_dir),
        "normalize": normalization_node(mapper, root=settings.pack_root),
        "erd": erd,
        "ddl": ddl_node(settings),
        "rtm": document_node(settings.storage_dir),
        "rules": design_rules_node(root=settings.pack_root),
        "wait_review": manifest_node(settings.storage_dir),
        "export": export_node(settings.storage_dir),
    }
    return build_graph(nodes, checkpointer=checkpointer, max_rework=settings.max_rework_iterations)


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
