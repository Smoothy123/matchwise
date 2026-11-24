"""Smoke tests against the real LLM. They use your quota, so they only run with: pytest -m live"""

import pytest

from matchwise.config import get_settings
from matchwise.llm import LLMNotConfigured, client_from_settings
from matchwise.preferences import process_message

pytestmark = pytest.mark.live


@pytest.fixture
def live_llm():
    try:
        return client_from_settings(get_settings())
    except LLMNotConfigured as error:
        pytest.skip(str(error))


def lower(values) -> list[str]:
    return [v.lower() for v in values]


def test_extracts_and_then_updates_preferences(conn, live_llm):
    first = process_message(conn, live_llm, "live", "I want backend work in Bengaluru, never sales, no night shifts")
    prefs = first["preferences"]
    print("\nafter message 1:", prefs.model_dump_json(indent=1), "\nnotes:", first["notes"])
    assert any("backend" in r for r in lower(prefs.wants.roles))
    places = lower(prefs.wants.locations + prefs.dealbreakers.only_locations)
    assert any("bengaluru" in p or "bangalore" in p for p in places)
    assert "Sales" in prefs.dealbreakers.exclude_functions or "sales" in lower(prefs.dealbreakers.exclude_title_words)
    assert any("night" in p for p in lower(prefs.dealbreakers.exclude_description_phrases))

    second = process_message(conn, live_llm, "live", "Actually make that Hyderabad instead, and I'm open to sales roles now.")
    prefs = second["preferences"]
    print("\nafter message 2:", prefs.model_dump_json(indent=1), "\nnotes:", second["notes"])
    places = lower(prefs.wants.locations + prefs.dealbreakers.only_locations)
    assert any("hyderabad" in p for p in places)
    assert not any("bengaluru" in p or "bangalore" in p for p in places)
    assert "Sales" not in prefs.dealbreakers.exclude_functions
    assert "sales" not in lower(prefs.dealbreakers.exclude_title_words)
    assert any("night" in p for p in lower(prefs.dealbreakers.exclude_description_phrases))  # untouched
    print("usage:", live_llm.usage)


def test_agent_round_trip_with_tools(conn, live_llm):
    """The real model calls a tool, gets the result back, and answers (Gemini thought signatures included)."""
    from conftest import fake_embed
    from matchwise.agent import run_turn

    out = run_turn(conn, live_llm, fake_embed, "live-agent",
                   "I'm a backend engineer and I want remote work. Never sales jobs.")
    print("\nreply:", out["reply"], "\ntools:", out["tool_calls"])
    assert "update_preferences" in [c["name"] for c in out["tool_calls"]]
    prefs = __import__("matchwise.preferences", fromlist=["load_profile"]).load_profile(conn, "live-agent")[0]
    assert "Sales" in prefs.dealbreakers.exclude_functions or "sales" in lower(prefs.dealbreakers.exclude_title_words)
    assert out["reply"].strip()


@pytest.mark.parametrize("profile_id, message, own_function, title_word", [
    ("acct", "CPA, six years in public accounting, want a senior accountant role. No audit roles.",
     "Accounting/Auditing", "audit"),
    ("teach", "Certified elementary school teacher looking for teaching jobs. Not interested in substitute teaching.",
     "Education", "substitute"),
])
def test_ruling_out_part_of_your_own_field_keeps_the_field(conn, live_llm, profile_id, message, own_function,
                                                           title_word):
    """Regression test for prompt v1, which excluded the person's own job function here."""
    prefs = process_message(conn, live_llm, profile_id, message)["preferences"]
    assert own_function not in prefs.dealbreakers.exclude_functions
    assert title_word in lower(prefs.dealbreakers.exclude_title_words + prefs.dealbreakers.exclude_description_phrases)
