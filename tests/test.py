import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

@pytest.fixture(autouse=True)
def force_local_defaults(monkeypatch):
    # Make tests deterministic and offline by default
    monkeypatch.setattr(settings, "LLM_PROVIDER", "none", raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None, raising=False)
    monkeypatch.setattr(settings, "YOUTUBE_API_KEY", "fake", raising=False)
    yield

def test_healthz():
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_suggest_missing_youtube_key(monkeypatch):
    # Override the already-imported settings object
    monkeypatch.setattr(settings, "YOUTUBE_API_KEY", "", raising=False)
    client = TestClient(app)
    r = client.post("/suggest", json={"genre": "rock"})
    assert r.status_code == 500

def test_suggest_validation():
    client = TestClient(app)
    r = client.post("/suggest", json={"genre": ""})
    assert r.status_code == 422
