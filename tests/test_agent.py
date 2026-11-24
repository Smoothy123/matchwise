import json
import re

import pytest
from fastapi.testclient import TestClient

from matchwise.agent import FALLBACK_REPLY, MAX_STEPS, NOT_SAVED_NOTE, TOOLS, run_turn, tool_definitions
from matchwise.api import app, get_embedder, get_llm
from matchwise.llm import AgentStep, Completion, LLMClient, LLMUnavailable, ToolCall
from matchwise.preferences import load_profile
from conftest import BACKEND_NEVER_SALES, same_vector, save_profile


class ScriptedAgent:
    """Fake LLM for the agent. Each step is either reply text or a list of (tool, arguments).
    `structured` holds replies for the JSON calls tools make (extraction, reasons); an exception
    there is raised instead, like a busy API."""

    model = "scripted-agent"

    def __init__(self, steps, structured=()):
        self.steps = list(steps)
        self.structured = list(structured)
        self.chat_calls: list[list[dict]] = []

    def complete_with_tools(self, messages, tools):
        self.chat_calls.append([dict(m) for m in messages])
        step = self.steps.pop(0)
        if isinstance(step, str):
            return AgentStep(step, [], {"role": "assistant", "content": step}, 50, 10)
        calls, raw = [], []
        for i, (name, args) in enumerate(step):
            call_id = f"call_{len(self.chat_calls)}_{i}"
            arguments = args if isinstance(args, str) else json.dumps(args)
            calls.append(ToolCall(call_id, name, arguments))
            raw.append({"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments},
                        "extra_content": {"google": {"thought_signature": f"sig-{call_id}"}}})
        return AgentStep(None, calls, {"role": "assistant", "content": "", "tool_calls": raw}, 50, 10)

    def complete(self, messages):
        if messages[0]["content"].startswith("You check job postings"):  # the LLM limit check: nothing breaks
            ids = [int(i) for i in re.findall(r"=== job (\d+) ===", messages[1]["content"])]
            return Completion(json.dumps({"verdicts": [{"job_id": i, "breaks_limit": False} for i in ids]}), 100, 20)
        reply = self.structured.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(reply, 100, 20)


def agent_llm(steps, structured=()) -> LLMClient:
    return LLMClient(ScriptedAgent(steps, structured))


def tool_results(llm: LLMClient, step: int) -> list[dict]:
    """The tool results the model was shown at the start of agent step `step`."""
    return [json.loads(m["content"]) for m in llm.transport.chat_calls[step] if m["role"] == "tool"]


EXTRACT = json.dumps({"operations": [
    {"op": "add", "field": "wants.roles", "value": "backend engineer", "evidence": "backend work"},
    {"op": "add", "field": "wants.skills", "value": "python", "evidence": "python"},
    {"op": "add", "field": "dealbreakers.exclude_functions", "value": "Sales", "evidence": "never sales"},
    {"op": "add", "field": "dealbreakers.exclude_title_words", "value": "sales", "evidence": "never sales"},
], "notes": []})


def test_tools_are_described_with_their_argument_schemas():
    definitions = {d["function"]["name"]: d["function"] for d in tool_definitions()}
    assert set(definitions) == set(TOOLS) == {"update_preferences", "get_matches", "search_jobs", "explain_match"}
    assert definitions["explain_match"]["parameters"]["required"] == ["job_id"]


def test_a_turn_saves_preferences_then_matches_then_replies(catalog):
    llm = agent_llm(
        steps=[[("update_preferences", {"message": "Backend work in Python, never sales"})],
               [("get_matches", {"limit": 3})],
               "Here are three matches."],
        structured=[EXTRACT],
    )
    out = run_turn(catalog, llm, same_vector, "ana", "I want backend work in Python, never sales. What fits?")
    assert out["reply"] == "Here are three matches."
    assert [(c["name"], c["ok"]) for c in out["tool_calls"]] == [("update_preferences", True), ("get_matches", True)]

    assert load_profile(catalog, "ana")[0].dealbreakers.exclude_functions == ["Sales"]   # long-term memory
    matches = tool_results(llm, 2)[-1]["result"]
    titles = [m["title"] for m in matches]
    assert titles[0] == "Backend Engineer" and "Sales Development Rep" not in titles      # filters applied

    roles = [r["role"] for r in catalog.execute("SELECT role FROM chat_messages ORDER BY id")]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]


def test_tool_call_messages_go_back_unchanged(catalog):
    """Gemini rejects the next request unless each tool call comes back with its thought signature."""
    llm = agent_llm(steps=[[("search_jobs", {"query": "backend"})], "Found some."])
    run_turn(catalog, llm, same_vector, "ana", "Any backend jobs?")
    sent_back = next(m for m in llm.transport.chat_calls[1] if m.get("tool_calls"))
    assert sent_back["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig-call_1_0"}}


def test_the_next_turn_remembers_the_conversation_and_preferences(catalog):
    run_turn(catalog, agent_llm([[("update_preferences", {"message": "backend, never sales"})], "Saved."],
                                [EXTRACT]), same_vector, "ana", "I want backend work, never sales.")
    llm = agent_llm(["Still backend."])
    run_turn(catalog, llm, same_vector, "ana", "What did I ask for?")
    sent = llm.transport.chat_calls[0]
    assert '"backend engineer"' in sent[0]["content"]                       # stored preferences in the prompt
    assert [(m["role"], m["content"]) for m in sent[1:]] == [             # earlier turn, without tool traffic
        ("user", "I want backend work, never sales."), ("assistant", "Saved."), ("user", "What did I ask for?")]


