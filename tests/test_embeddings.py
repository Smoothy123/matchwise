import numpy as np
import pytest

from conftest import LONG_TEXT, fake_embed, raw_posting
from matchwise import embeddings, ingest
from matchwise.embeddings import DESCRIPTION_CHARS, card_hash, job_card


def card_row(**overrides) -> dict:
    row = {
        "title": "Backend Engineer",
        "seniority": "mid_senior",
        "employment_type": "Full-time",
        "location": "Austin, TX",
        "remote": True,
        "functions": ["Engineering"],
        "skills": ["python", "postgresql"],
        "description": "Build APIs. " + LONG_TEXT,
    }
    row.update(overrides)
    return row


def test_card_puts_what_the_job_is_first():
    lines = job_card(card_row()).splitlines()
    assert lines[0] == "Backend Engineer"
    assert lines[1] == "Mid-senior level · Full-time · Austin, TX · Remote"
    assert lines[2] == "Functions: Engineering"
    assert lines[3] == "Skills: python, postgresql"
    assert lines[4].startswith("Build APIs.")


def test_card_skips_missing_facts():
    card = job_card(card_row(seniority="unknown", employment_type=None, remote=False, functions=[], skills=[]))
    assert card.splitlines()[:2] == ["Backend Engineer", "Austin, TX"]


def test_card_cuts_long_descriptions_on_a_word_boundary():
    card = job_card(card_row(description="word " * 1000))
    description = card.splitlines()[-1]
    assert len(description) <= DESCRIPTION_CHARS
    assert description.endswith("word")


def test_card_drops_emails_and_legal_text():
    card = job_card(card_row(description="Build APIs. Email jobs@acme.com. We are an equal opportunity employer."))
    # The email pattern takes the full stop after the address too, so "Email" joins
    # the legal sentence and is dropped with it. Fine: it is contact boilerplate.
    assert card.splitlines()[-1] == "Build APIs."


def test_card_hash_changes_with_the_card_only():
    assert card_hash(job_card(card_row())) == card_hash(job_card(card_row()))
    assert card_hash(job_card(card_row(skills=["python"]))) != card_hash(job_card(card_row()))
    # Text past the cut-off never reaches the model, so it must not change the card.
    long = "word " * 1000
    assert job_card(card_row(description=long)) == job_card(card_row(description=long + "extra"))


# ---------- database ----------

def _load(conn, *ids: str) -> None:
    jobs = [ingest.normalise(raw_posting(job_id=i, title=f"Job {i}"), ingest.Lookups({}, {}, {})) for i in ids]
    ingest.upsert_jobs(conn, jobs)


def test_embed_pending_only_embeds_what_changed(conn):
    _load(conn, "1", "2", "3")
    assert embeddings.embed_pending(conn, embed=fake_embed)["embedded"] == 3
    assert embeddings.embed_pending(conn, embed=fake_embed)["embedded"] == 0  # nothing changed

    conn.execute("UPDATE jobs SET title = 'Staff Engineer' WHERE source_id = '2'")
    conn.execute("UPDATE jobs SET is_active = false WHERE source_id = '3'")
    conn.execute("UPDATE jobs SET description = description || ' edited' WHERE source_id = '1'")
    result = embeddings.embed_pending(conn, embed=fake_embed)
    # Job 2's card changed; job 3 is inactive; job 1's edit (appended to a short
    # description) also changes its card.
    assert (result["checked"], result["embedded"]) == (2, 2)


def test_stored_vector_matches_the_card(conn):
    _load(conn, "1")
    embeddings.embed_pending(conn, embed=fake_embed)
    row = conn.execute("SELECT * FROM jobs").fetchone()
    card = job_card(row)
    assert row["embedded_hash"] == card_hash(card)
    # pgvector returns a Vector object; to_numpy() gives the float32 array back.
    np.testing.assert_allclose(row["embedding"].to_numpy(), fake_embed([card])[0], rtol=1e-6)


# ---------- the real model ----------

@pytest.mark.model
def test_minilm_puts_related_text_closer():
    query, backend, nurse = embeddings.embed_texts(
        ["python backend developer", "Software Engineer, APIs and databases", "Registered Nurse, ICU night shift"]
    )
    assert query.shape == (embeddings.DIMENSIONS,)
    assert np.isclose(np.linalg.norm(query), 1.0, atol=1e-5)  # normalised
    assert query @ backend > query @ nurse + 0.2
