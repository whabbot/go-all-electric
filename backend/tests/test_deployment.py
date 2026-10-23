"""Guards are exercised before validation, uploads, or expensive dependencies."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gae.security import GEMINI_PATHS, ApiGuard
from gae.server import configure_logging
from gae.settings import get_settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "judge-secret")
    monkeypatch.setenv("GEMINI_REQUESTS_PER_IP", "2")
    monkeypatch.setenv("GEMINI_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    app = FastAPI()
    app.add_middleware(ApiGuard)

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    def ok(path: str):
        return {"ok": True}

    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_access_gate_all_api_routes(client):
    for path in [*GEMINI_PATHS, "/api/surveys", "/api/epc/search", "/api/access", "/api/new"]:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-Access-Code": "wrong"}).status_code == 401
        assert client.get(path, headers={"X-Access-Code": "judge-secret"}).status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/capture").status_code == 200


def test_unset_code_preserves_open_development(client, monkeypatch):
    monkeypatch.delenv("ACCESS_CODE")
    get_settings.cache_clear()
    assert client.get("/api/epc/search").status_code == 200
    for _ in range(4):
        assert client.post("/api/photos/check").status_code == 200


@pytest.mark.parametrize("path", sorted(GEMINI_PATHS))
def test_shared_per_ip_allowance(client, path):
    headers = {"X-Access-Code": "judge-secret", "X-Forwarded-For": "203.0.113.1"}
    assert client.post(path, headers=headers).status_code == 200
    assert client.post("/api/photos/check", headers=headers).status_code == 200
    response = client.post(path, headers=headers)
    assert response.status_code == 429
    assert "Demo limit" in response.json()["detail"]
    assert int(response.headers["Retry-After"]) > 0
    headers["X-Forwarded-For"] = "203.0.113.2"
    assert client.post(path, headers=headers).status_code == 200
    assert client.get("/api/epc/search", headers=headers).status_code == 200


def test_spoofed_prefix_cannot_reset_limit(client):
    headers = {"X-Access-Code": "judge-secret"}
    for fake in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        response = client.post(
            "/api/photos/check", headers={**headers, "X-Forwarded-For": f"{fake}, 203.0.113.1"}
        )
    assert response.status_code == 429


def test_wrong_codes_do_not_consume_allowance(client):
    for _ in range(3):
        assert client.post("/api/photos/check").status_code == 401
    assert (
        client.post("/api/photos/check", headers={"X-Access-Code": "judge-secret"}).status_code
        == 200
    )


def test_window_expires(client, monkeypatch):
    monkeypatch.setattr("gae.security.time.monotonic", lambda: 100)
    headers = {"X-Access-Code": "judge-secret"}
    for _ in range(2):
        assert client.post("/api/photos/check", headers=headers).status_code == 200
    assert client.post("/api/photos/check", headers=headers).status_code == 429
    monkeypatch.setattr("gae.security.time.monotonic", lambda: 161)
    assert client.post("/api/photos/check", headers=headers).status_code == 200


def test_container_logging_drops_access_and_upstream_query_urls(caplog):
    access = logging.getLogger("uvicorn.access")
    http = logging.getLogger("httpx")
    old_disabled, old_level = access.disabled, http.level
    try:
        configure_logging()
        with caplog.at_level(logging.INFO):
            access.info("GET /api/epc/search?postcode=SAMPLE")
            http.info("HTTP Request: GET https://epc.example/search?postcode=SAMPLE")
        assert "SAMPLE" not in caplog.text
        assert access.disabled
        assert http.level == logging.WARNING
    finally:
        access.disabled, http.level = old_disabled, old_level


def test_static_spa_and_api_404s(tmp_path, monkeypatch):
    import gae.main as main

    monkeypatch.setattr(main, "app", FastAPI())
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>APP</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    main.serve_frontend(tmp_path)
    with TestClient(main.app) as client:
        assert client.get("/capture").text == "<html>APP</html>"
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/missing").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/missing.png").status_code == 404
