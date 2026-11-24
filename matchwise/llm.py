"""The one place the app talks to an LLM.

Works with any OpenAI-compatible chat API: Gemini (through Google's
OpenAI-compatible endpoint) or OpenAI itself. Switching provider means changing
LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env.

structured() asks for JSON and validates it against a Pydantic model *here*.
We don't rely on the provider to enforce the schema (support differs between
providers); this validation is what the rest of the app depends on. If a reply
doesn't validate, the error goes back to the model with a request to fix it,
up to MAX_ATTEMPTS times, and then LLMOutputError is raised.

    python -m matchwise.llm --list-models   # models your key can use
    python -m matchwise.llm --ping          # one tiny structured call
"""

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 3


class LLMError(Exception):
    """Base class, so callers can catch every LLM failure in one place."""


class LLMNotConfigured(LLMError):
    pass


class LLMUnavailable(LLMError):
    """The API could not be reached or refused the call (after the SDK's own retries)."""


class LLMOutputError(LLMError):
    """The model kept replying with output that doesn't fit the schema."""


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, exactly as the model wrote it


@dataclass(frozen=True)
class AgentStep:
    """One reply in a tool-using conversation: either text, or a request to run tools."""
    text: str | None
    tool_calls: list[ToolCall]
    message: dict  # the assistant message as returned; send it back unchanged (see complete_with_tools)
    input_tokens: int
    output_tokens: int


class ChatTransport(Protocol):
    """Sends a list of chat messages and returns the reply. Tests use a scripted fake."""

    model: str

    def complete(self, messages: list[dict[str, str]]) -> Completion: ...

    def complete_with_tools(self, messages: list[dict], tools: list[dict]) -> AgentStep: ...


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    invalid_replies: int = 0


class RateLimiter:
    """Spaces calls at least 60 / requests_per_minute seconds apart (free tiers count per minute)."""

    def __init__(self, requests_per_minute: float, clock=time.monotonic, sleep=time.sleep):
        self.interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._next_allowed = 0.0
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._next_allowed)
            if start > now:
                self._sleep(start - now)
            self._next_allowed = start + self.interval


class OpenAICompatible:
    """Transport for any OpenAI-compatible chat endpoint (Gemini, OpenAI, ...)."""

    def __init__(self, base_url: str, api_key: str, model: str, requests_per_minute: float, max_retries: int = 2):
        from openai import OpenAI

        self.model = model
        # The SDK retries rate-limit (429) and server errors (503 "high demand") itself, with backoff.
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=60, max_retries=max_retries)
        self._limiter = RateLimiter(requests_per_minute)

    def complete(self, messages: list[dict[str, str]]) -> Completion:
        import openai

        self._limiter.wait()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except openai.APIError as error:
            raise LLMUnavailable(f"{type(error).__name__}: {error}") from error
        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def complete_with_tools(self, messages: list[dict], tools: list[dict]) -> AgentStep:
        import openai

        self._limiter.wait()
        try:
            response = self._client.chat.completions.create(
                model=self.model, messages=messages, tools=tools, tool_choice="auto", temperature=0)
        except openai.APIError as error:
            raise LLMUnavailable(f"{type(error).__name__}: {error}") from error
        # Keep the whole message as returned. Gemini 3 attaches a "thought signature" to each
        # tool call (extra_content.google.thought_signature) and rejects the next request (400)
        # unless the tool call comes back unchanged; rebuilding it from parsed fields loses it.
        message = response.choices[0].message.model_dump(exclude_none=True)
        message["content"] = message.get("content") or ""
        calls = [ToolCall(c["id"], c["function"]["name"], c["function"].get("arguments") or "{}")
                 for c in message.get("tool_calls", [])]
        usage = response.usage
        return AgentStep(
            text=message["content"] or None,
            tool_calls=calls,
            message=message,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self._client.models.list())


