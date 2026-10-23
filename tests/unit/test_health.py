from fastapi.testclient import TestClient

from specton import __version__
from specton.api.main import create_app


def test_health_returns_ok_with_version() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
