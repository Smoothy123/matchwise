"""Settings, read once from environment variables (see .env.example)."""

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

GEMINI_OPENAI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"

# The web frontend's dev server (npm run dev) and production preview (npm run preview).
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://localhost:4173"


@dataclass(frozen=True)
class Settings:
    database_url: str
    log_level: str
    llm_base_url: str
    llm_api_key: str | None
    llm_model: str | None
    llm_requests_per_minute: float
    llm_max_retries: int = 2


def get_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return Settings(
        database_url=database_url,
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        llm_base_url=os.environ.get("LLM_BASE_URL") or GEMINI_OPENAI_ENDPOINT,
        llm_api_key=os.environ.get("LLM_API_KEY") or None,
        llm_model=os.environ.get("LLM_MODEL") or None,
        llm_requests_per_minute=float(os.environ.get("LLM_REQUESTS_PER_MINUTE") or 10),
        # Interactive requests should fail fast; long eval runs can afford to wait out a busy API.
        llm_max_retries=int(os.environ.get("LLM_MAX_RETRIES") or 2),
    )


def cors_origins(value: str | None = None) -> list[str]:
    """Origins whose pages may call the API from a browser, from CORS_ORIGINS (comma-separated).

    Unset means the local dev origins; set but empty means none. A mistyped origin would
    fail silently in the browser (it just never matches), so each one is checked here and a
    bad one stops the app at startup instead.
    """
    raw = os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS) if value is None else value
    origins = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")  # browsers never send a trailing slash
        if not origin:
            continue
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query:
            raise ValueError(f"CORS_ORIGINS: {origin!r} is not an origin like https://app.example.com")
        origins.append(origin)
    return origins


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # The OpenAI SDK's HTTP client logs every request at INFO; our llm module logs what matters.
    logging.getLogger("httpx").setLevel(logging.WARNING)