class LLMClient:
    def __init__(self, transport: ChatTransport):
        self.transport = transport
        self.usage = Usage()

    @property
    def model(self) -> str:
        return self.transport.model

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        purpose: str,
        check: Callable[[T], None] | None = None,
    ) -> T:
        """Ask for JSON matching `schema`; return it validated, or raise LLMOutputError.

        `check` adds rules the schema alone can't express because they depend on this
        request (e.g. "only use these IDs"). It raises ValueError to reject a reply,
        which is then retried exactly like a schema error.
        """
        messages = [
            {"role": "system", "content": f"{system}\n\n{schema_instructions(schema)}"},
            {"role": "user", "content": user},
        ]
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            completion = self.transport.complete(messages)
            latency_ms = (time.perf_counter() - started) * 1000
            self.usage.calls += 1
            self.usage.input_tokens += completion.input_tokens
            self.usage.output_tokens += completion.output_tokens
            try:
                result = schema.model_validate_json(strip_code_fence(completion.text))
                if check:
                    check(result)
                outcome = "ok"
            except ValueError as error:  # pydantic's ValidationError is a ValueError too
                result = None
                last_error = describe_errors(error) if isinstance(error, ValidationError) else str(error)
                outcome = "invalid"
                self.usage.invalid_replies += 1
            log.info(
                "llm purpose=%s model=%s attempt=%d outcome=%s latency_ms=%.0f input_tokens=%d output_tokens=%d",
                purpose, self.model, attempt, outcome, latency_ms, completion.input_tokens, completion.output_tokens,
            )
            if result is not None:
                return result
            messages += [
                {"role": "assistant", "content": completion.text},
                {"role": "user", "content": (
                    f"Your reply did not match the required JSON schema:\n{last_error}\n"
                    "Reply again with the corrected JSON object only."
                )},
            ]
        raise LLMOutputError(f"{purpose}: no valid reply after {MAX_ATTEMPTS} attempts. Last error: {last_error}")

    def chat(self, messages: list[dict], tools: list[dict], purpose: str = "agent") -> AgentStep:
        """One step of a tool-using conversation. Tool arguments are validated by the caller."""
        started = time.perf_counter()
        step = self.transport.complete_with_tools(messages, tools)
        self.usage.calls += 1
        self.usage.input_tokens += step.input_tokens
        self.usage.output_tokens += step.output_tokens
        log.info(
            "llm purpose=%s model=%s tools=%s latency_ms=%.0f input_tokens=%d output_tokens=%d",
            purpose, self.model, [c.name for c in step.tool_calls] or "-", (time.perf_counter() - started) * 1000,
            step.input_tokens, step.output_tokens,
        )
        return step


def schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "Reply with a single JSON object, and nothing else, that matches this JSON Schema:\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


def strip_code_fence(text: str) -> str:
    """Some models wrap JSON in ```json ... ``` even when asked not to."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def describe_errors(error: ValidationError, limit: int = 5) -> str:
    """Short, model-readable list of what was wrong, e.g. 'operations.0.field: Input should be ...'."""
    lines = [f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in error.errors()[:limit]]
    return "\n".join(lines)


def client_from_settings(settings, model: str | None = None) -> LLMClient:
    """The configured client; `model` overrides LLM_MODEL (e.g. a different model for the judge)."""
    model = model or settings.llm_model
    if not settings.llm_api_key or not model:
        raise LLMNotConfigured("Set LLM_API_KEY and LLM_MODEL in .env (see .env.example).")
    transport = OpenAICompatible(settings.llm_base_url, settings.llm_api_key, model,
                                 settings.llm_requests_per_minute, settings.llm_max_retries)
    return LLMClient(transport)


def main() -> None:
    import argparse

    from matchwise.config import get_settings, setup_logging

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--ping", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)
    if args.list_models:
        if not settings.llm_api_key:
            raise SystemExit("Set LLM_API_KEY in .env first.")
        transport = OpenAICompatible(settings.llm_base_url, settings.llm_api_key, settings.llm_model or "-", 60)
        print("\n".join(transport.list_models()))
    if args.ping:
        class Pong(BaseModel):
            answer: str

        client = client_from_settings(settings)
        reply = client.structured(system="You are a health check.", user='Reply with {"answer": "pong"}.',
                                  schema=Pong, purpose="ping")
        print(f"model={client.model} reply={reply.answer!r} usage={client.usage}")


if __name__ == "__main__":
    main()
