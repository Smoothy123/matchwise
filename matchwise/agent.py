"""A chat agent that helps one person find jobs, using four tools.

Each turn:
  1. Load memory. Long-term: the person's stored preferences (Phase 3), put in the
     system prompt. Short-term: the last HISTORY_MESSAGES user/assistant messages of
     this conversation.
  2. Loop: send the conversation and the tool definitions to the LLM. If it asks for
     tools, run them (arguments validated with Pydantic) and send the results back.
     Stop when it answers in plain text, or after MAX_STEPS rounds of tool calls.
  3. Save the user's message, every tool call and result, and the reply.

The loop is written by hand rather than with an agent framework: it's about 60
lines, and every step can be read, logged and tested.

Safety: tools act only on this conversation's profile. The model never chooses a
profile id, so it can't read or change anyone else's data. A tool that fails returns
an error to the model instead of crashing the turn, so the model can tell the person.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ValidationError

from matchwise import preferences, ranking, reasons
from matchwise.embeddings import Embedder
from matchwise.llm import LLMClient, LLMError, ToolCall, describe_errors
from matchwise.search import search_jobs

log = logging.getLogger(__name__)

MAX_STEPS = 5           # tool rounds per turn before giving up
HISTORY_MESSAGES = 20   # earlier user/assistant messages sent with each turn
FALLBACK_REPLY = "Sorry, I couldn't finish that. Could you say it another way?"
# Added in code, not left to the model: with the LLM busy (503), saves failed and the model still
# replied "I have them noted!". This makes the reply true whatever the model wrote.
NOT_SAVED_NOTE = ("Note: your preferences were not saved this time, because the update failed. "
                  "Please send them again.")


class ToolError(Exception):
    """A tool can't do what was asked; the message goes back to the model to explain."""


@dataclass
class ToolContext:
    conn: psycopg.Connection
    llm: LLMClient
    embed: Embedder
    profile_id: str


# ---------- tools ----------

class UpdatePreferencesArgs(BaseModel):
    message: str = Field(min_length=1, max_length=2000,
                         description="The person's own words about what they want or rule out")


class SearchJobsArgs(BaseModel):
    query: str = Field(min_length=2, max_length=500, description="What to look for, in plain words")
    limit: int = Field(default=5, ge=1, le=10)


class GetMatchesArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=10)


class ExplainMatchArgs(BaseModel):
    job_id: int = Field(description="The job's id, e.g. 1234 for [#1234]")


def compact_preferences(prefs: preferences.Preferences) -> dict:
    """Only the fields that are set, to keep prompts short."""
    def nonempty(model: BaseModel) -> dict:
        return {k: v for k, v in model.model_dump().items() if v not in ([], None, False)}
    return {"wants": nonempty(prefs.wants), "dealbreakers": nonempty(prefs.dealbreakers)}


def update_preferences(ctx: ToolContext, args: UpdatePreferencesArgs) -> dict:
    try:
        result = preferences.process_message(ctx.conn, ctx.llm, ctx.profile_id, args.message)
    except (LLMError, preferences.ConcurrentUpdate) as error:
        # Spelled out for the model: a bare "Error code: 503" didn't stop it claiming success.
        raise ToolError(
            f"NOT SAVED. Nothing was stored ({type(error).__name__}). Tell them plainly that their "
            "preferences were not saved and ask them to send them again."
        ) from error
    return {
        "changes": [f"{op.op} {op.field} {op.value!r}" for op in result["operations"]] or ["nothing changed"],
        "notes": result["notes"],
        "preferences_now": compact_preferences(result["preferences"]),
    }


def search(ctx: ToolContext, args: SearchJobsArgs) -> list[dict]:
    rows = search_jobs(ctx.conn, ctx.embed([args.query])[0], args.limit)
    return [{"job_id": r["id"], "title": r["title"], "company": r["company"], "location": r["location"],
             "remote": r["remote"], "similarity": round(r["similarity"], 3)} for r in rows]


