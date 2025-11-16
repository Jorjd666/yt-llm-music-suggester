import json
import pytest
from starlette.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_suggest_returns_items(monkeypatch, client):
    # Patch the function as referenced inside app.main
    import app.main as main

    async def fake_search_music_videos(query, max_results, timeout):
        return {
            "items": [
                {
                    "id": {"videoId": "vid1"},
                    "snippet": {
                        "title": "Song A",
                        "channelTitle": "Ch1",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    },
                },
                {
                    "id": {"videoId": "vid2"},
                    "snippet": {
                        "title": "Song B",
                        "channelTitle": "Ch2",
                        "publishedAt": "2024-01-02T00:00:00Z",
                    },
                },
            ]
        }

    monkeypatch.setattr(main, "search_music_videos", fake_search_music_videos)

    r = client.post(
        "/suggest",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"genre": "lofi", "mood": "chill", "limit": 2}),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["suggestions"]) == 2
