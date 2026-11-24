import json
from typing import get_args

import pytest
from pydantic import ValidationError

from conftest import scripted_llm
from matchwise import db
from matchwise.llm import LLMOutputError
from matchwise.preferences import (
    PROMPT_VERSION, SECTIONS, ConcurrentUpdate, FieldPath, Operation, Preferences, apply_operations,
    list_messages, load_profile, process_message,
)


def op(op: str, field: str, value=None) -> Operation:
    return Operation(op=op, field=field, value=value, evidence="test")


def reply(*operations: dict, notes: list[str] | None = None) -> str:
    """A scripted LLM reply in the Extraction format."""
    return json.dumps({"operations": [{"evidence": "e", **o} for o in operations], "notes": notes or []})


# ---------- the schema ----------

def test_field_paths_match_the_models():
    from_models = {f"{section}.{name}" for section, model in SECTIONS.items() for name in model.model_fields}
    assert set(get_args(FieldPath)) == from_models


@pytest.mark.parametrize(
    "bad",
    [
        {"op": "set", "field": "wants.roles", "value": "x"},                         # list field needs add/remove
        {"op": "add", "field": "wants.remote", "value": True},                       # single value needs set/clear
        {"op": "add", "field": "wants.seniority", "value": "senior"},                # not an allowed level
        {"op": "add", "field": "dealbreakers.exclude_functions", "value": "Selling"},  # not a LinkedIn function
        {"op": "set", "field": "dealbreakers.min_salary", "value": -5},              # must be > 0
        {"op": "set", "field": "wants.min_salary", "value": None},                   # set without a value
        {"op": "add", "field": "wants.roles", "value": "  "},                        # empty text
        {"op": "add", "field": "wants.colour", "value": "blue"},                     # no such field
    ],
)
def test_operations_that_do_not_fit_their_field_are_rejected(bad):
    with pytest.raises(ValidationError):
        Operation(evidence="e", **bad)


def test_values_are_coerced_to_the_field_type():
    assert op("set", "wants.min_salary", "120000").value == 120000
    assert op("set", "wants.remote", "true").value is True
    assert op("add", "wants.roles", "  backend engineer ").value == "backend engineer"


# ---------- applying operations ----------

def test_add_remove_set_clear():
    prefs = apply_operations(Preferences(), [
        op("add", "wants.locations", "Austin, TX"),
        op("add", "wants.locations", "austin, tx"),           # same value, different case: not added twice
        op("add", "wants.locations", "Denver, CO"),
        op("remove", "wants.locations", "AUSTIN, TX"),
        op("set", "dealbreakers.only_remote", True),
        op("set", "wants.min_salary", 90000),
        op("clear", "wants.min_salary"),
    ])
    assert prefs.wants.locations == ["Denver, CO"]
    assert prefs.dealbreakers.only_remote is True
    assert prefs.wants.min_salary is None
    assert apply_operations(prefs, [op("clear", "dealbreakers.only_remote")]).dealbreakers.only_remote is False


def test_skills_use_the_postings_vocabulary():
    prefs = apply_operations(Preferences(), [op("add", "wants.skills", "Postgres"), op("add", "wants.skills", "Rust")])
    assert prefs.wants.skills == ["postgresql", "rust"]
    assert apply_operations(prefs, [op("remove", "wants.skills", "PostgreSQL")]).wants.skills == ["rust"]


def test_removing_something_absent_is_a_no_op_and_input_is_unchanged():
    original = Preferences()
    assert apply_operations(original, [op("remove", "wants.roles", "chef")]) == original
    apply_operations(original, [op("add", "wants.roles", "chef")])
    assert original.wants.roles == []


# ---------- messages, memory and storage ----------

FIRST = reply(
    {"op": "add", "field": "wants.roles", "value": "backend engineer"},
    {"op": "add", "field": "wants.locations", "value": "Austin, TX"},
    {"op": "add", "field": "dealbreakers.exclude_functions", "value": "Sales"},
    {"op": "add", "field": "dealbreakers.exclude_title_words", "value": "sales"},
)
SECOND = reply(
    {"op": "remove", "field": "wants.locations", "value": "Austin, TX"},
    {"op": "add", "field": "wants.locations", "value": "Denver, CO"},
    {"op": "remove", "field": "dealbreakers.exclude_functions", "value": "Sales"},
    {"op": "remove", "field": "dealbreakers.exclude_title_words", "value": "sales"},
    notes=["Sales roles can show up again."],
)