def get_matches(ctx: ToolContext, args: GetMatchesArgs) -> list[dict]:
    found = preferences.load_profile(ctx.conn, ctx.profile_id)
    if found is None:
        raise ToolError("No preferences stored yet. Ask what they're looking for, then call update_preferences.")
    matches = ranking.match(ctx.conn, found[0], ctx.embed, limit=args.limit, mode=ranking.Mode.checked, llm=ctx.llm)
    return [{"job_id": m["job_id"], "title": m["title"], "company": m["company"], "location": m["location"],
             "remote": m["remote"], "score": m["score"], "matched_skills": m["matched_skills"],
             "limit_check": m.get("limit_check")} for m in matches]


JOB_FOR_EXPLAIN_SQL = """
SELECT id AS job_id, title, company, location, remote, seniority, employment_type,
       salary_min, salary_max, skills
FROM jobs WHERE id = %s AND is_active
"""


def explain_match(ctx: ToolContext, args: ExplainMatchArgs) -> dict:
    found = preferences.load_profile(ctx.conn, ctx.profile_id)
    if found is None:
        raise ToolError("No preferences stored yet, so there is nothing to compare this job with.")
    job = ctx.conn.execute(JOB_FOR_EXPLAIN_SQL, (args.job_id,)).fetchone()
    if job is None:
        raise ToolError(f"No open job with id {args.job_id}.")
    explanation = reasons.explain_matches(ctx.conn, ctx.llm, found[0], [job])[args.job_id]
    if explanation is None:
        raise ToolError("Couldn't write an explanation right now.")
    return {"job_id": args.job_id, "title": job["title"], "company": job["company"], **explanation.model_dump()}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[ToolContext, Any], Any]


TOOLS = {tool.name: tool for tool in [
    Tool("update_preferences",
         "Save what the person wants or rules out (role, skills, place, level, pay, remote, hard limits). "
         "Pass their own words. Call this whenever they state or change a preference.",
         UpdatePreferencesArgs, update_preferences),
    Tool("get_matches",
         "Their best-fitting open jobs, using their stored preferences: hard limits filtered out and checked, "
         "the rest ranked. Use for 'what fits me?'.",
         GetMatchesArgs, get_matches),
    Tool("search_jobs",
         "Free-text search over open jobs by meaning. Ignores their stored preferences and limits. "
         "Use when they ask about a kind of job directly.",
         SearchJobsArgs, search),
    Tool("explain_match",
         "Why one job fits them or doesn't: a short reason, the preferences it meets, and caveats.",
         ExplainMatchArgs, explain_match),
]}


def tool_definitions() -> list[dict]:
    return [{"type": "function", "function": {
        "name": t.name, "description": t.description, "parameters": t.args.model_json_schema()}}
        for t in TOOLS.values()]


def run_tool(ctx: ToolContext, call: ToolCall) -> dict:
    """Run one tool call. Problems come back as {"error": ...} for the model to handle."""
    tool = TOOLS.get(call.name)
    if tool is None:
        return {"error": f"Unknown tool {call.name!r}. Available: {', '.join(TOOLS)}."}
    try:
        args = tool.args.model_validate_json(call.arguments or "{}")
    except ValidationError as error:
        return {"error": f"Invalid arguments for {call.name}: {describe_errors(error)}"}
    try:
        return {"result": tool.run(ctx, args)}
    except (ToolError, ranking.NoWants, preferences.ConcurrentUpdate, LLMError) as error:
        log.warning("tool %s failed: %s", call.name, error)
        return {"error": str(error)}


# ---------- the loop ----------

SYSTEM_PROMPT = """You are Matchwise, a job-search assistant for one person.

Use the tools:
- When they say what they want or rule out, call update_preferences with their words first.
- For "what fits me?", call get_matches. For a direct question about a kind of job, search_jobs.
- When they ask about a particular job, call explain_match with its id.

Rules:
- Only mention jobs a tool returned in this conversation. Never invent jobs, companies or details.
- Refer to jobs as "Title at Company [#id]", so they can ask about them later.
- Keep replies short: a few sentences, at most 5 jobs.
- If a tool returns an error, say plainly what went wrong.
- If update_preferences returns an error, nothing was saved. Say so, and never say you saved,
  noted or remembered anything from that message.
- If get_matches marks jobs with limit_check "skipped", say their hard limits couldn't be fully
  checked right now.

What you know about them (their stored preferences):
{preferences}"""


