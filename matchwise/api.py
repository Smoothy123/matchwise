"""HTTP API. Routes stay thin: they validate input and call the modules that do the work."""

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from matchwise import agent, db, embeddings, llm, preferences, ranking, reasons
from matchwise.config import cors_origins, get_settings, setup_logging
from matchwise.preferences import Operation, Preferences
from matchwise.ranking import Mode
from matchwise.search import search_jobs

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    db.migrate(settings.database_url)
    app.state.pool = db.create_pool(settings.database_url)
    try:
        app.state.llm = llm.client_from_settings(settings)
    except llm.LLMNotConfigured as error:
        app.state.llm = None
        log.warning("LLM features are off: %s", error)
    yield
    app.state.pool.close()


app = FastAPI(title="Matchwise", lifespan=lifespan)

# Lets the web frontend (a different origin) call the API from the browser. Middleware must be
# added before the app starts, so the origins are read here, not in lifespan. No cookies or
# auth headers are used, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    max_age=600,  # browsers may reuse a preflight answer for 10 minutes
)


# ---------- dependencies ----------

def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    """One pooled connection per request, returned to the pool afterwards."""
    with request.app.state.pool.connection() as conn:
        yield conn


def get_embedder() -> embeddings.Embedder:
    """The real model; tests override this dependency with a fast fake."""
    return embeddings.embed_texts


def get_llm(request: Request) -> llm.LLMClient:
    if request.app.state.llm is None:
        raise HTTPException(503, "The LLM is not configured: set LLM_API_KEY and LLM_MODEL in .env.")
    return request.app.state.llm


def get_optional_llm(request: Request) -> llm.LLMClient | None:
    """For features that still work without an LLM (matches without reasons)."""
    return request.app.state.llm


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
Embed = Annotated[embeddings.Embedder, Depends(get_embedder)]
LLM = Annotated[llm.LLMClient, Depends(get_llm)]
OptionalLLM = Annotated[llm.LLMClient | None, Depends(get_optional_llm)]
ProfileId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


# ---------- errors ----------

@app.exception_handler(llm.LLMOutputError)
def llm_output_error(request: Request, error: llm.LLMOutputError) -> JSONResponse:
    log.error("%s", error)
    return JSONResponse(status_code=502, content={
        "detail": "The language model kept returning invalid output, so nothing was changed. Please try again."})


@app.exception_handler(llm.LLMUnavailable)
def llm_unavailable(request: Request, error: llm.LLMUnavailable) -> JSONResponse:
    log.error("%s", error)
    return JSONResponse(status_code=503, content={
        "detail": "The language model is unavailable right now, so nothing was changed. Please try again."})


