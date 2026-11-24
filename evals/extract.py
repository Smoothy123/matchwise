"""Run each persona's messages through the real preference extractor once, and freeze the result.

    python -m evals.extract            # extracts personas not yet in the file (safe to re-run)
    python -m evals.extract --fresh    # re-extract everyone

Ranking evals then read evals/profiles_extracted.json instead of calling the LLM,
so their numbers don't move when the LLM's output varies from run to run.
Re-extract only on purpose: if the preferences change, the labels may need a look.
"""

import argparse
import json
from datetime import datetime, timezone

import psycopg

from evals.data import EXTRACTED_JSON, EvalProfile, load_profiles
from matchwise import db
from matchwise.llm import LLMClient
from matchwise.preferences import PROMPT_VERSION, Preferences, process_message


def extract_one(conn: psycopg.Connection, llm: LLMClient, profile: EvalProfile) -> Preferences:
    profile_id = f"eval-{profile.id}"
    conn.execute("DELETE FROM profiles WHERE id = %s", (profile_id,))  # start fresh; messages cascade
    for message in profile.messages:
        result = process_message(conn, llm, profile_id, message)
    return result["preferences"]


def extract_all(conn: psycopg.Connection, llm: LLMClient, profiles: list[EvalProfile]) -> dict[str, Preferences]:
    return {profile.id: extract_one(conn, llm, profile) for profile in profiles}


def summary(prefs: Preferences) -> str:
    def nonempty(model) -> dict:
        return {k: v for k, v in model.model_dump().items() if v not in ([], None, False)}
    return json.dumps({"wants": nonempty(prefs.wants), "dealbreakers": nonempty(prefs.dealbreakers)})


def main() -> None:
    from matchwise.config import get_settings, setup_logging
    from matchwise.llm import client_from_settings

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging("WARNING")
    llm = client_from_settings(settings)
    saved = {} if args.fresh or not EXTRACTED_JSON.exists() else json.loads(EXTRACTED_JSON.read_text())["profiles"]
    with db.connect(settings.database_url) as conn:
        for profile in load_profiles():
            if profile.id in saved:
                continue
            prefs = extract_one(conn, llm, profile)
            saved[profile.id] = prefs.model_dump()
            # Saved after every persona, so an API outage only costs the persona in progress.
            EXTRACTED_JSON.write_text(json.dumps({
                "model": llm.model,
                "prompt_version": PROMPT_VERSION,
                "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "profiles": saved,
            }, indent=1) + "\n")
            print(f"{profile.id}: {summary(prefs)}")
    print(f"\n{len(saved)} personas in {EXTRACTED_JSON.name}; LLM usage this run: {llm.usage}")


if __name__ == "__main__":
    main()
