
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    # Use LLM_PROVIDER=none for tests (no external calls)
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake")
    yield

def test_healthz():
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_suggest_missing_youtube_key(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    client = TestClient(app)
    r = client.post("/suggest", json={"genre": "rock"})
    assert r.status_code == 500

def test_suggest_validation():
    client = TestClient(app)
    # We cannot fully hit youtube in unit tests; just validate schema quickly
    r = client.post("/suggest", json={"genre": ""})
    assert r.status_code == 422