@app.exception_handler(preferences.ConcurrentUpdate)
def concurrent_update(request: Request, error: preferences.ConcurrentUpdate) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(ranking.LimitCheckUnavailable)
def limit_check_unavailable(request: Request, error: ranking.LimitCheckUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(ranking.NoWants)
def no_wants(request: Request, error: ranking.NoWants) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


# ---------- models ----------

class ErrorOut(BaseModel):
    """The body of every error except request validation (422), whose `detail` is a list."""
    detail: str


ERROR_DESCRIPTIONS = {
    404: "No such profile: a profile exists once it has been sent a message",
    409: "The profile changed while this message was processed; send it again",
    502: "The language model kept returning invalid output; nothing was changed",
    503: "The language model is not configured or is unavailable right now",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Declare a route's error responses, so the OpenAPI schema (and the types the frontend
    generates from it) lists every status the route can return, not just 200 and 422."""
    return {code: {"model": ErrorOut, "description": ERROR_DESCRIPTIONS[code]} for code in codes}


class HealthOut(BaseModel):
    status: Literal["ok"]
    jobs: int
    active_jobs: int
    embedded_jobs: int
    llm_configured: bool


class SearchResult(BaseModel):
    id: int
    title: str
    company: str | None
    location: str | None
    remote: bool
    seniority: str
    skills: list[str]
    snippet: str
    similarity: float


class MessageIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class MessageOut(BaseModel):
    profile_id: str
    version: int
    preferences: Preferences
    operations: list[Operation]
    notes: list[str]


class ProfileOut(BaseModel):
    profile_id: str
    version: int
    preferences: Preferences


class FeatureScore(BaseModel):
    value: float         # the feature itself, 0..1
    weight: float        # its share of the score, after leaving out features that don't apply
    contribution: float  # value x weight; the contributions add up to the score


class MatchOut(BaseModel):
    job_id: int
    title: str
    company: str | None
    location: str | None
    remote: bool
    seniority: str
    employment_type: str | None
    salary_min: int | None
    salary_max: int | None
    posted_at: datetime | None
    skills: list[str]
    matched_skills: list[str]
    score: float
    similarity: float
    features: dict[str, FeatureScore]
    explanation: reasons.Explanation | None = None  # None if reasons were off or the LLM failed
    # "passed", "skipped" (LLM unavailable: only the SQL filters applied), "no limits",
    # or None in modes without the LLM limit check. Jobs that break a limit are never returned.
    limit_check: Literal["passed", "skipped", "no limits"] | None = None


class ToolCallOut(BaseModel):
    name: str
    arguments: str
    ok: bool


class ChatOut(BaseModel):
    reply: str
    tool_calls: list[ToolCallOut]


class ToolCallFunction(BaseModel):
    name: str
    arguments: str  # JSON text, exactly as the model wrote it


class StoredToolCall(BaseModel):
    """A tool request as saved. Provider extras (Gemini's thought signatures) aren't returned:
    the agent only needs them within a turn, and they mean nothing to a client."""
    id: str
    function: ToolCallFunction


class ChatMessageOut(BaseModel):
    turn: int
    role: Literal["user", "assistant", "tool"]
    content: str | None   # a tool row's content is the tool's JSON result: {"result": ...} or {"error": ...}
    tool_calls: list[StoredToolCall] | None   # set on assistant rows that ask for tools
    tool_call_id: str | None                  # set on tool rows: which call this result answers
    created_at: datetime


class ChatResetOut(BaseModel):
    deleted_messages: int


class HistoryItem(BaseModel):
    version: int
    content: str
    operations: list[Operation]
    notes: list[str]
    model: str
    prompt_version: str
    created_at: datetime


# ---------- routes ----------

@app.get("/health")
def health(conn: Conn, request: Request) -> HealthOut:
    counts = conn.execute(
        """SELECT count(*) AS jobs,
                  count(*) FILTER (WHERE is_active) AS active_jobs,
                  count(*) FILTER (WHERE is_active AND embedding IS NOT NULL) AS embedded_jobs
           FROM jobs"""
    ).fetchone()
    return HealthOut(status="ok", **counts, llm_configured=request.app.state.llm is not None)


@app.get("/search")
def search(
    conn: Conn,
    embed: Embed,
    q: Annotated[str, Query(min_length=2, max_length=500, description="What you're looking for, in plain words")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SearchResult]:
    query_vector = embed([q])[0]
    return search_jobs(conn, query_vector, limit)


@app.post("/profiles/{profile_id}/messages", responses=errors(409, 502, 503))
def post_message(profile_id: ProfileId, body: MessageIn, conn: Conn, client: LLM) -> MessageOut:
    """Read a plain-language message and update the profile's stored preferences."""
    return preferences.process_message(conn, client, profile_id, body.message)


@app.get("/profiles/{profile_id}", responses=errors(404))
def get_profile(profile_id: ProfileId, conn: Conn) -> ProfileOut:
    found = preferences.load_profile(conn, profile_id)
    if found is None:
        raise HTTPException(404, f"No profile {profile_id!r}. Send it a message first.")
    prefs, version = found
    return ProfileOut(profile_id=profile_id, version=version, preferences=prefs)


@app.get("/profiles/{profile_id}/matches", responses={
    **errors(404, 503),
    422: {"description": "Invalid parameters (a list of problems), or the profile has only dealbreakers "
                         "so there is nothing to search for yet (a message)",
          "content": {"application/json": {"schema": {"anyOf": [
              {"$ref": "#/components/schemas/HTTPValidationError"}, {"$ref": "#/components/schemas/ErrorOut"}]}}}},
})
def get_matches(
    profile_id: ProfileId,
    conn: Conn,
    embed: Embed,
    client: OptionalLLM,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    mode: Annotated[Mode | None, Query(description=(
        "Default: checked (filters + re-ranking + LLM limit check) when the LLM is configured, else full. "
        "vector and vector_filters are for comparison."))] = None,
    explain: Annotated[bool, Query(description="Add a plain-language reason to each match (cached)")] = True,
) -> list[MatchOut]:
    """The best-fitting active jobs for this profile, each with its score breakdown and a reason."""
    found = preferences.load_profile(conn, profile_id)
    if found is None:
        raise HTTPException(404, f"No profile {profile_id!r}. Send it a message first.")
    prefs = found[0]
    # The LLM limit check halved limit violations in the evals (13% -> 6% of the top 10), so it's
    # the default whenever an LLM is available.
    mode = mode or (Mode.checked if client is not None else Mode.full)
    matches = ranking.match(conn, prefs, embed, mode=mode, limit=limit, llm=client)
    if explain and client is not None:
        explanations = reasons.explain_matches(conn, client, prefs, matches)
        for match in matches:
            match["explanation"] = explanations.get(match["job_id"])
    return matches


@app.post("/profiles/{profile_id}/chat", responses=errors(503))
def chat(profile_id: ProfileId, body: MessageIn, conn: Conn, embed: Embed, client: LLM) -> ChatOut:
    """Talk to the agent. It remembers this conversation and the profile's stored preferences."""
    return agent.run_turn(conn, client, embed, profile_id, body.message)


@app.get("/profiles/{profile_id}/chat")
def get_chat(profile_id: ProfileId, conn: Conn) -> list[ChatMessageOut]:
    """The whole conversation, including every tool call and result."""
    return agent.chat_history(conn, profile_id)


@app.delete("/profiles/{profile_id}/chat")
def delete_chat(profile_id: ProfileId, conn: Conn) -> ChatResetOut:
    """Forget the conversation; stored preferences stay."""
    return ChatResetOut(deleted_messages=agent.reset_chat(conn, profile_id))


@app.get("/profiles/{profile_id}/messages", responses=errors(404))
def get_messages(profile_id: ProfileId, conn: Conn) -> list[HistoryItem]:
    if preferences.load_profile(conn, profile_id) is None:
        raise HTTPException(404, f"No profile {profile_id!r}.")
    return preferences.list_messages(conn, profile_id)
