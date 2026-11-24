import json
import re

import pytest
from fastapi.testclient import TestClient

from conftest import BACKEND_NEVER_SALES, same_vector, save_profile, scripted_llm
from matchwise.api import app, get_embedder, get_optional_llm
from matchwise.llm import Completion, LLMClient
from matchwise.preferences import Dealbreakers, Preferences, Wants
from matchwise.ranking import match
from matchwise.reasons import BATCH_SIZE, explain_matches, known_gaps, posting_block, preference_items


class ReasonBot:
    """Fake LLM for reasons: answers validly for whichever jobs the prompt contains, and counts calls."""

    model = "reason-bot"

    def __init__(self):
        self.calls: list[list[int]] = []  # the job ids in each call

    def complete(self, messages):
        ids = [int(i) for i in re.findall(r"=== job (\d+) ===", messages[1]["content"])]
        self.calls.append(ids)
        reply = {"reasons": [
            {"job_id": i, "reason": f"Job {i} is a backend role using Python.", "matched_preferences": ["W1", "W2"],
             "caveats": ["Salary not stated"]}
            for i in ids
        ]}
        return Completion(json.dumps(reply), input_tokens=500, output_tokens=80)


def bot_llm() -> tuple[LLMClient, ReasonBot]:
    bot = ReasonBot()
    return LLMClient(bot), bot


# ---------- what the LLM is shown ----------

def test_preferences_are_numbered_for_grounding():
    items = preference_items(Preferences(wants=Wants(
        roles=["backend engineer"], skills=["python"], locations=["Austin, TX"], seniority=["mid_senior"],
        remote=True, min_salary=120000, other=["small team"])))
    assert items == {
        "W1": "role: backend engineer", "W2": "skill: python", "W3": "place: Austin, TX",
        "W4": "level: Mid-senior level", "W5": "prefers remote work", "W6": "would like at least $120,000 a year",
        "W7": "also wants: small team",
    }


JOB = {"job_id": 7, "title": "Backend Engineer", "company": "Acme", "location": "Dallas, OR", "remote": False,
       "seniority": "unknown", "employment_type": "Full-time", "salary_min": None, "salary_max": None,
       "skills": ["python"]}


def test_known_gaps_come_from_the_data():
    prefs = Preferences(
        wants=Wants(skills=["python", "kafka", "basket weaving"], locations=["Austin, TX"], seniority=["mid_senior"],
                    remote=True),
        dealbreakers=Dealbreakers(min_salary=90000),
    )
    assert known_gaps(prefs, JOB) == [
        "Location is Dallas, OR, not one of your places (Austin, TX)",
        "Not listed as remote",
        "Salary not stated (you want at least $90,000)",
        "Seniority level not stated",
        "Doesn't mention: kafka",  # 'basket weaving' isn't a tagged skill, so it can't be checked
    ]
    assert known_gaps(Preferences(wants=Wants(locations=["Austin, TX"])), {**JOB, "remote": True}) == []


def test_posting_block_lists_the_facts_and_gaps():
    block = posting_block(JOB, "Build APIs. Email jobs@acme.com.", ["Not listed as remote"])
    assert block.splitlines()[0] == "=== job 7 ==="
    assert "Salary: not stated" in block and "jobs@acme.com" not in block
    assert block.endswith("Known gaps (must appear in caveats): Not listed as remote")


# ---------- generating and caching ----------

def test_reasons_are_cached_and_repeat_calls_cost_nothing(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, limit=3)
    llm, bot = bot_llm()
    first = explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)
    assert len(bot.calls) == 1 and sorted(bot.calls[0]) == sorted(m["job_id"] for m in matches)
    explanation = first[matches[0]["job_id"]]
    assert explanation.matched_preferences == ["role: backend engineer", "skill: python"]  # IDs expanded

    second = explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)
    assert len(bot.calls) == 1  # no new LLM call
    assert second == first
    assert catalog.execute("SELECT count(*) AS n FROM reasons_cache").fetchone()["n"] == 3


def test_an_edited_posting_or_new_preferences_miss_the_cache(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, limit=3)
    llm, bot = bot_llm()
    explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)

    edited = matches[1]["job_id"]
    catalog.execute("UPDATE jobs SET content_hash = 'edited' WHERE id = %s", (edited,))
    explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)
    assert bot.calls[-1] == [edited]  # only the edited posting is regenerated

    more = BACKEND_NEVER_SALES.model_copy(deep=True)
    more.wants.skills.append("docker")
    explain_matches(catalog, llm, more, matches)
    assert sorted(bot.calls[-1]) == sorted(m["job_id"] for m in matches)  # all regenerated


