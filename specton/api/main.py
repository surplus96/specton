"""FastAPI 앱 진입점."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from specton import __version__
from specton.api.errors import install_error_handlers
from specton.api.runs import router as runs_router
from specton.config import Settings, get_settings
from specton.persistence.db import Pool, apply_schema, create_pool


class HealthResponse(BaseModel):
    status: str
    version: str


def create_app(settings: Settings | None = None, pool: Pool | None = None) -> FastAPI:
    """앱을 만든다. `pool`을 주면 그 풀을 쓰고 열고 닫지 않는다 (테스트용).

    시작 순서는 docs/11을 따른다: DB 연결 → 앱 표 준비 → API.
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pool is not None:
            yield
            return
        owned = create_pool(settings, open=False)
        owned.open(wait=True)
        try:
            apply_schema(owned)
            app.state.pool = owned
            yield
        finally:
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
