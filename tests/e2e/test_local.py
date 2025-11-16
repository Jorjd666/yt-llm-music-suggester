# tests/integration/test_suggest_local.py
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "testtoken")
    monkeypatch.setenv("YOUTUBE_API_KEY", "dummy")  # not used because we stub search
    monkeypatch.setenv("LLM_PROVIDER", "none")      # bypass LLM in this test

@pytest.fixture
def client():
    return TestClient(app)

def test_suggest_returns_items(monkeypatch, client):
    # Stub YouTube client to avoid network
    from app import youtube_client as yc

    async def fake_search_music_videos(query, max_results, timeout):
        return {
            "items": [
                {"id": {"videoId": "vid1"}, "snippet": {"title": "Song A", "channelTitle": "Ch1", "publishedAt": "2024-01-01T00:00:00Z"}},
                {"id": {"videoId": "vid2"}, "snippet": {"title": "Song B", "channelTitle": "Ch2", "publishedAt": "2024-01-02T00:00:00Z"}},
            ]
        }
    monkeypatch.setattr(yc, "search_music_videos", fake_search_music_videos)

    r = client.post(
        "/suggest",
        headers={"Authorization": "Bearer testtoken", "Content-Type": "application/json"},
        data=json.dumps({"genre": "lofi", "mood": "chill", "limit": 2}),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "suggestions" in data and len(data["suggestions"]) == 2
