"""FastAPI 앱 진입점."""

from fastapi import FastAPI
from pydantic import BaseModel

from specton import __version__


class HealthResponse(BaseModel):
    status: str
    version: str


def create_app() -> FastAPI:
    app = FastAPI(title="Specton", version=__version__)

    @app.get("/health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app


app = create_app()
