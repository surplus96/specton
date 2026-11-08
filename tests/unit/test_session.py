"""세션 발급 (ADR-0011): 쿠키가 없으면 발급하고, 있으면 같은 값을 owner_ref로 쓴다."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from specton.api.session import SESSION_COOKIE, SESSION_MAX_AGE, OwnerRef
from specton.config import Settings


def _client() -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(_env_file=None)  # 쿠키 Secure 여부를 읽는다 (#21)

    @app.get("/whoami")
    def whoami(owner: OwnerRef) -> dict[str, int]:
        return {"length": len(owner)}

    return TestClient(app)


def test_issues_http_only_cookie_when_missing() -> None:
    response = _client().get("/whoami")

    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in header
    assert "SameSite=lax" in header


def test_session_survives_a_browser_restart() -> None:
    """브라우저 세션 쿠키가 아니라 Max-Age가 있어야 다시 열어도 같은 owner_ref다."""
    header = _client().get("/whoami").headers["set-cookie"]

    assert f"Max-Age={SESSION_MAX_AGE}" in header
    assert SESSION_MAX_AGE >= 365 * 24 * 60 * 60


def test_keeps_the_issued_session() -> None:
    client = _client()
    first = client.get("/whoami").cookies[SESSION_COOKIE]

    second = client.get("/whoami")

    assert "set-cookie" not in second.headers
    assert client.cookies[SESSION_COOKIE] == first


def test_each_client_gets_a_different_session() -> None:
    one = _client().get("/whoami").cookies[SESSION_COOKIE]
    two = _client().get("/whoami").cookies[SESSION_COOKIE]

    assert one != two


def test_replaces_a_cookie_that_was_not_issued_by_the_server() -> None:
    client = _client()
    client.cookies.set(SESSION_COOKIE, "admin")

    response = client.get("/whoami")

    assert response.cookies[SESSION_COOKIE] != "admin"


def test_session_value_is_not_in_the_body() -> None:
    response = _client().get("/whoami")

    assert response.cookies[SESSION_COOKIE] not in response.text
