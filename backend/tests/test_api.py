from fastapi.testclient import TestClient

from gae.main import app
from gae.settings import Settings, get_settings

FAKE_SECRETS = {
    "GEMINI_API_KEY": "test-gemini-not-a-real-key",
    "EPC_API_TOKEN": "test-epc-bearer-not-real",
    "MONGODB_URI": "mongodb+srv://user:test-password@example.invalid/db",
    "GOOGLE_SOLAR_API_KEY": "test-solar-not-a-real-key",
}


def _settings_with_fake_secrets(monkeypatch) -> Settings:
    for name, value in FAKE_SECRETS.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_health_reports_ok_without_secrets(monkeypatch) -> None:
    settings = _settings_with_fake_secrets(monkeypatch)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = TestClient(app).get("/api/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["configured"] == {
        "gemini": True,
        "epc": True,
        "mongodb": True,
        "google_solar": True,
    }
    for value in FAKE_SECRETS.values():
        assert value not in response.text


def test_settings_never_print_secrets(monkeypatch) -> None:
    settings = _settings_with_fake_secrets(monkeypatch)
    printed = repr(settings) + str(settings) + settings.model_dump_json()
    for value in FAKE_SECRETS.values():
        assert value not in printed
    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == FAKE_SECRETS["GEMINI_API_KEY"]


def test_unconfigured_settings(monkeypatch) -> None:
    for name in FAKE_SECRETS:
        monkeypatch.delenv(name, raising=False)
    assert not any(Settings(_env_file=None).configured().values())
