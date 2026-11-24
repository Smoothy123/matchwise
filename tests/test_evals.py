import json

import pytest

from conftest import BACKEND_NEVER_SALES, same_vector, scripted_llm
from evals import judge as judge_module
from evals.data import Label, load_labels, load_profiles
from evals.extract import extract_all
from evals.label import build_pool, keyword_query
from evals.run_ranking import evaluate, markdown_table, score_ranking, summarise
from matchwise.preferences import Preferences, Wants
from matchwise.ranking import Mode


def test_the_personas_file_is_valid():
    profiles = load_profiles()
    assert len(profiles) == 15
    assert len({p.id for p in profiles}) == 15
    assert all(p.messages and all(m.strip() for m in p.messages) for p in profiles)


def test_newest_label_wins(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [
        {"profile": "a", "source_id": "1", "grade": 0, "violation": False},
        {"profile": "a", "source_id": "2", "grade": 1, "violation": False},
        {"profile": "a", "source_id": "1", "grade": 2, "violation": True},   # relabelled
    ]))
    labels = load_labels(path)
    assert labels[("a", "1")] == Label("a", "1", 2, True) and len(labels) == 2


# ---------- pooling ----------

def test_keyword_query_uses_roles_and_skills():
    assert keyword_query(Preferences(wants=Wants(roles=["Backend engineer"], skills=["python", "c#"]))) == \
        "backend or engineer or python"


def test_pool_is_the_deduplicated_union_in_a_fixed_shuffled_order(catalog):
    systems_only = build_pool(catalog, "ana", BACKEND_NEVER_SALES, same_vector, depth=3, keyword_depth=0)
    with_keywords = build_pool(catalog, "ana", BACKEND_NEVER_SALES, same_vector, depth=3, keyword_depth=8)
    assert with_keywords == build_pool(catalog, "ana", BACKEND_NEVER_SALES, same_vector, depth=3, keyword_depth=8)
    assert len(with_keywords) == len(set(with_keywords))
    assert "sales" in systems_only   # vector-only ranks it, so it must be judged
    # No system ranks 'Wholesale Buyer' in its top 3, but its description mentions Python,
    # so the keyword search brings it into the pool: the pool isn't only what our systems like.
    assert "wholesale" not in systems_only and "wholesale" in with_keywords
    assert set(systems_only) <= set(with_keywords)
    assert with_keywords != build_pool(catalog, "bob", BACKEND_NEVER_SALES, same_vector, depth=3, keyword_depth=8)


# ---------- ranking eval ----------

def labels_for(profile: str, grades: dict[str, int], violations: set[str] = frozenset()) -> dict:
    return {(profile, sid): Label(profile, sid, g, sid in violations) for sid, g in grades.items()}


def test_score_ranking():
    labels = list(labels_for("p", {"a": 2, "b": 1, "c": 0, "x": 0}, violations={"x"}).values())
    scores = score_ranking(["a", "x", "c", "z"], labels)
    assert scores["P@5"] == 1 / 5
    assert scores["R@20"] == 1.0
    assert scores["violations@10"] == 1 / 4
    assert scores["judged@10"] == 3 / 4   # 'z' has no label


def test_evaluate_and_table():
    labels = {**labels_for("p1", {"a": 2, "s": 0}, {"s"}), **labels_for("p2", {"b": 2})}
    rankings = {
        (Mode.vector, "p1"): ["s", "a"], (Mode.vector_filters, "p1"): ["a"], (Mode.full, "p1"): ["a"],
        (Mode.vector, "p2"): ["q", "b"], (Mode.vector_filters, "p2"): ["q", "b"], (Mode.full, "p2"): ["b", "q"],
    }
    results = evaluate(lambda pid, mode: rankings[(mode, pid)], ["p1", "p2"], labels)
    assert results["vector only"]["p1"]["violations@10"] == 0.5
    assert results["vector + filters"]["p1"]["violations@10"] == 0.0
    assert results["vector + filters + re-ranking"]["p2"]["nDCG@10"] == 1.0
    table = markdown_table({v: summarise(s) for v, s in results.items()})
    assert table.splitlines()[0] == "| Version | P@5 | R@20 | nDCG@10 | violations@10 | judged@10 |"
    assert len(table.splitlines()) == 5


# ---------- freezing preferences ----------

def test_extract_all_runs_every_message_in_order(conn):
    from evals.data import EvalProfile
    reply = lambda value: json.dumps({"operations": [  # noqa: E731
        {"op": "add", "field": "wants.roles", "value": value, "evidence": "e"}], "notes": []})
    llm = scripted_llm(reply("nurse"), reply("ICU nurse"))
    extracted = extract_all(conn, llm, [EvalProfile("p", ["first", "second"])])
    assert extracted["p"].wants.roles == ["nurse", "ICU nurse"]
    assert "Newest message:\nsecond" in llm.transport.calls[1][1]["content"]


