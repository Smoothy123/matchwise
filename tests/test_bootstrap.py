from conftest import fake_embed
from matchwise import bootstrap


def test_first_run_loads_and_embeds_then_later_runs_do_nothing(conn, db_url, raw_dir):
    assert bootstrap.run(db_url, raw_dir, limit=2, embed=fake_embed) == {"status": "ready", "loaded": 2, "embedded": 2}
    assert bootstrap.run(db_url, raw_dir, limit=2, embed=fake_embed) == {"status": "ready", "loaded": 0, "embedded": 0}


def test_without_the_dataset_it_explains_and_lets_the_api_start(conn, db_url, tmp_path):
    assert bootstrap.run(db_url, tmp_path / "nothing-here", embed=fake_embed)["status"] == "no data"


def test_jobs_missing_vectors_get_embedded(conn, db_url, raw_dir):
    bootstrap.run(db_url, raw_dir, limit=2, embed=fake_embed)
    conn.execute("UPDATE jobs SET embedding = NULL, embedded_hash = NULL WHERE id = 1")
    assert bootstrap.run(db_url, raw_dir, limit=2, embed=fake_embed)["embedded"] == 1
