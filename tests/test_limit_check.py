import json
import re

import pytest
from fastapi.testclient import TestClient

from conftest import BACKEND_NEVER_SALES, same_vector, save_profile, scripted_llm
from matchwise import limit_check
from matchwise.api import app, get_embedder
from matchwise.limit_check import keep_allowed, limit_items
from matchwise.llm import Completion, LLMClient, LLMOutputError
from matchwise.preferences import Dealbreakers, Preferences, Wants
from matchwise.ranking import LimitCheckUnavailable, Mode, match

NO_CONTRACT = Preferences(
    wants=Wants(roles=["backend engineer"], skills=["python"]),
    dealbreakers=Dealbreakers(exclude_employment_types=["Contract"], exclude_title_words=["sales"]),
)


class CheckBot:
    """Fake LLM for the limit check: flags jobs whose card contains `trigger`, quoting it as evidence."""

    model = "check-bot"

    def __init__(self, trigger: str, limit_id: str = "L2", evidence: str | None = None):
        self.trigger, self.limit_id, self.evidence = trigger, limit_id, evidence
        self.calls: list[list[int]] = []

    def complete(self, messages):
        user = messages[1]["content"]
        cards = dict(re.findall(r"=== job (\d+) ===\n(.*?)(?=\n\n=== job|\Z)", user, re.S))
        self.calls.append(sorted(int(i) for i in cards))
        verdicts = []
        for job_id, card in cards.items():
            flag = self.trigger in card
            verdicts.append({"job_id": int(job_id), "breaks_limit": flag,
                             "limit_id": self.limit_id if flag else None,
                             "evidence": (self.evidence or self.trigger) if flag else None})
        return Completion(json.dumps({"verdicts": verdicts}), 300, 50)


def bot(trigger, **kwargs) -> tuple[LLMClient, CheckBot]:
    b = CheckBot(trigger, **kwargs)
    return LLMClient(b), b


def test_limits_are_numbered_rules_written_by_meaning():
    prefs = Preferences(wants=Wants(remote=True), dealbreakers=Dealbreakers(
        exclude_title_words=["sales"], exclude_description_phrases=["night shift"],
        exclude_employment_types=["Contract"], only_locations=["Texas"], min_salary=90000))
    assert limit_items(prefs) == {
        "L1": "the job itself is not a sales role (its duties may still mention sales)",
        "L2": "nothing involving night shift",
        "L3": "no contract, fixed-term or freelance work",
        "L4": "only jobs located in Texas or fully remote",
        "L5": "pay must reach at least $90,000 a year (when the posting states pay)",
    }
    assert limit_items(prefs, "limits-v1")["L1"] == "not a 'sales' job"   # v1 kept, so its numbers reproduce
    assert limit_items(Preferences(wants=Wants(roles=["x"]))) == {}


# The scripted checker flags 'Junior Developer': a job the SQL filters let through (its structured
# fields break no limit), which is exactly the case the LLM check exists for.
FLAGGED = "Title: Junior Developer"


def test_a_flagged_job_is_dropped_and_the_next_one_moves_up(catalog):
    ranked = match(catalog, NO_CONTRACT, same_vector, mode=Mode.full, limit=20)
    assert "Junior Developer" in [r["title"] for r in ranked]       # the SQL filters didn't catch it
    llm, b = bot(FLAGGED)
    kept, dropped = keep_allowed(catalog, llm, NO_CONTRACT, ranked, limit=3)
    assert [d["title"] for d in dropped] == ["Junior Developer"]
    assert dropped[0]["limit_check_verdict"]["limit"] == "no contract, fixed-term or freelance work"
    assert [k["job_id"] for k in kept] == [r["job_id"] for r in ranked if r["title"] != "Junior Developer"][:3]
    assert {k["limit_check"] for k in kept} == {"passed"}


def test_evidence_must_be_quoted_from_the_posting(catalog):
    ranked = match(catalog, NO_CONTRACT, same_vector, mode=Mode.full, limit=5)
    ids = sorted(r["job_id"] for r in ranked)
    invented = json.dumps({"verdicts": [
        {"job_id": i, "breaks_limit": i == ids[0], "limit_id": "L2" if i == ids[0] else None,
         "evidence": "a 6-month contract" if i == ids[0] else None} for i in ids]})
    honest = json.dumps({"verdicts": [{"job_id": i, "breaks_limit": False} for i in ids]})
    llm = scripted_llm(invented, honest)
    kept, dropped = keep_allowed(catalog, llm, NO_CONTRACT, ranked, limit=5)
    assert dropped == [] and len(kept) == 5
    assert "evidence must be an exact quote from that posting" in llm.transport.calls[1][-1]["content"]


