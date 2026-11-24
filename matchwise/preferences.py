"""A person's job preferences, extracted from plain-language messages and kept up to date.

Stored state is a Preferences object with two parts:
  wants         soft: what makes a job better (used to rank, Phase 4)
  dealbreakers  hard: what rules a job out (used as SQL filters, Phase 4)

For each new message the LLM does not rewrite the state. It returns *operations*
("add 'Denver, CO' to wants.locations", "remove 'Sales' from
dealbreakers.exclude_functions") and apply_operations() applies them in Python.
A model asked to rewrite everything can silently drop an earlier preference;
with operations every change is explicit, stored next to the message that
caused it, and testable without an LLM.
"""

from typing import Annotated, Any, Literal, get_args, get_origin

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, StringConstraints, TypeAdapter, ValidationError, model_validator

from matchwise.llm import LLMClient
from matchwise.skills import load_vocabulary

# v2 (found while building the eval set): v1 turned "no audit roles" (an accountant) and
# "no substitute teaching" (a teacher) into excluding their own whole job function, and
# wrote phrases too specific to ever match a posting ("on-call weekends").
PROMPT_VERSION = "preferences-v2"

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Seniority = Literal["intern", "entry", "associate", "mid_senior", "director", "executive"]
EmploymentType = Literal["Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer", "Other"]
# LinkedIn's job functions, exactly as they appear in the dataset (mappings/skills.csv).
JobFunction = Literal[
    "Accounting/Auditing", "Administrative", "Advertising", "Analyst", "Art/Creative",
    "Business Development", "Consulting", "Customer Service", "Design", "Distribution",
    "Education", "Engineering", "Finance", "General Business", "Health Care Provider",
    "Human Resources", "Information Technology", "Legal", "Management", "Manufacturing",
    "Marketing", "Other", "Product Management", "Production", "Project Management",
    "Public Relations", "Purchasing", "Quality Assurance", "Research", "Sales", "Science",
    "Strategy/Planning", "Supply Chain", "Training", "Writing/Editing",
]


class Wants(BaseModel):
    """Soft preferences: a job that matches more of these ranks higher."""
    roles: list[ShortText] = []
    skills: list[ShortText] = []
    locations: list[ShortText] = []
    industries: list[ShortText] = []
    seniority: list[Seniority] = []
    remote: bool | None = None          # True = prefers remote, False = prefers on-site
    min_salary: int | None = Field(default=None, gt=0)   # yearly pay they'd like
    other: list[ShortText] = []         # anything else that matters to them, in their words


class Dealbreakers(BaseModel):
    """Hard limits: a job that breaks any of these is never shown."""
    exclude_title_words: list[ShortText] = []
    exclude_functions: list[JobFunction] = []
    exclude_industries: list[ShortText] = []
    exclude_companies: list[ShortText] = []
    exclude_description_phrases: list[ShortText] = []
    exclude_seniority: list[Seniority] = []
    exclude_employment_types: list[EmploymentType] = []
    only_locations: list[ShortText] = []
    only_remote: bool = False
    min_salary: int | None = Field(default=None, gt=0)   # yearly pay below this rules a job out


class Preferences(BaseModel):
    wants: Wants = Wants()
    dealbreakers: Dealbreakers = Dealbreakers()


SECTIONS: dict[str, type[BaseModel]] = {"wants": Wants, "dealbreakers": Dealbreakers}

# Every field an operation may change. A test checks this matches the models above.
FieldPath = Literal[
    "wants.roles", "wants.skills", "wants.locations", "wants.industries", "wants.seniority",
    "wants.remote", "wants.min_salary", "wants.other",
    "dealbreakers.exclude_title_words", "dealbreakers.exclude_functions",
    "dealbreakers.exclude_industries", "dealbreakers.exclude_companies",
    "dealbreakers.exclude_description_phrases", "dealbreakers.exclude_seniority",
    "dealbreakers.exclude_employment_types", "dealbreakers.only_locations",
    "dealbreakers.only_remote", "dealbreakers.min_salary",
]


def _field_info(path: str):
    section, name = path.split(".")
    return SECTIONS[section].model_fields[name]


def is_list_field(path: str) -> bool:
    return get_origin(_field_info(path).annotation) is list