def system_prompt(conn: psycopg.Connection, profile_id: str) -> str:
    found = preferences.load_profile(conn, profile_id)
    known = json.dumps(compact_preferences(found[0])) if found else "nothing yet"
    return SYSTEM_PROMPT.format(preferences=known)


def load_history(conn: psycopg.Connection, profile_id: str) -> list[dict]:
    """The last HISTORY_MESSAGES user messages and final replies (not the tool traffic)."""
    rows = conn.execute(
        """SELECT role, content FROM chat_messages
           WHERE profile_id = %s AND role IN ('user', 'assistant') AND tool_calls IS NULL
           ORDER BY id DESC LIMIT %s""",
        (profile_id, HISTORY_MESSAGES),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def run_turn(conn: psycopg.Connection, llm: LLMClient, embed: Embedder, profile_id: str, message: str) -> dict:
    ctx = ToolContext(conn, llm, embed, profile_id)
    messages = [{"role": "system", "content": system_prompt(conn, profile_id)},
                *load_history(conn, profile_id),
                {"role": "user", "content": message}]
    trace: list[dict] = []        # what to save: tool requests and results
    calls_made: list[dict] = []   # what to return: a short summary of each tool call
    reply = FALLBACK_REPLY
    for _ in range(MAX_STEPS):
        step = llm.chat(messages, tool_definitions())
        if not step.tool_calls:
            reply = step.text or FALLBACK_REPLY
            break
        messages.append(step.message)  # sent back unchanged (Gemini needs its thought signatures)
        trace.append({"role": "assistant", "content": step.text, "tool_calls": step.message["tool_calls"]})
        for call in step.tool_calls:
            outcome = run_tool(ctx, call)
            content = json.dumps(outcome, default=str)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
            trace.append({"role": "tool", "content": content, "tool_call_id": call.id})
            calls_made.append({"name": call.name, "arguments": call.arguments, "ok": "error" not in outcome})
    else:
        log.warning("agent profile=%s stopped after %d tool rounds", profile_id, MAX_STEPS)

    saves = [call for call in calls_made if call["name"] == "update_preferences"]
    if saves and not any(call["ok"] for call in saves):
        # Before saving the turn, so the stored history (the agent's memory for later turns)
        # and the API response both say it too.
        reply = f"{reply}\n\n{NOT_SAVED_NOTE}"
        log.warning("agent profile=%s: preferences not saved this turn", profile_id)

    save_turn(conn, profile_id, message, trace, reply)
    return {"reply": reply, "tool_calls": calls_made}


def save_turn(conn: psycopg.Connection, profile_id: str, message: str, trace: list[dict], reply: str) -> None:
    with conn.transaction():
        turn = conn.execute(
            "SELECT coalesce(max(turn), 0) + 1 AS n FROM chat_messages WHERE profile_id = %s", (profile_id,)
        ).fetchone()["n"]
        rows = [{"role": "user", "content": message}, *trace, {"role": "assistant", "content": reply}]
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chat_messages (profile_id, turn, role, content, tool_calls, tool_call_id)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [(profile_id, turn, r["role"], r.get("content"),
                  Jsonb(r["tool_calls"]) if r.get("tool_calls") else None, r.get("tool_call_id")) for r in rows],
            )


def chat_history(conn: psycopg.Connection, profile_id: str) -> list[dict]:
    return conn.execute(
        """SELECT turn, role, content, tool_calls, tool_call_id, created_at FROM chat_messages
           WHERE profile_id = %s ORDER BY id""",
        (profile_id,),
    ).fetchall()


def reset_chat(conn: psycopg.Connection, profile_id: str) -> int:
    """Forget the conversation. Stored preferences stay: they're the long-term memory."""
    return conn.execute("DELETE FROM chat_messages WHERE profile_id = %s", (profile_id,)).rowcount