def test_later_messages_update_earlier_ones_and_history_is_kept(conn):
    llm = scripted_llm(FIRST, SECOND)
    first = process_message(conn, llm, "ana", "Backend work in Austin, never sales")
    assert first["version"] == 1
    assert first["preferences"].dealbreakers.exclude_functions == ["Sales"]

    second = process_message(conn, llm, "ana", "Actually Denver, and I'm fine with sales now")
    prefs = second["preferences"]
    assert second["version"] == 2 and second["notes"] == ["Sales roles can show up again."]
    assert prefs.wants.roles == ["backend engineer"]          # untouched by the second message
    assert prefs.wants.locations == ["Denver, CO"]
    assert prefs.dealbreakers.exclude_functions == [] and prefs.dealbreakers.exclude_title_words == []

    assert load_profile(conn, "ana") == (prefs, 2)
    history = list_messages(conn, "ana")
    assert [(h["version"], h["content"]) for h in history] == [
        (1, "Backend work in Austin, never sales"), (2, "Actually Denver, and I'm fine with sales now")]
    assert history[0]["operations"][1]["value"] == "Austin, TX"
    assert history[1]["model"] == "scripted" and history[1]["prompt_version"] == PROMPT_VERSION


def test_the_llm_sees_the_current_preferences_and_the_message(conn):
    llm = scripted_llm(FIRST, SECOND)
    process_message(conn, llm, "ana", "first")
    process_message(conn, llm, "ana", "Actually Denver")
    user_prompt = llm.transport.calls[1][1]["content"]
    assert '"Austin, TX"' in user_prompt and user_prompt.endswith("Newest message:\nActually Denver")


def test_snapshot_after_each_message(conn):
    llm = scripted_llm(FIRST, SECOND)
    process_message(conn, llm, "ana", "first")
    process_message(conn, llm, "ana", "second")
    rows = conn.execute("SELECT preferences_after FROM profile_messages ORDER BY version").fetchall()
    assert rows[0]["preferences_after"]["wants"]["locations"] == ["Austin, TX"]
    assert rows[1]["preferences_after"]["wants"]["locations"] == ["Denver, CO"]


def test_nothing_is_stored_when_the_llm_fails(conn):
    llm = scripted_llm("nope", "still nope", "{}{}")
    with pytest.raises(LLMOutputError):
        process_message(conn, llm, "ana", "Backend work")
    assert load_profile(conn, "ana") is None
    assert conn.execute("SELECT count(*) AS n FROM profile_messages").fetchone()["n"] == 0


def test_a_concurrent_update_is_detected_not_overwritten(conn, db_url):
    process_message(conn, scripted_llm(FIRST), "ana", "first")
    with db.connect(db_url) as other:
        # Another request saves a message while our LLM call is still running.
        def someone_else_saves():
            other.execute("UPDATE profiles SET version = version + 1 WHERE id = 'ana'")

        with pytest.raises(ConcurrentUpdate):
            process_message(conn, scripted_llm(SECOND, on_call=someone_else_saves), "ana", "second")
    assert conn.execute("SELECT count(*) AS n FROM profile_messages").fetchone()["n"] == 1
    assert load_profile(conn, "ana")[0].wants.locations == ["Austin, TX"]  # their save wasn't overwritten


def test_an_invalid_operation_is_fixed_on_retry(conn):
    bad = reply({"op": "add", "field": "wants.seniority", "value": "senior"})
    good = reply({"op": "add", "field": "wants.seniority", "value": "mid_senior"})
    llm = scripted_llm(bad, good)
    result = process_message(conn, llm, "ana", "I'm fairly senior")
    assert result["preferences"].wants.seniority == ["mid_senior"]
    feedback = llm.transport.calls[1][-1]["content"]
    assert "wants.seniority: Input should be 'intern', 'entry'" in feedback  # names the field to fix