def _value_adapter(path: str) -> TypeAdapter:
    """Validator for one value of the field: a list item, or the single value with its limits (e.g. > 0)."""
    info = _field_info(path)
    if is_list_field(path):
        return TypeAdapter(get_args(info.annotation)[0])
    if info.metadata:
        return TypeAdapter(Annotated[(info.annotation, *info.metadata)])
    return TypeAdapter(info.annotation)


class Operation(BaseModel):
    op: Literal["add", "remove", "set", "clear"] = Field(
        description="add/remove for list fields, set/clear for single-value fields")
    field: FieldPath
    value: str | int | bool | None = None
    evidence: str = Field(description="The words in the message this change comes from")

    @model_validator(mode="after")
    def check_value_fits_field(self) -> "Operation":
        """Reject operations that don't fit their field, so the LLM is asked to fix them."""
        if is_list_field(self.field):
            if self.op not in ("add", "remove"):
                raise ValueError(f"{self.field} is a list: use add or remove, not {self.op}")
            self.value = self._validated_value()
        elif self.op == "set":
            self.value = self._validated_value()
            if self.value is None:
                raise ValueError(f"set needs a value for {self.field}; use clear to remove it")
        elif self.op != "clear":
            raise ValueError(f"{self.field} holds one value: use set or clear, not {self.op}")
        return self

    def _validated_value(self):
        # Name the field in the error, so the retry message tells the LLM exactly what to fix.
        try:
            return _value_adapter(self.field).validate_python(self.value)
        except ValidationError as error:
            raise ValueError(f"{self.field}: {error.errors()[0]['msg']}") from None


class Extraction(BaseModel):
    """What the LLM returns for one message."""
    operations: list[Operation] = []
    notes: list[str] = Field(default=[], description="Short notes for the user, e.g. a limit you could not apply")


# ---------- applying operations ----------

def apply_operations(preferences: Preferences, operations: list[Operation]) -> Preferences:
    """Return new preferences with the operations applied in order. Pure function."""
    data = preferences.model_dump()
    for operation in operations:
        section, name = operation.field.split(".")
        target = data[section]
        if operation.op == "add":
            value = _normalise(operation.field, operation.value)
            if not any(_same(existing, value) for existing in target[name]):
                target[name].append(value)
        elif operation.op == "remove":
            value = _normalise(operation.field, operation.value)
            target[name] = [existing for existing in target[name] if not _same(existing, value)]
        elif operation.op == "set":
            target[name] = operation.value
        else:  # clear
            target[name] = SECTIONS[section].model_fields[name].default
    return Preferences.model_validate(data)


def _normalise(path: str, value: Any) -> Any:
    """Skills use the same canonical names as job postings, so 'Postgres' matches 'postgresql'."""
    if path == "wants.skills":
        return load_vocabulary().get(value.lower(), value.lower())
    return value


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()
    return a == b


# ---------- asking the LLM ----------

SYSTEM_PROMPT = """You keep a job seeker's stored preferences up to date.
You get their current preferences (JSON) and their newest message. Return the
changes that message makes, as a list of operations.

How to read the message
- Hard limits go in dealbreakers: "never", "no", "won't", "must", "only", "at least", "can't".
- Soft wishes go in wants: "I'd like", "prefer", "ideally", "interested in", or plain statements of what they want to do.
- Change only what the message talks about. Everything it doesn't mention stays as it is.
- If the message contradicts a stored value, remove the old value and add or set the new one.
  Example: stored wants.locations ["Austin, TX"], message "actually Denver instead"
  -> remove "Austin, TX" from wants.locations, add "Denver, CO".
- If they drop a limit ("I'm open to sales now"), remove the matching dealbreakers.
- "Never <a whole kind of work>" they don't do usually needs two operations: the word for
  dealbreakers.exclude_title_words and the matching job function, e.g. "never sales" ->
  exclude_title_words "sales" and exclude_functions "Sales".
- But never exclude the job function of the work they are looking for. When they rule out part of
  their own field, use only a title word or phrase: an accountant's "no audit roles" ->
  exclude_title_words "audit" (not exclude_functions "Accounting/Auditing"); a teacher's
  "no substitute teaching" -> exclude_title_words "substitute" (not exclude_functions "Education").
- Keep phrases short, the way postings write them: "on-call" (not "on-call weekends"),
  "long haul" (not "overnight long-haul"), "night shift" (not "night shifts only").
- If a hard limit can't be expressed with the dealbreaker fields, add it to wants.other and say in notes
  that it will be treated as a preference, not a filter.
- Don't invent preferences the message doesn't state or clearly imply. Quote the message in evidence.

Fields
- wants.roles: kinds of work, e.g. "backend engineer", "ICU nurse"
- wants.skills: skills or tools they want to use, e.g. "python"
- wants.locations: places they'd like to work, as "City, ST" when the state is clear
- wants.industries, wants.other (anything else that matters to them, in their words)
- wants.seniority, dealbreakers.exclude_seniority: intern, entry, associate, mid_senior, director, executive
- wants.remote: true = prefers remote, false = prefers on-site
- wants.min_salary, dealbreakers.min_salary: yearly amount as a whole number, e.g. 120000
- dealbreakers.exclude_title_words: words that rule a job out when they appear in its title
- dealbreakers.exclude_functions: only these values: {functions}
- dealbreakers.exclude_industries, dealbreakers.exclude_companies
- dealbreakers.exclude_description_phrases: phrases that rule a job out when the posting mentions them, e.g. "night shift"
- dealbreakers.exclude_employment_types: only these values: {employment_types}
- dealbreakers.only_locations: the job must be in one of these places
- dealbreakers.only_remote: true if they will only take remote jobs

Use add/remove for list fields and set/clear for single-value fields
(wants.remote, wants.min_salary, dealbreakers.only_remote, dealbreakers.min_salary).
If the message changes nothing, return an empty list of operations.""".format(
    functions=", ".join(get_args(JobFunction)),
    employment_types=", ".join(get_args(EmploymentType)),
)


