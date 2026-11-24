"""The web frontend generates its TypeScript types from /openapi.json, so the schema must
describe every response exactly: no untyped objects, and every error status a route can return."""

import json
from pathlib import Path

from matchwise.api import app

SCHEMA = app.openapi()
FRONTEND_SNAPSHOT = Path(__file__).resolve().parent.parent / "web" / "openapi.json"


def json_schema(path: str, method: str, status: str) -> dict:
    return SCHEMA["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]


def is_typed(schema: dict) -> bool:
    """A reference to a named model, or an array of them; never a bare `object`."""
    if "$ref" in schema:
        return True
    return schema.get("type") == "array" and "$ref" in schema.get("items", {})


def test_every_success_response_is_a_named_model():
    for path, operations in SCHEMA["paths"].items():
        for method, operation in operations.items():
            schema = json_schema(path, method, "200")
            assert is_typed(schema), f"{method.upper()} {path} returns an untyped {schema}"


def test_error_responses_are_declared():
    error = {"$ref": "#/components/schemas/ErrorOut"}
    expected = {
        ("/profiles/{profile_id}", "get"): {"404"},
        ("/profiles/{profile_id}/messages", "get"): {"404"},
        ("/profiles/{profile_id}/messages", "post"): {"409", "502", "503"},
        ("/profiles/{profile_id}/matches", "get"): {"404", "503"},
        ("/profiles/{profile_id}/chat", "post"): {"503"},
        ("/jobs/{job_id}", "get"): {"404"},
    }
    for (path, method), codes in expected.items():
        for code in codes:
            assert json_schema(path, method, code) == error, f"{method.upper()} {path} {code}"


def test_matches_422_can_be_a_validation_list_or_a_message():
    options = json_schema("/profiles/{profile_id}/matches", "get", "422")["anyOf"]
    assert {o["$ref"].rsplit("/", 1)[1] for o in options} == {"HTTPValidationError", "ErrorOut"}
    # Both referenced models must exist, or the generated types would point at nothing.
    assert {"HTTPValidationError", "ErrorOut"} <= SCHEMA["components"]["schemas"].keys()


def test_chat_history_types_its_tool_calls():
    message = SCHEMA["components"]["schemas"]["ChatMessageOut"]["properties"]
    assert message["role"]["enum"] == ["user", "assistant", "tool"]
    assert {"$ref": "#/components/schemas/StoredToolCall"} == message["tool_calls"]["anyOf"][0]["items"]
    assert "tool_call_id" in message


def test_limit_check_lists_its_values():
    limit_check = SCHEMA["components"]["schemas"]["MatchOut"]["properties"]["limit_check"]
    assert limit_check["anyOf"][0]["enum"] == ["passed", "skipped", "no limits"]


def test_the_frontend_types_were_generated_from_this_schema():
    """web/openapi.json is what the frontend's TypeScript types are generated from."""
    snapshot = json.loads(FRONTEND_SNAPSHOT.read_text())
    assert snapshot == SCHEMA, "The API changed: with it running, run `npm run api:sync` in web/"