# ---------- judge ----------

EXPLANATION = {"reason": "A backend role in Austin using Python.", "matched_preferences": ["role: backend engineer"],
               "caveats": ["Salary not stated"]}
JOB = {"source_id": "be", "title": "Backend Engineer", "company": "Acme", "location": "Austin, TX", "remote": False,
       "seniority": "mid_senior", "employment_type": "Full-time", "salary_min": None, "salary_max": None,
       "skills": ["python", "postgresql"], "description": "Build APIs. " + "Lots of detail. " * 300 + "We use Python."}


def test_judge_prompt_shows_what_was_said_and_hides_our_known_gaps():
    from evals.data import EvalProfile
    prompt = judge_module.judge_prompt(EvalProfile("p", ["I want backend work"]), JOB, EXPLANATION)
    assert '"I want backend work"' in prompt and "Claims these preferences are met: role: backend engineer" in prompt
    assert "Known gaps" not in prompt


def test_judge_sees_the_same_evidence_as_the_writer():
    """judge-v1 cut descriptions at 2,500 characters and called late-mentioned skills 'invented'."""
    from evals.data import EvalProfile
    prompt = judge_module.judge_prompt(EvalProfile("p", ["I want backend work"]), JOB, EXPLANATION)
    assert "We use Python." in prompt                                   # past character 2,500
    assert "Skills tagged anywhere in the posting: python, postgresql" in prompt


def test_judgements_are_cached(tmp_path, monkeypatch):
    from evals.data import EvalProfile
    monkeypatch.setattr(judge_module, "JUDGEMENTS_JSONL", tmp_path / "judgements.jsonl")
    reply = json.dumps({"specific": 4, "grounded": 5, "honest": 3, "rationale": "Names the role and place."})
    llm = scripted_llm(reply)
    items = [{"profile": "p", "job": JOB, "explanation": EXPLANATION}]
    profiles = [EvalProfile("p", ["I want backend work"])]
    first = judge_module.judge_all(llm, profiles, items, "reasons-v1")
    second = judge_module.judge_all(llm, profiles, items, "reasons-v1")  # no reply left: must come from the cache
    assert first == second and first[0]["grounded"] == 5
    assert len(llm.transport.calls) == 1
    assert "| reasons-v1 | scripted | 4.00 | 5.00 | 3.00 | 1 |" in judge_module.summary_table(first)


def test_paired_comparison_uses_only_postings_judged_in_both_versions():
    def rec(profile, sid, version, s, g, h):
        return {"profile": profile, "source_id": sid, "reasons_prompt_version": version,
                "specific": s, "grounded": g, "honest": h}
    records = [
        rec("p1", "a", "v1", 4, 3, 2), rec("p1", "a", "v2", 5, 4, 4),
        rec("p1", "b", "v1", 4, 4, 3), rec("p1", "b", "v2", 4, 4, 5),
        rec("p2", "c", "v1", 3, 2, 1), rec("p2", "c", "v2", 3, 4, 2),
        rec("p2", "only-v1", "v1", 1, 1, 1),                        # no v2 counterpart: left out
    ]
    change = judge_module.paired_comparison(records, "v1", "v2")
    # honest: p1 mean change (2 + 2) / 2 = 2, p2 change 1 -> mean over personas 1.5
    assert change["honest"][0] == pytest.approx(1.5) and change["honest"][3] == 3
    assert change["grounded"][0] == pytest.approx((0.5 + 2) / 2)
    table = judge_module.comparison_table(records, "v1", "v2")
    assert table.splitlines()[-1].startswith("| change (95% CI) | +0.25")


def test_agreement():
    judged = [{"reason_hash": h, "specific": s, "grounded": g, "honest": o}
              for h, s, g, o in [("a", 5, 5, 4), ("b", 3, 4, 2), ("c", 4, 2, 5)]]
    human = [{"reason_hash": h, "specific": s, "grounded": g, "honest": o}
             for h, s, g, o in [("a", 5, 4, 4), ("b", 1, 4, 3), ("z", 1, 1, 1)]]   # 'z' was never judged
    stats = judge_module.agreement(judged, human)
    assert stats["specific"]["n"] == 2
    assert stats["specific"]["exact"] == 0.5 and stats["specific"]["within_1"] == 0.5
    assert stats["grounded"]["mean_abs_diff"] == 0.5
    assert stats["honest"]["judge_mean"] == 3.0 and stats["honest"]["reference_mean"] == 3.5
    assert "| specific | 50% | 50% | 1.00 | 4.00 | 3.00 | 2 |" in judge_module.agreement_table(stats)
