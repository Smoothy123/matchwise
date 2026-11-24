"""Match the places people name ("Texas", "Austin, TX", "Denver") against job locations.

Job locations look like "Austin, TX" (85% of postings), "United States",
"New York City Metropolitan Area" or "Greater Houston". A place becomes a list
of word groups that must *all* appear in the location, each group allowing
alternatives: "Austin, TX" -> [(Austin), (TX | Texas)]. So "Texas" matches
"Houston, TX", and "Dallas, TX" does not match "Dallas, OR".

Known gap: metro names without a state ("Greater Houston", "Dallas-Fort Worth
Metroplex") don't match a state-only place like "Texas".
"""

import re
from dataclasses import dataclass

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_ABBR_BY_NAME = {name.lower(): abbr for abbr, name in US_STATES.items()}

REMOTE_WORDS = {"remote", "anywhere", "work from home", "wfh"}


@dataclass(frozen=True)
class Place:
    groups: tuple[tuple[str, ...], ...]  # every group must match; any word within a group may


def state_abbr(text: str) -> str | None:
    text = text.strip()
    if text.upper() in US_STATES:
        return text.upper()
    return _ABBR_BY_NAME.get(text.lower())


def parse_place(text: str) -> Place | None:
    """None for 'remote'-style places, which are handled by the remote flag instead."""
    if text.strip().lower() in REMOTE_WORDS:
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None
    state = state_abbr(parts[-1])
    if state and len(parts) == 1:
        return Place(((state, US_STATES[state]),))
    if state:
        return Place(((parts[0],), (state, US_STATES[state])))
    return Place(((parts[0],),))  # e.g. "Bengaluru" or "Bengaluru, India"


def escape_regex(text: str) -> str:
    """Backslash-escape regex characters; the result works in Python and Postgres regexes."""
    return re.sub(r"([.^$*+?()\[\]{}|\\-])", r"\\\1", text)


def alternatives(words) -> str:
    """'a|b|c' with regex characters escaped, and any whitespace allowed between words."""
    return "|".join(re.sub(r"\s+", r"\\s+", escape_regex(w.strip())) for w in words)


def pg_regex(group) -> str:
    """Postgres regex: \\m and \\M are its start- and end-of-word anchors."""
    return rf"\m(?:{alternatives(group)})\M"


def py_regex(group) -> str:
    return rf"\b(?:{alternatives(group)})\b"


def location_matches(location: str | None, place: Place) -> bool:
    return bool(location) and all(re.search(py_regex(g), location, re.IGNORECASE) for g in place.groups)
