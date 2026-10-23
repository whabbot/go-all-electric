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

    gemini_api_key: SecretStr | None = None
    epc_api_email: SecretStr | None = None
    epc_api_key: SecretStr | None = None
    mongodb_uri: SecretStr | None = None
    google_solar_api_key: SecretStr | None = None

    def configured(self) -> dict[str, bool]:
        """Which integrations have credentials, without revealing any value."""
        return {
            "gemini": self.gemini_api_key is not None,
            "epc": self.epc_api_email is not None and self.epc_api_key is not None,
            "mongodb": self.mongodb_uri is not None,
            "google_solar": self.google_solar_api_key is not None,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