@pytest.mark.parametrize("bad_call, expected_error", [
    (("get_matches", {"limit": 99}), "Invalid arguments for get_matches"),
    (("get_matches", "not json"), "Invalid arguments for get_matches"),
    (("delete_everything", {}), "Unknown tool 'delete_everything'"),
    (("get_matches", {}), "No preferences stored yet"),
    (("explain_match", {"job_id": 1}), "No preferences stored yet"),
])
def test_tool_problems_go_back_to_the_model_as_errors(catalog, bad_call, expected_error):
    llm = agent_llm(steps=[[bad_call], "Sorry about that."])
    out = run_turn(catalog, llm, same_vector, "ana", "hi")
    assert out["reply"] == "Sorry about that." and out["tool_calls"][0]["ok"] is False
    assert expected_error in tool_results(llm, 1)[0]["error"]


BUSY = LLMUnavailable("InternalServerError: Error code: 503")


def test_a_failed_save_is_never_reported_as_saved(catalog):
    llm = agent_llm(steps=[[("update_preferences", {"message": "Data analyst in Chicago"})],
                           "Got it, I've noted that!"],                   # what the model really said
                    structured=[BUSY])
    out = run_turn(catalog, llm, same_vector, "ana", "Data analyst in Chicago, please.")

    assert out["tool_calls"][0]["ok"] is False
    assert "NOT SAVED" in tool_results(llm, 1)[0]["error"]               # the model is told plainly
    assert out["reply"] == f"Got it, I've noted that!\n\n{NOT_SAVED_NOTE}"  # and the reply says it anyway
    assert load_profile(catalog, "ana") is None

    # The stored reply carries the note too, so the next turn's memory isn't the false claim.
    llm = agent_llm(["Let's try again."])
    run_turn(catalog, llm, same_vector, "ana", "Did you save it?")
    remembered = [m["content"] for m in llm.transport.chat_calls[0] if m["role"] == "assistant"]
    assert remembered == [f"Got it, I've noted that!\n\n{NOT_SAVED_NOTE}"]


def test_a_save_that_works_on_a_second_try_needs_no_note(catalog):
    llm = agent_llm(steps=[[("update_preferences", {"message": "backend, never sales"})],
                           [("update_preferences", {"message": "backend, never sales"})],
                           "Saved."],
                    structured=[BUSY, EXTRACT])
    out = run_turn(catalog, llm, same_vector, "ana", "Backend work, never sales.")
    assert [c["ok"] for c in out["tool_calls"]] == [False, True]
    assert out["reply"] == "Saved."


def test_explain_match(catalog):
    save_profile(catalog, "ana", BACKEND_NEVER_SALES)
    job_id = catalog.execute("SELECT id FROM jobs WHERE source_id = 'be'").fetchone()["id"]
    reason = json.dumps({"reasons": [{"job_id": job_id, "reason": "A backend role in Austin using Python.",
                                      "matched_preferences": ["W1"], "caveats": ["Salary not stated"]}]})
    llm = agent_llm(steps=[[("explain_match", {"job_id": job_id})], [("explain_match", {"job_id": 999999})],
                           "It fits."], structured=[reason])
    run_turn(catalog, llm, same_vector, "ana", "Why the first one? And job 999999?")
    explained, missing = tool_results(llm, 2)
    assert explained["result"]["matched_preferences"] == ["role: backend engineer"]
    assert missing["error"] == "No open job with id 999999."


def test_a_turn_that_never_finishes_stops(catalog):
    llm = agent_llm(steps=[[("search_jobs", {"query": "jobs"})]] * MAX_STEPS)
    out = run_turn(catalog, llm, same_vector, "ana", "loop forever")
    assert out["reply"] == FALLBACK_REPLY and len(out["tool_calls"]) == MAX_STEPS


# ---------- the endpoints ----------

@pytest.fixture
def client(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    app.dependency_overrides[get_embedder] = lambda: same_vector
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_chat_endpoints(catalog, client):
    llm = agent_llm([[("update_preferences", {"message": "backend, never sales"})], "Saved."], [EXTRACT])
    app.dependency_overrides[get_llm] = lambda: llm
    response = client.post("/profiles/ana/chat", json={"message": "I want backend work, never sales."})
    assert response.status_code == 200
    assert response.json()["reply"] == "Saved."
    assert response.json()["tool_calls"][0]["name"] == "update_preferences"

    history = client.get("/profiles/ana/chat").json()
    assert [h["role"] for h in history] == ["user", "assistant", "tool", "assistant"]
    # The tool request is typed and drops Gemini's thought signature; its result names the call it answers.
    assert history[1]["tool_calls"] == [{"id": "call_1_0", "function": {
        "name": "update_preferences", "arguments": json.dumps({"message": "backend, never sales"})}}]
    assert history[2]["tool_call_id"] == "call_1_0" and history[0]["tool_call_id"] is None
    assert client.delete("/profiles/ana/chat").json() == {"deleted_messages": 4}
    assert client.get("/profiles/ana/chat").json() == []
    assert client.get("/profiles/ana").status_code == 200   # preferences outlive the chat


def test_chat_needs_an_llm(catalog, client):
    assert client.post("/profiles/ana/chat", json={"message": "hi"}).status_code == 503
