"""Settings, read once from environment variables (see .env.example)."""

import logging
import os
from dataclasses import dataclass

GEMINI_OPENAI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"


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


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # The OpenAI SDK's HTTP client logs every request at INFO; our llm module logs what matters.
    logging.getLogger("httpx").setLevel(logging.WARNING)
