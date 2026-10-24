"""Guards are exercised before validation, uploads, or expensive dependencies."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import gae.main as main
from gae import security
from gae.security import GEMINI_PATHS, AccessHash, ApiGuard, hash_access_code
from gae.server import configure_logging
from gae.settings import get_settings

CODE = "judge-secret"
# Hash once: each scrypt check is deliberately slow.
CODE_HASH = hash_access_code(CODE)
SECRET = "s" * 48


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ACCESS_CODE_HASH", CODE_HASH)
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    monkeypatch.setenv("GEMINI_REQUESTS_PER_IP", "2")
    monkeypatch.setenv("GEMINI_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("SESSION_ATTEMPTS_PER_IP", "3")
    get_settings.cache_clear()
    app = FastAPI()
    app.add_middleware(ApiGuard)

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    def ok(path: str):
        return {"ok": True}

    # https, so the client returns the Secure cookie as a browser would.
    with TestClient(app, base_url="https://testserver") as client:
        yield client
    get_settings.cache_clear()


def sign_in(client, code=CODE, ip="198.51.100.9"):
    return client.post("/api/session", json={"code": code}, headers={"X-Forwarded-For": ip})


def test_hash_round_trip_rejects_wrong_code():
    parsed = AccessHash.parse(CODE_HASH)
    assert CODE_HASH.startswith("scrypt$32768$8$3$")
    assert CODE not in CODE_HASH
    assert len(parsed.salt) >= 16
    assert parsed.matches(CODE)
    assert not parsed.matches("judge-secreT")
    assert not parsed.matches("")
    assert hash_access_code(CODE) != CODE_HASH


@pytest.mark.parametrize(
    "value", ["", CODE, "bcrypt$1$2$3$AAAA$AAAA", CODE_HASH.replace("$32768$", "$1000$")]
)
def test_malformed_hash_is_refused(value):
    with pytest.raises(RuntimeError, match="ACCESS_CODE_HASH"):
        AccessHash.parse(value)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "SESSION_SECRET"),
        ({"SESSION_SECRET": "x" * 31}, "SESSION_SECRET"),
        ({"SESSION_SECRET": SECRET, "ACCESS_CODE": CODE}, "ACCESS_CODE is no longer"),
        ({"SESSION_SECRET": SECRET, "ACCESS_CODE_HASH": "plain"}, "ACCESS_CODE_HASH"),
        (
            {"SESSION_SECRET": SECRET, "SESSION_COOKIE_SECURE": "false", "K_SERVICE": "gae"},
            "SESSION_COOKIE_SECURE",
        ),
    ],
)
def test_unsafe_configuration_refuses_to_start(monkeypatch, env, message):
    monkeypatch.setenv("ACCESS_CODE_HASH", CODE_HASH)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match=message), TestClient(main.app):
            pass
    finally:
        get_settings.cache_clear()


def test_valid_configuration_starts(monkeypatch):
    monkeypatch.setenv("ACCESS_CODE_HASH", CODE_HASH)
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/access").status_code == 401
    finally:
        get_settings.cache_clear()


def test_correct_code_sets_strict_session_cookie(client):
    response = sign_in(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    attributes = {part.strip().split("=")[0].lower() for part in cookie.split(";")}
    assert cookie.startswith("gae_session=")
    assert {"httponly", "secure", "path", "samesite"} <= attributes
    assert "Path=/api" in cookie
    assert "SameSite=strict" in cookie
    assert "max-age" not in attributes
    assert "expires" not in attributes


def test_insecure_cookie_only_when_configured(client, monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    response = sign_in(client)
    assert response.status_code == 200
    assert "secure" not in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("body", [{"code": "wrong"}, {"code": ""}, {}, [], "x"])
def test_wrong_code_is_refused_without_a_hint(client, body):
    response = client.post("/api/session", json=body)
    assert response.status_code == 401
    assert response.json() == {"detail": "Access code required or incorrect."}
    assert "set-cookie" not in response.headers
    assert client.get("/api/access").status_code == 401


def test_session_gates_all_api_routes(client):
    paths = [*GEMINI_PATHS, "/api/surveys", "/api/epc/search", "/api/access", "/api/new"]
    for path in paths:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-Access-Code": CODE}).status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/capture").status_code == 200
    assert client.get("/api/session").status_code == 405
    assert sign_in(client).status_code == 200
    for path in paths:
        assert client.get(path).status_code == 200


def test_tampered_or_foreign_cookie_is_refused(client, monkeypatch):
    sign_in(client)
    token = client.cookies["gae_session"]
    issued, expires, signature = token.split(".")
    forged = [
        f"{issued}.{int(expires) + 3600}.{signature}",
        f"{issued}.{expires}.{signature[:-1]}{'B' if signature.endswith('A') else 'A'}",
        "",
        "garbage",
        f"{issued}.{expires}",
    ]
    for value in forged:
        client.cookies.set("gae_session", value, domain="testserver.local", path="/api")
        assert len(client.cookies.jar) == 1
        assert client.get("/api/access").status_code == 401, value
    # A session from an old access code or a different signing secret is refused.
    client.cookies.set("gae_session", token, domain="testserver.local", path="/api")
    assert client.get("/api/access").status_code == 200
    monkeypatch.setenv("SESSION_SECRET", "t" * 48)
    get_settings.cache_clear()
    assert client.get("/api/access").status_code == 401
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    monkeypatch.setenv("ACCESS_CODE_HASH", hash_access_code(CODE))
    get_settings.cache_clear()
    assert client.get("/api/access").status_code == 401


def test_session_expires(client, monkeypatch):
    monkeypatch.setattr("gae.security.time.time", lambda: 1_000_000)
    sign_in(client)
    assert client.get("/api/access").status_code == 200
    monkeypatch.setattr("gae.security.time.time", lambda: 1_000_000 + 12 * 3600 - 1)
    assert client.get("/api/access").status_code == 200
    monkeypatch.setattr("gae.security.time.time", lambda: 1_000_000 + 12 * 3600)
    assert client.get("/api/access").status_code == 401
    monkeypatch.setattr("gae.security.time.time", lambda: 1_000_000 + 12 * 3600 + 1)
    assert client.get("/api/access").status_code == 401
    # Issued far in the future (a forged clock) is refused too.
    monkeypatch.setattr("gae.security.time.time", lambda: 1_000_000 - 3600)
    assert client.get("/api/access").status_code == 401


def test_shorter_ttl_caps_existing_sessions(client, monkeypatch):
    sign_in(client)
    monkeypatch.setenv("SESSION_TTL_SECONDS", "3600")
    get_settings.cache_clear()
    assert client.get("/api/access").status_code == 401


def test_failed_attempts_are_limited_per_ip(client, monkeypatch):
    for _ in range(3):
        assert sign_in(client, "wrong").status_code == 401
    response = sign_in(client)
    assert response.status_code == 429
    assert "Too many attempts" in response.json()["detail"]
    assert int(response.headers["Retry-After"]) > 0
    assert "set-cookie" not in response.headers
    # Other visitors are unaffected, and successes do not use up the allowance.
    for _ in range(5):
        assert sign_in(client, ip="198.51.100.10").status_code == 200
    assert sign_in(client, "wrong", ip="198.51.100.10").status_code == 401
    # The window resets.
    now = security.time.monotonic()
    monkeypatch.setattr("gae.security.time.monotonic", lambda: now + 901)
    assert sign_in(client).status_code == 200


def test_code_and_cookie_never_logged_or_echoed(client, caplog):
    with caplog.at_level(logging.DEBUG):
        wrong = sign_in(client, "wrong-" + CODE)
        right = sign_in(client)
        token = client.cookies["gae_session"]
        probe = client.get("/api/access")
    assert CODE not in caplog.text and token not in caplog.text
    for response in (wrong, right, probe):
        assert CODE not in response.text
        assert all(CODE not in value for value in response.headers.values())
        assert token not in response.text


def test_unset_hash_preserves_open_development(client, monkeypatch):
    monkeypatch.delenv("ACCESS_CODE_HASH")
    monkeypatch.delenv("SESSION_SECRET")
    get_settings.cache_clear()
    assert client.get("/api/epc/search").status_code == 200
    for _ in range(4):
        assert client.post("/api/photos/check").status_code == 200
    response = client.post("/api/session", json={"code": "anything"})
    assert response.status_code == 200
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("path", sorted(GEMINI_PATHS))
def test_shared_per_ip_allowance(client, path):
    sign_in(client)
    headers = {"X-Forwarded-For": "203.0.113.1"}
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
    sign_in(client)
    for fake in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        response = client.post(
            "/api/photos/check", headers={"X-Forwarded-For": f"{fake}, 203.0.113.1"}
        )
    assert response.status_code == 429


def test_signed_out_requests_do_not_consume_allowance(client):
    for _ in range(3):
        assert client.post("/api/photos/check").status_code == 401
    sign_in(client)
    assert client.post("/api/photos/check").status_code == 200


def test_window_expires(client, monkeypatch):
    sign_in(client)
    monkeypatch.setattr("gae.security.time.monotonic", lambda: 100)
    for _ in range(2):
        assert client.post("/api/photos/check").status_code == 200
    assert client.post("/api/photos/check").status_code == 429
    monkeypatch.setattr("gae.security.time.monotonic", lambda: 161)
    assert client.post("/api/photos/check").status_code == 200


def test_hash_helper_prints_only_the_hash(monkeypatch, capsys):
    answers = iter([CODE, CODE])
    monkeypatch.setattr("gae.security.getpass.getpass", lambda prompt: next(answers))
    assert security.main(["hash-access-code"]) == 0
    out, err = capsys.readouterr()
    assert CODE not in out + err
    assert AccessHash.parse(out.strip()).matches(CODE)
    assert out.count("\n") == 1


@pytest.mark.parametrize("answers", [[CODE, CODE + "x"], ["", ""]])
def test_hash_helper_refuses_mismatch_or_empty(monkeypatch, capsys, answers):
    typed = iter(answers)
    monkeypatch.setattr("gae.security.getpass.getpass", lambda prompt: next(typed))
    assert security.main(["hash-access-code"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert CODE not in err


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
