import pytest
from fastapi.testclient import TestClient

from matchwise.api import app
from matchwise.config import DEFAULT_CORS_ORIGINS, cors_origins

OTHER_ORIGIN = "https://not-allowed.example"


def test_origins_default_to_the_local_frontend(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins() == DEFAULT_CORS_ORIGINS.split(",")


def test_origins_are_trimmed_and_an_empty_value_means_none():
    assert cors_origins(" https://a.example/ , http://localhost:5173,, ") == [
        "https://a.example", "http://localhost:5173"]
    assert cors_origins("") == []


@pytest.mark.parametrize("bad", ["localhost:5173", "https://a.example/app", "ftp://a.example", "https://"])
def test_a_mistyped_origin_stops_startup(bad):
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        cors_origins(bad)


@pytest.fixture
def allowed_origin() -> str:
    origins = cors_origins()  # what the app was built with
    if not origins:
        pytest.skip("CORS_ORIGINS is set to none")
    return origins[0]


def preflight(client: TestClient, origin: str):
    return client.options("/profiles/ana/chat", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })


def test_preflight_from_an_allowed_origin_is_answered(allowed_origin):
    response = preflight(TestClient(app), allowed_origin)  # no DB needed: the middleware answers
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == allowed_origin
    assert "POST" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-max-age"] == "600"
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_from_another_origin_is_refused():
    response = preflight(TestClient(app), OTHER_ORIGIN)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_responses_carry_the_header_only_for_allowed_origins(db_url, monkeypatch, allowed_origin):
    monkeypatch.setenv("DATABASE_URL", db_url)
    with TestClient(app) as client:
        allowed = client.get("/health", headers={"Origin": allowed_origin})
        other = client.get("/health", headers={"Origin": OTHER_ORIGIN})
        missing = client.get("/profiles/nobody", headers={"Origin": allowed_origin})
    assert allowed.headers["access-control-allow-origin"] == allowed_origin
    assert "access-control-allow-origin" not in other.headers
    # Error responses need it too, or the browser hides the status and the frontend can't show it.
    assert missing.status_code == 404
    assert missing.headers["access-control-allow-origin"] == allowed_origin
