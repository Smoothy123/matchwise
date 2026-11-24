import pytest
from fastapi.testclient import TestClient

from conftest import scripted_llm
from matchwise.api import app, get_llm
from test_preferences import FIRST, SECOND


@pytest.fixture
def make_client(db_url, monkeypatch):
    """A TestClient whose LLM gives the scripted replies."""
    monkeypatch.setenv("DATABASE_URL", db_url)
    clients = []

    def make(*replies):
        llm = scripted_llm(*replies)
        app.dependency_overrides[get_llm] = lambda: llm
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)
    app.dependency_overrides.clear()


def test_post_message_then_read_profile_and_history(conn, make_client):
    client = make_client(FIRST, SECOND)
    first = client.post("/profiles/ana/messages", json={"message": "Backend work in Austin, never sales"})
    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert first.json()["preferences"]["dealbreakers"]["exclude_functions"] == ["Sales"]
    assert first.json()["operations"][0] == {
        "op": "add", "field": "wants.roles", "value": "backend engineer", "evidence": "e"}

    client.post("/profiles/ana/messages", json={"message": "Actually Denver"})
    profile = client.get("/profiles/ana").json()
    assert profile["version"] == 2 and profile["preferences"]["wants"]["locations"] == ["Denver, CO"]
    history = client.get("/profiles/ana/messages").json()
    assert [h["content"] for h in history] == ["Backend work in Austin, never sales", "Actually Denver"]


def test_unknown_profile_is_404(conn, make_client):
    client = make_client()
    assert client.get("/profiles/nobody").status_code == 404
    assert client.get("/profiles/nobody/messages").status_code == 404


@pytest.mark.parametrize("path, body", [
    ("/profiles/bad.id/messages", {"message": "hi"}),      # id pattern
    ("/profiles/ana/messages", {"message": "   "}),        # empty after trimming
    ("/profiles/ana/messages", {"message": "x" * 2001}),   # too long
    ("/profiles/ana/messages", {}),
])
def test_bad_input_is_422(conn, make_client, path, body):
    assert make_client().post(path, json=body).status_code == 422


def test_invalid_llm_output_is_502_and_changes_nothing(conn, make_client):
    client = make_client("bad", "bad", "bad")
    response = client.post("/profiles/ana/messages", json={"message": "Backend work"})
    assert response.status_code == 502
    assert "nothing was changed" in response.json()["detail"]
    assert client.get("/profiles/ana").status_code == 404


def test_without_an_llm_key_messages_are_503(conn, db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("LLM_API_KEY", "")
    with TestClient(app) as client:
        response = client.post("/profiles/ana/messages", json={"message": "Backend work"})
        assert response.status_code == 503
        assert client.get("/health").json()["llm_configured"] is False