def extract(llm: LLMClient, current: Preferences, message: str) -> Extraction:
    user = f"Current preferences:\n{current.model_dump_json(indent=1)}\n\nNewest message:\n{message}"
    return llm.structured(system=SYSTEM_PROMPT, user=user, schema=Extraction, purpose="extract_preferences")


# ---------- storage ----------

class ConcurrentUpdate(Exception):
    """Another message for the same profile was saved while this one was being processed."""


def load_profile(conn: psycopg.Connection, profile_id: str) -> tuple[Preferences, int] | None:
    row = conn.execute("SELECT preferences, version FROM profiles WHERE id = %s", (profile_id,)).fetchone()
    if row is None:
        return None
    return Preferences.model_validate(row["preferences"]), row["version"]


def process_message(conn: psycopg.Connection, llm: LLMClient, profile_id: str, message: str) -> dict:
    """Extract operations from `message`, apply them, and store the new state plus the message.

    The LLM call happens *outside* any transaction, so no lock is held while we wait
    for it. The save then uses optimistic locking: it only succeeds if the profile's
    version is still the one we read. If not, ConcurrentUpdate is raised and nothing
    is stored. If the LLM fails, nothing is stored either.
    """
    current, version = load_profile(conn, profile_id) or (Preferences(), 0)
    extraction = extract(llm, current, message)
    updated = apply_operations(current, extraction.operations)
    new_version = version + 1

    with conn.transaction():
        if version == 0:
            saved = conn.execute(
                """INSERT INTO profiles (id, preferences, version) VALUES (%s, %s, 1)
                   ON CONFLICT (id) DO NOTHING RETURNING id""",
                (profile_id, Jsonb(updated.model_dump())),
            ).fetchone()
        else:
            saved = conn.execute(
                """UPDATE profiles SET preferences = %s, version = version + 1, updated_at = now()
                   WHERE id = %s AND version = %s RETURNING id""",
                (Jsonb(updated.model_dump()), profile_id, version),
            ).fetchone()
        if saved is None:
            raise ConcurrentUpdate(f"profile {profile_id} changed while this message was processed; send it again")
        conn.execute(
            """INSERT INTO profile_messages
                   (profile_id, version, content, operations, notes, preferences_after, model, prompt_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                profile_id, new_version, message,
                Jsonb([op.model_dump() for op in extraction.operations]),
                Jsonb(extraction.notes),
                Jsonb(updated.model_dump()),
                llm.model, PROMPT_VERSION,
            ),
        )
    return {
        "profile_id": profile_id,
        "version": new_version,
        "preferences": updated,
        "operations": extraction.operations,
        "notes": extraction.notes,
    }


def list_messages(conn: psycopg.Connection, profile_id: str) -> list[dict]:
    return conn.execute(
        """SELECT version, content, operations, notes, model, prompt_version, created_at
           FROM profile_messages WHERE profile_id = %s ORDER BY version""",
        (profile_id,),
    ).fetchall()
