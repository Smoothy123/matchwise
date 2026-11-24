from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import BACKEND_NEVER_SALES, JOBS, same_vector, save_profile, unit_vector
from matchwise.api import app, get_embedder
from matchwise.filters import dealbreaker_sql
from matchwise.preferences import Dealbreakers, Preferences, Wants
from matchwise.ranking import (
    EXTRAS_WEIGHT, Mode, NoWants, combine, core_text, location_feature, match, query_vector, recency_feature,
    retrieve, salary_feature, seniority_feature, skills_feature,
)

# The `catalog` fixture (8 hand-built jobs, see JOBS in conftest.py) gives every test below
# the same small, fully known set of postings.


def passing(conn, dealbreakers: Dealbreakers, remote_ok: bool = False) -> set[str]:
    clauses, params = dealbreaker_sql(dealbreakers, remote_ok)
    ids = [r["id"] for r in retrieve(conn, unit_vector(0), clauses, params, limit=50)]
    rows = conn.execute("SELECT source_id FROM jobs WHERE id = ANY(%s)", (ids,)).fetchall()
    return {r["source_id"] for r in rows}


ALL = set(JOBS)


# ---------- dealbreakers as SQL filters ----------

@pytest.mark.parametrize("dealbreakers, excluded", [
    (Dealbreakers(), set()),
    (Dealbreakers(exclude_title_words=["sales"]), {"sales"}),               # not 'Wholesale Buyer'
    (Dealbreakers(exclude_functions=["Sales"]), {"sales"}),
    (Dealbreakers(exclude_description_phrases=["night shift"]), {"night"}),  # catches 'Night shifts'
    (Dealbreakers(exclude_description_phrases=["icu nursing"]), {"night"}),  # 'ICU Nurse' in the title
    (Dealbreakers(exclude_description_phrases=["sales"]), {"sales"}),        # not 'Wholesale Buyer'
    (Dealbreakers(exclude_companies=["HCA"]), {"night"}),
    (Dealbreakers(exclude_seniority=["intern", "entry"]), {"intern", "sales", "lowpay"}),
    (Dealbreakers(exclude_employment_types=["Contract"]), {"remote"}),
    (Dealbreakers(only_remote=True), ALL - {"remote"}),
    (Dealbreakers(only_locations=["Texas"]), {"dallas_or", "remote"}),      # remote jobs don't get a pass
    (Dealbreakers(only_locations=["Dallas, TX"]), ALL - {"lowpay"}),
    (Dealbreakers(only_locations=["Remote"]), set()),                       # 'remote' isn't a place
    (Dealbreakers(min_salary=100000), {"lowpay"}),                          # unknown salary passes
    (Dealbreakers(exclude_title_words=["sales"], only_locations=["Houston, TX"]), ALL - {"night"}),
])
def test_each_dealbreaker_filters_what_it_should(catalog, dealbreakers, excluded):
    assert passing(catalog, dealbreakers) == ALL - excluded


def test_remote_jobs_pass_a_location_limit_only_when_remote_is_fine(catalog):
    texas_only = Dealbreakers(only_locations=["Texas"])
    assert "remote" not in passing(catalog, texas_only)                  # said nothing about remote
    assert "remote" in passing(catalog, texas_only, remote_ok=True)       # said remote is fine
    assert "dallas_or" not in passing(catalog, texas_only, remote_ok=True)


def test_match_passes_remote_ok_from_the_wants(catalog):
    wants_remote = Preferences(wants=Wants(roles=["data engineer"], remote=True),
                               dealbreakers=Dealbreakers(only_locations=["Texas"]))
    no_view = Preferences(wants=Wants(roles=["data engineer"]), dealbreakers=Dealbreakers(only_locations=["Texas"]))
    titles_remote = {m["title"] for m in match(catalog, wants_remote, same_vector, mode=Mode.vector_filters, limit=8)}
    titles_none = {m["title"] for m in match(catalog, no_view, same_vector, mode=Mode.vector_filters, limit=8)}
    assert "Data Engineer" in titles_remote and "Data Engineer" not in titles_none


def test_values_are_parameters_not_sql(catalog):
    tricky = Dealbreakers(exclude_companies=["O'Reilly (test); DROP TABLE jobs"], exclude_title_words=["C++"])
    assert passing(catalog, tricky) == ALL


# ---------- features ----------

def test_core_text_uses_wants_and_never_dealbreakers():
    prefs = Preferences(
        wants=Wants(roles=["backend engineer"], skills=["python"], locations=["Austin, TX"],
                    seniority=["mid_senior"], other=["small team"]),
        dealbreakers=Dealbreakers(exclude_title_words=["sales"], exclude_functions=["Sales"]),
    )
    text = core_text(prefs.wants)
    assert text.splitlines() == ["backend engineer", "Mid-senior level · Austin, TX", "Skills: python"]
    assert "sales" not in text.lower() and "small team" not in text


def test_extras_only_nudge_the_query_vector():
    recorded = []

    def embed(texts):
        recorded.extend(texts)
        return np.stack([unit_vector(0), unit_vector(1)][: len(texts)])

    vector = query_vector(Wants(roles=["nurse"], other=["day shifts", "sign-on bonus"]), embed)
    assert recorded == ["nurse", "day shifts. sign-on bonus"]
    assert np.isclose(np.linalg.norm(vector), 1.0)
    assert vector[1] / vector[0] == pytest.approx(EXTRAS_WEIGHT)  # core dominates
    with pytest.raises(NoWants):
        query_vector(Wants(), embed)


