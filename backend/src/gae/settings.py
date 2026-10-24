"""Server-side settings loaded from the environment or a local `.env` file.

Every credential is a `SecretStr`, so it prints as `**********` in reprs, logs and tracebacks.
Secrets are read here and used only by server-side clients; they are never returned by the
API or sent to the frontend.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `.env` next to wherever the server starts, then the repo root when started in backend/.
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # Salted scrypt hash of the shared code; unset keeps local development open.
    access_code_hash: SecretStr | None = None
    # Signs session cookies; required (32+ bytes) whenever the hash is set.
    session_secret: SecretStr | None = None
    session_ttl_seconds: int = 12 * 3600
    # Only plain-http localhost may turn this off; refused under Cloud Run.
    session_cookie_secure: bool = True
    session_attempts_per_ip: int = 10
    session_attempt_window_seconds: int = 900
    # Retired plaintext code: read only so a stale setting refuses to start.
    access_code: SecretStr | None = None
    gemini_requests_per_ip: int = 30
    gemini_limit_window_seconds: int = 3600

    gemini_api_key: SecretStr | None = None
    epc_api_token: SecretStr | None = None
    mongodb_uri: SecretStr | None = None
    google_solar_api_key: SecretStr | None = None
    # Model ids are not secrets; override to swap models without a code change.
    gemini_lead_model: str = "gemini-4-argon"
    gemini_fast_model: str = "gemini-3.8-flash"

    def configured(self) -> dict[str, bool]:
        """Which integrations have credentials, without revealing any value."""
        return {
            "gemini": self.gemini_api_key is not None,
            "epc": bool(self.epc_api_token and self.epc_api_token.get_secret_value().strip()),
            "mongodb": self.mongodb_uri is not None,
            "google_solar": self.google_solar_api_key is not None,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
