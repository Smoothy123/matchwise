"""Tag text with skills from a fixed vocabulary (matchwise/skills.txt).

Matching is case-insensitive and on whole terms: 'java' does not match inside
'javascript', 'excel' not inside 'excellent', 'sql' not inside 'mysql'.
Every alias maps to one canonical name, so 'Postgres' and 'PostgreSQL' both
become 'postgresql' and can be compared across postings and preferences.
"""

import re
from functools import lru_cache
from pathlib import Path

VOCAB_PATH = Path(__file__).with_name("skills.txt")

# A term may not touch a letter, digit, '+' or '#' on either side. That keeps
# 'c++' and 'c#' whole and stops a term matching inside a longer word.
_WORD_CHAR = r"[a-z0-9+#]"

# Text that says nothing about the job itself. Links and emails produce matches
# like 'Recruitment@acme.com'; equal-opportunity and legal sentences mention
# 'recruitment' and 'compliance' in almost every posting.
_LINK_OR_EMAIL = re.compile(r"\S+@\S+|https?://\S+|www\.\S+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LEGAL_MARKERS = (
    "equal opportunity", "without regard to", "discriminat",
    "reasonable accommodation", "e-verify", "eeo",
)


def load_vocabulary(path: Path = VOCAB_PATH) -> dict[str, str]:
    """Map every lower-cased term (canonical name or alias) to its canonical name."""
    term_to_skill: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms = [t.strip().lower() for t in line.split("|") if t.strip()]
        canonical = terms[0]
        for term in terms:
            if term in term_to_skill:
                raise ValueError(f"{path.name}:{line_no}: '{term}' is listed twice")
            term_to_skill[term] = canonical
    return term_to_skill


def build_pattern(terms: list[str]) -> re.Pattern[str]:
    # Longest terms first, so 'react native' wins over 'react' at the same position.
    alternatives = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!{_WORD_CHAR})(?:{alternatives})(?!{_WORD_CHAR})")


@lru_cache(maxsize=1)
def _matcher() -> tuple[re.Pattern[str], dict[str, str]]:
    vocab = load_vocabulary()
    return build_pattern(list(vocab)), vocab


def strip_boilerplate(text: str) -> str:
    """Remove links, email addresses and legal/equal-opportunity sentences."""
    text = _LINK_OR_EMAIL.sub(" ", text)
    sentences = _SENTENCE_END.split(text)
    return " ".join(s for s in sentences if not any(m in s.lower() for m in _LEGAL_MARKERS))


def extract_skills(text: str) -> list[str]:
    """Canonical skill names found in `text`, sorted."""
    pattern, vocab = _matcher()
    normalised = " ".join(strip_boilerplate(text).lower().split())  # 'machine\nlearning' still matches
    return sorted({vocab[m.group(0)] for m in pattern.finditer(normalised)})
