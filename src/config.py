"""Application settings loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is missing or empty. "
            f"Copy .env.example to .env and set a value for {key}."
        )
    return value


class _Settings:
    @property
    def cimis_app_key(self) -> str:
        return _require("CIMIS_APP_KEY")


settings = _Settings()