# tests/e2e/test_suggest_live.py
import os
import json
import pytest
import requests

HOST = os.getenv("E2E_HOST")  # e.g. https://music.34.x.x.x.sslip.io
API_TOKEN = os.getenv("E2E_API_TOKEN")

skip_msg = "Set E2E_HOST & E2E_API_TOKEN to run live E2E."
pytestmark = pytest.mark.skipif(not (HOST and API_TOKEN), reason=skip_msg)

def test_live_healthz():
    r = requests.get(f"{HOST}/healthz", timeout=15, verify=True)
    assert r.status_code == 200

def test_live_suggest():
    r = requests.post(
        f"{HOST}/suggest",
        headers={"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"},
        data=json.dumps({"genre": "lofi", "mood": "chill", "limit": 3}),
        timeout=30,
        verify=True,
    )
    assert r.status_code == 200, r.text
    assert "suggestions" in r.json()
