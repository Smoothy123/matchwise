"""Turn dealbreakers into SQL WHERE clauses (hard filters).

Every value goes in as a query parameter, never pasted into the SQL text, so a
dealbreaker like "O'Reilly" can't break or inject into the query. Each clause
is written so that a job is kept only if it breaks none of the person's limits.

Two policy choices, both deliberate:
- Unknown is allowed through. A job with no salary passes a minimum-salary limit
  (70% of postings list none), and a job with no employment type passes an
  employment-type limit. Hiding them would hide most of the market; instead,
  Phase 5's reasons flag the unknown as a caveat.
- A remote job passes a location limit only if the person said remote is fine.
  (First version: remote always passed. The evals showed why that's wrong: LinkedIn
  marks some field jobs as remote, so "Pennsylvania or New Jersey only" surfaced
  HVAC jobs in Wisconsin, Florida and Colorado.)
"""

from matchwise.places import escape_regex, parse_place, pg_regex
from matchwise.preferences import Dealbreakers

# Trimmed from the end of each phrase word so its other forms match too.
SUFFIXES = ("ing", "es", "ed", "s", "e")
MIN_STEM = 4  # never trim below this: 'sales' must not become 'sal' and match 'salary'


def words_regex(words: list[str]) -> str:
    """Whole words or phrases, case-insensitive with ~*: 'sales' matches 'Sales Rep', not 'wholesale'."""
    return pg_regex(words)


def loose_word(word: str) -> str:
    """'nursing' -> 'nurs\\w*', so it also matches 'nurse' and 'nurses'. A tiny stand-in for a stemmer."""
    word = word.lower()
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            word = word[: -len(suffix)]
            break
    return escape_regex(word) + r"\w*"


def phrases_regex(phrases: list[str]) -> str:
    """Phrases in any common form, starting at a word boundary:
    'travel nursing' matches 'Travel Nurse'; 'night shift' matches 'night shifts' (not 'overnight shift');
    'sales' matches 'salesperson' but not 'wholesale'."""
    return r"\m(?:" + "|".join(r"\s+".join(loose_word(w) for w in p.split()) for p in phrases) + ")"


def dealbreaker_sql(d: Dealbreakers, remote_ok: bool = False) -> tuple[list[str], dict]:
    """WHERE clauses (to be ANDed) and their named parameters.

    remote_ok: the person said remote work is fine, so remote jobs pass a location limit.
    """
    clauses: list[str] = []
    params: dict = {}

    def param(value) -> str:
        name = f"f{len(params)}"
        params[name] = value
        return f"%({name})s"

    if d.exclude_title_words:
        clauses.append(f"NOT (title ~* {param(words_regex(d.exclude_title_words))})")
    if d.exclude_functions:
        clauses.append(f"NOT (functions && {param(list(d.exclude_functions))}::text[])")
    if d.exclude_industries:
        clauses.append(
            f"NOT EXISTS (SELECT 1 FROM unnest(industries) AS i WHERE i ~* {param(words_regex(d.exclude_industries))})")
    if d.exclude_companies:
        clauses.append(f"NOT (coalesce(company, '') ~* {param(words_regex(d.exclude_companies))})")
    if d.exclude_description_phrases:
        # The whole posting: a 'Travel Nurse' title is as clear as the description.
        clauses.append(
            f"NOT ((title || ' ' || description) ~* {param(phrases_regex(d.exclude_description_phrases))})")
    if d.exclude_seniority:
        clauses.append(f"seniority <> ALL({param(list(d.exclude_seniority))})")
    if d.exclude_employment_types:
        clauses.append(
            f"(employment_type IS NULL OR employment_type <> ALL({param(list(d.exclude_employment_types))}))")
    if d.only_remote:
        clauses.append("remote")
    places = [p for p in map(parse_place, d.only_locations) if p is not None]
    if places:
        any_place = " OR ".join(
            "(" + " AND ".join(f"coalesce(location, '') ~* {param(pg_regex(g))}" for g in place.groups) + ")"
            for place in places
        )
        clauses.append(f"(remote OR {any_place})" if remote_ok else f"({any_place})")
    if d.min_salary:
        clauses.append(f"(salary_max IS NULL OR salary_max >= {param(d.min_salary)})")
    return clauses, params