def test_only_the_persons_own_limits_can_be_cited(catalog):
    ranked = match(catalog, NO_CONTRACT, same_vector, mode=Mode.full, limit=8)
    llm, b = bot(FLAGGED, limit_id="L9")          # L9 doesn't exist: this person has two limits
    with pytest.raises(LLMOutputError):          # every retry cites it, so the call fails...
        limit_check.judge_batch(llm, limit_items(NO_CONTRACT), {1: FLAGGED})
    kept, dropped = keep_allowed(catalog, llm, NO_CONTRACT, ranked, limit=8)
    assert dropped == [] and [k["job_id"] for k in kept] == [r["job_id"] for r in ranked[:8]]  # fails open...
    assert {k["limit_check"] for k in kept} == {"skipped"}    # ...visibly
    with pytest.raises(LLMOutputError):          # evals ask it not to, so no number rests on a skipped check
        keep_allowed(catalog, llm, NO_CONTRACT, ranked, limit=8, fail_open=False)


def test_no_limits_means_no_llm_call(catalog):
    prefs = Preferences(wants=Wants(roles=["backend engineer"]))
    ranked = match(catalog, prefs, same_vector, mode=Mode.full, limit=5)
    llm, b = bot("anything")
    kept, dropped = keep_allowed(catalog, llm, prefs, ranked, limit=3)
    assert [k["job_id"] for k in kept] == [r["job_id"] for r in ranked[:3]] and dropped == [] and b.calls == []
    assert {k["limit_check"] for k in kept} == {"no limits"}


def test_cached_verdicts_still_count_when_the_llm_is_down(catalog):
    ranked = match(catalog, NO_CONTRACT, same_vector, mode=Mode.full, limit=8)
    llm, _ = bot(FLAGGED)
    keep_allowed(catalog, llm, NO_CONTRACT, ranked[:3], limit=3)              # verdicts for the top 3 cached
    down = scripted_llm("bad", "bad", "bad")                                  # then the LLM starts failing
    down.transport.model = llm.model                                          # (same model, so same cache keys)
    kept, dropped = keep_allowed(catalog, down, NO_CONTRACT, ranked, limit=8)
    statuses = {k["title"]: k["limit_check"] for k in kept}
    flagged_was_cached = "Junior Developer" in [r["title"] for r in ranked[:3]]
    assert ("Junior Developer" in [d["title"] for d in dropped]) == flagged_was_cached
    assert [k["limit_check"] for k in kept[:2]] == ["passed", "passed"]      # cached: still checked
    assert "skipped" in statuses.values()                                     # the rest: visibly unchecked


def test_verdicts_are_cached(catalog):
    ranked = match(catalog, NO_CONTRACT, same_vector, mode=Mode.full, limit=8)
    llm, b = bot(FLAGGED)
    first = keep_allowed(catalog, llm, NO_CONTRACT, ranked, limit=5)
    second = keep_allowed(catalog, llm, NO_CONTRACT, ranked, limit=5)
    assert first == second and len(b.calls) == 1


def test_checked_mode_in_match_and_the_api(catalog, db_url, monkeypatch):
    with pytest.raises(LimitCheckUnavailable):
        match(catalog, NO_CONTRACT, same_vector, mode=Mode.checked)
    llm, _ = bot(FLAGGED)
    full = [m["title"] for m in match(catalog, NO_CONTRACT, same_vector, mode=Mode.full, limit=8)]
    checked = [m["title"] for m in match(catalog, NO_CONTRACT, same_vector, mode=Mode.checked, limit=8, llm=llm)]
    assert "Junior Developer" in full and "Junior Developer" not in checked

    monkeypatch.setenv("DATABASE_URL", db_url)
    app.dependency_overrides[get_embedder] = lambda: same_vector
    try:
        with TestClient(app) as client:  # no LLM configured in offline tests
            save_profile(catalog, "ana", BACKEND_NEVER_SALES)
            response = client.get("/profiles/ana/matches", params={"mode": "checked"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503 and "needs the LLM" in response.json()["detail"]