def test_skills_feature_weights_rare_skills_more():
    idf = {"python": 1.0, "kafka": 3.0}
    assert skills_feature(["python", "kafka"], ["kafka"], idf) == 0.75
    assert skills_feature(["python", "kafka"], ["python"], idf) == 0.25
    assert skills_feature(["basket weaving"], ["python"], idf) is None  # not in the vocabulary
    assert skills_feature([], ["python"], idf) is None


@pytest.mark.parametrize("wants, job, expected", [
    (Wants(), {"location": "Austin, TX", "remote": False}, None),
    (Wants(locations=["Texas"]), {"location": "Austin, TX", "remote": False}, 1.0),
    (Wants(locations=["Texas"]), {"location": "Denver, CO", "remote": False}, 0.0),
    (Wants(locations=["Texas"]), {"location": "United States", "remote": True}, 0.7),
    (Wants(remote=True), {"location": "United States", "remote": True}, 1.0),
    (Wants(remote=False), {"location": "United States", "remote": True}, 0.3),
])
def test_location_feature(wants, job, expected):
    assert location_feature(wants, job) == expected


def test_seniority_feature():
    assert seniority_feature([], "entry") is None
    assert seniority_feature(["mid_senior"], "mid_senior") == 1.0
    assert seniority_feature(["mid_senior"], "associate") == 0.5
    assert seniority_feature(["mid_senior"], "intern") == 0.0
    assert seniority_feature(["mid_senior"], "unknown") == 0.5


def test_salary_feature():
    assert salary_feature(None, {"salary_max": 50000}) is None
    assert salary_feature(100000, {"salary_max": 120000}) == 1.0
    assert salary_feature(100000, {"salary_max": 80000}) == 0.0
    assert salary_feature(100000, {"salary_max": None}) == 0.5


def test_recency_halves_every_week():
    newest = datetime(2024, 4, 20, tzinfo=timezone.utc)
    assert recency_feature(newest, newest) == 1.0
    assert recency_feature(newest - timedelta(days=7), newest) == pytest.approx(0.5)


def test_combine_leaves_out_features_that_do_not_apply():
    score, breakdown = combine({"similarity": 1.0, "skills": None, "location": 0.0,
                                "seniority": None, "salary": None, "recency": 1.0})
    assert set(breakdown) == {"similarity", "location", "recency"}
    assert sum(b["weight"] for b in breakdown.values()) == pytest.approx(1.0, abs=1e-3)
    assert score == pytest.approx(sum(b["contribution"] for b in breakdown.values()), abs=1e-3)  # display rounding
    assert score == pytest.approx((0.45 + 0.05) / (0.45 + 0.15 + 0.05))


# ---------- the whole thing ----------

def test_vector_mode_ignores_dealbreakers_and_filters_mode_applies_them(catalog):
    vector = [m["title"] for m in match(catalog, BACKEND_NEVER_SALES, same_vector, mode=Mode.vector, limit=8)]
    filtered = [m["title"] for m in match(catalog, BACKEND_NEVER_SALES, same_vector, mode=Mode.vector_filters, limit=8)]
    assert "Sales Development Rep" in vector
    assert "Sales Development Rep" not in filtered
    # Without re-ranking, order is pure similarity: the job pointing exactly at the query comes first.
    assert vector[0] == filtered[0] == "Backend Engineer"


def test_full_mode_reranks_with_features(catalog):
    matches = match(catalog, BACKEND_NEVER_SALES, same_vector, mode=Mode.full, limit=8)
    first = matches[0]
    assert (first["title"], first["location"]) == ("Backend Engineer", "Austin, TX")  # skills + place + level
    assert first["matched_skills"] == ["postgresql", "python"]
    assert set(first["features"]) == {"similarity", "skills", "location", "seniority", "recency"}  # no salary want
    assert first["score"] == pytest.approx(sum(f["contribution"] for f in first["features"].values()), abs=1e-3)
    scores = [m["score"] for m in matches]
    assert scores == sorted(scores, reverse=True)
    assert all(m["title"] != "Sales Development Rep" for m in matches)
    # Same title, wrong state: ranks below the Austin one.
    oregon = next(i for i, m in enumerate(matches) if m["location"] == "Dallas, OR")
    assert oregon > 0


def test_a_profile_with_only_dealbreakers_has_nothing_to_search_for(catalog):
    with pytest.raises(NoWants):
        match(catalog, Preferences(dealbreakers=Dealbreakers(only_remote=True)), same_vector)


# ---------- the endpoint ----------

@pytest.fixture
def client(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    app.dependency_overrides[get_embedder] = lambda: same_vector
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_matches_endpoint(catalog, client):
    save_profile(catalog, "ana", BACKEND_NEVER_SALES)
    response = client.get("/profiles/ana/matches", params={"limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3 and body[0]["title"] == "Backend Engineer"
    assert set(body[0]["features"]["skills"]) == {"value", "weight", "contribution"}

    vector = client.get("/profiles/ana/matches", params={"mode": "vector", "limit": 8}).json()
    assert "Sales Development Rep" in [m["title"] for m in vector]
    assert client.get("/profiles/ana/matches", params={"mode": "bogus"}).status_code == 422


def test_matches_endpoint_errors(catalog, client):
    assert client.get("/profiles/nobody/matches").status_code == 404
    save_profile(catalog, "empty", Preferences())
    response = client.get("/profiles/empty/matches")
    assert response.status_code == 422 and "looking for" in response.json()["detail"]