def test_uncached_jobs_are_batched(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, limit=7)
    llm, bot = bot_llm()
    explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)
    assert [len(ids) for ids in bot.calls] == [BATCH_SIZE, len(matches) - BATCH_SIZE]


def _reply(job_ids, matched=("W1",)):
    return json.dumps({"reasons": [
        {"job_id": i, "reason": "A backend role in Austin.", "matched_preferences": list(matched), "caveats": []}
        for i in job_ids]})


def test_an_unknown_preference_id_is_rejected_and_retried(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, limit=2)
    ids = [m["job_id"] for m in matches]
    llm = scripted_llm(_reply(ids, matched=("W1", "W9")), _reply(ids))
    result = explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)
    assert all(e.matched_preferences == ["role: backend engineer"] for e in result.values())
    feedback = llm.transport.calls[1][-1]["content"]
    assert "matched_preferences may only contain W1, W2, W3, W4, W5" in feedback and "'W9'" in feedback


def test_a_missing_job_is_rejected_and_retried(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, limit=2)
    ids = [m["job_id"] for m in matches]
    llm = scripted_llm(_reply(ids[:1]), _reply(ids))
    assert set(explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)) == set(ids)
    assert "Return exactly one reason for each of the job ids" in llm.transport.calls[1][-1]["content"]


def test_prompt_versions_are_cached_separately_and_v2_asks_for_limit_checks(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, limit=2)
    llm, bot = bot_llm()
    explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches, prompt_version="reasons-v1")
    explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches, prompt_version="reasons-v2")
    assert len(bot.calls) == 2  # v2 doesn't reuse v1's reasons
    assert catalog.execute("SELECT count(DISTINCT prompt_version) AS n FROM reasons_cache").fetchone()["n"] == 2


def test_v2_prompt_tells_the_writer_to_check_limits():
    from matchwise.reasons import PROMPTS, prompt_text
    v1 = prompt_text(BACKEND_NEVER_SALES, {"W1": "role: x"}, [], "reasons-v1")
    v2 = prompt_text(BACKEND_NEVER_SALES, {"W1": "role: x"}, [], "reasons-v2")
    assert "already passes these" in v1 and "the filters can miss things" in v2
    assert "Possible conflict with your limit:" in PROMPTS["reasons-v2"]


def test_an_llm_failure_still_returns_the_matches_without_reasons(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, limit=2)
    llm = scripted_llm("bad", "bad", "bad")
    result = explain_matches(catalog, llm, BACKEND_NEVER_SALES, matches)
    assert result == {m["job_id"]: None for m in matches}
    assert catalog.execute("SELECT count(*) AS n FROM reasons_cache").fetchone()["n"] == 0  # failures aren't cached


# ---------- the endpoint ----------

@pytest.fixture
def api(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    llm, bot = bot_llm()
    app.dependency_overrides[get_embedder] = lambda: same_vector
    app.dependency_overrides[get_optional_llm] = lambda: llm
    with TestClient(app) as client:
        yield client, bot
    app.dependency_overrides.clear()


def test_matches_come_with_reasons(catalog, api):
    client, bot = api
    save_profile(catalog, "ana", BACKEND_NEVER_SALES)
    body = client.get("/profiles/ana/matches", params={"limit": 3, "mode": "full"}).json()
    assert body[0]["explanation"] == {
        "reason": f"Job {body[0]['job_id']} is a backend role using Python.",
        "matched_preferences": ["role: backend engineer", "skill: python"],
        "caveats": ["Salary not stated"],
    }
    client.get("/profiles/ana/matches", params={"limit": 3, "mode": "full"})
    assert len(bot.calls) == 1  # the second request was served from the cache

    plain = client.get("/profiles/ana/matches", params={"limit": 3, "explain": "false"}).json()
    assert all(m["explanation"] is None for m in plain)


def test_matches_without_an_llm_have_no_reasons(catalog, db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    app.dependency_overrides[get_embedder] = lambda: same_vector
    try:
        with TestClient(app) as client:  # LLM_API_KEY is blank in offline tests
            save_profile(catalog, "ana", BACKEND_NEVER_SALES)
            response = client.get("/profiles/ana/matches", params={"limit": 2})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert [m["explanation"] for m in response.json()] == [None, None]
