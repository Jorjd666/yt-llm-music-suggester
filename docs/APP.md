# APP.md – yt-llm-music-suggester Application & API Documentation

This document describes how the **yt-llm-music-suggester** application works from a user and developer perspective: UX flows, core features, and the public API surface (including authentication, request/response shapes, and error semantics).

---

## 1. High-level Overview

### 1.1 What the app does

The app helps a user discover music on YouTube using a **conversation with an LLM** instead of traditional search.

Typical flow:

1. User logs in (JWT-based auth in the frontend).
2. User enters a **natural-language prompt**, e.g.:
   - “Give me 5 upbeat rock tracks like early Foo Fighters, live versions if possible.”
   - “I’m studying, give me chill lofi instrumentals without vocals.”
3. Backend does:
   - Uses an **LLM (via Ollama on the VM)** to understand intent and generate structured queries.
   - Calls the **YouTube Data API** to search for videos (tracks).
   - Applies some filtering and scoring (views, recency, channel, etc).
   - Returns a **curated list of suggestions** with titles, channels, thumbnails, and video URLs.
4. Frontend renders the list, allows the user to:
   - Open YouTube links in a new tab.
   - Refresh suggestions or tweak the prompt.
   - (Optionally) copy a pre-generated YouTube search URL or playlist-like set of links.

The app provides **two main experiences**:

- A **browser UI** (for humans).
- A **JSON API** (for programmatic access and debugging).

---

## 2. User-facing Web Application

### 2.1 Entry points

- **Production UI**:  
  `https://music.<STATIC_IP>.sslip.io/`
- **Staging UI**:  
  `https://music-staging.<STATIC_IP>.sslip.io/`

Behind the scenes:

- Both point to the same FastAPI app running in k3s.
- TLS is handled by **Traefik + cert-manager + Let’s Encrypt**.
- Namespaces:
  - `staging` → `music-staging.*`
  - `music` → `music.*`

### 2.2 Pages & components

**Main UI (single-page web app):**

- **Prompt input**:
  - Free-form text field.
  - Optional advanced parameters (e.g., genre, mood, decade) in UI form fields (or encoded in the prompt).
- **Suggestions list**:
  - Each item shows:
    - Title
    - Channel
    - Duration (if available)
    - Short description
    - YouTube link (`https://www.youtube.com/watch?v=...`)
  - Items may also show:
    - “Reasoning snippet” from the LLM (why this track fits the prompt).
- **System messages / alerts**:
  - Errors (API key issues, rate limit, LLM errors) appear as toast/snackbar-like messages.
  - Loading spinner while waiting for suggestions.

**Auth UX (simple, project-appropriate):**

- Frontend uses a simple **“Bearer token in header”** model for the backend.
- For the capstone context, the token is managed out-of-band:
  - In practice, this is passed from secrets as `API_TOKEN` and used in requests (e.g., via a small auth form or stored in local storage / environment).
  - In a production-ready variant this would be replaced by a proper auth provider (e.g. OAuth2 / OIDC).

---

## 3. Authentication & Security Model

### 3.1 API token

The backend requires a Bearer token for most state-changing or suggestion endpoints:

- **Header:**
  ```http
  Authorization: Bearer <API_TOKEN>
  ```

- `API_TOKEN` is injected into the container via a **Kubernetes Secret**:
  - Namespace: `staging` or `music`
  - Secret name: `yt-llm-secrets`
  - Key: `API_TOKEN`

The app compares the header token against that secret and returns `401` if invalid/missing.

### 3.2 Why this model

For the capstone project, this model is enough to show:

- **Authentication** is enforced on the API.
- Secrets are stored in **Kubernetes Secrets**, **not** in code.
- Calls from the UI must include a valid token.

A real production deployment would typically integrate:

- OAuth2 / OIDC (e.g., Google, GitHub, or an internal IdP).
- Proper refresh tokens, user identities, roles, etc.

---

## 4. API Overview

The backend is built with **FastAPI** and exposes a small set of structured routes.

> NOTE: Some path details may be slightly different depending on code evolution, but this is the intended contract.

### 4.1 Health & meta endpoints

#### `GET /healthz`

- **Auth**: none
- **Purpose**: quick Kubernetes / CI / uptime check.
- **Response (200)**:
  ```json
  {
    "status": "ok",
    "uptime_seconds": 1234.56,
    "version": "sha-or-semver",
    "llm_provider": "openai",
    "yt_integration": "ok"
  }
  ```

If something critical is wrong (e.g., cannot reach Ollama or YouTube), it may return `503` with diagnostic info.

#### `GET /metrics`

- **Auth**: none (scraped by Prometheus inside the cluster).
- **Purpose**: expose Prometheus metrics.
- **Format**: Prometheus text exposition (counters, histograms, gauges), including:
  - Request count / latency for suggestion endpoints.
  - LLM call count / latency.
  - YouTube API call metrics.
  - Error counters.

#### `GET /` (root)

- **Auth**: usually none for the HTML page itself.
- **Purpose**: serve the main frontend (either templated or SPA bundle).

---

### 4.2 Suggestion API

Core API for obtaining music suggestions.

#### `POST /api/v1/suggestions`

**Auth required**: `Authorization: Bearer <API_TOKEN>`

**Request body (JSON):**

```json
{
  "prompt": "5 upbeat rock tracks similar to early Foo Fighters",
  "max_results": 10,
  "filters": {
    "max_duration_minutes": 8,
    "only_music_videos": true,
    "exclude_live": false,
    "min_views": 500000
  }
}
```

- `prompt` (string, required): natural language description of what the user wants.
- `max_results` (int, optional): default ~10.
- `filters` (object, optional):
  - `max_duration_minutes` (int)
  - `only_music_videos` (bool)
  - `exclude_live` (bool)
  - `min_views` (int)
  - etc. (whatever is supported in the actual implementation).

**How it works internally:**

1. **LLM planner** (Ollama via OpenAI-compatible API):
   - Given `prompt` (+ filters), generate a structured “search intent”, for example:
     ```json
     {
       "query": "upbeat rock similar to foo fighters",
       "mood": "energetic",
       "era": "90s-2000s",
       "num_tracks": 10
     }
     ```
   - The app uses `OPENAI_BASE_URL = "http://<VM_IP>:11434/v1"` and model `llama3.2:3b` as configured in `yt-llm-config` ConfigMap.

2. **YouTube API**:
   - Use the planned query to call YouTube Data API (v3) **search** and/or **videos** endpoints.
   - Limit by `max_results` and filters.

3. **Ranking/selection**:
   - Filter out obviously bad matches (very short, non-music content).
   - Rank by a combination of relevance, views, recency.

4. **Response**:
   - Return a curated list with a stable JSON shape.

**Success response (200):**

```json
{
  "prompt": "5 upbeat rock tracks similar to early Foo Fighters",
  "model": "llama3.2:3b",
  "total_found": 15,
  "returned": 5,
  "items": [
    {
      "title": "Everlong (Official HD Video)",
      "channel": "Foo Fighters",
      "yt_video_id": "eBG7P-K-r1Y",
      "url": "https://www.youtube.com/watch?v=eBG7P-K-r1Y",
      "duration_seconds": 250,
      "views": 450000000,
      "reason": "Classic upbeat Foo Fighters track with a similar energy."
    },
    {
      "title": "My Hero (Official Video)",
      "channel": "Foo Fighters",
      "yt_video_id": "EqWRaAF6_WY",
      "url": "https://www.youtube.com/watch?v=EqWRaAF6_WY",
      "duration_seconds": 260,
      "views": 300000000,
      "reason": "Anthemic rock track, similar tempo and feel."
    }
  ]
}
```

#### `GET /api/v1/suggestions/example` (optional helper)

- Returns a static or semi-static example payload for documentation / testing.
- Useful as a quick JSON demo without hitting the LLM or YouTube.

---

### 4.3 Auth / token verification endpoint (optional)

Depending on how you wired it in code, there may be an endpoint like:

#### `GET /api/v1/auth/check`

- **Auth required**: `Authorization: Bearer <API_TOKEN>`
- Returns 200 if the token is valid, e.g.:
  ```json
  { "status": "ok", "token_valid": true }
  ```

This is handy for frontend to verify the token before making expensive calls.

---

## 5. Error Handling & Status Codes

The app follows a simple, predictable error shape.

### 5.1 Standard error payload

On errors, backend typically returns:

```json
{
  "error": {
    "type": "string_machine_readable",
    "message": "Human readable explanation",
    "details": { "anything": "useful" }
  }
}
```

### 5.2 Common status codes

- `200 OK` – success.
- `400 Bad Request` – invalid input (missing `prompt`, bad filters, etc).
- `401 Unauthorized` – missing or invalid Bearer token.
- `429 Too Many Requests` – app-level rate limit is hit (e.g., too many requests per minute).
- `500 Internal Server Error` – unexpected errors (uncaught exceptions).
- `502 / 503` – upstream issues (YouTube or Ollama not reachable, depending on how you map them).

### 5.3 Rate limiting & LLM cost control

Rate limit configuration is stored in the ConfigMap:

```yaml
RATE_LIMIT: "10/minute"
```

Conceptually:

- The app can maintain an in-memory or Redis-based counter keyed by token/IP.
- If too many requests occur within the window:
  - Return `429` with a helpful error.
- This is part of demonstrating **cost management** even though Ollama is local and “free” in your setup.

---

## 6. LLM Integration Details (Ollama via OpenAI API)

### 6.1 Config

In Kubernetes, ConfigMap `yt-llm-config` defines:

```yaml
LLM_PROVIDER: "openai"
OPENAI_BASE_URL: "http://<VM_INTERNAL_IP>:11434/v1"
OPENAI_MODEL: "llama3.2:3b"
```

In the Python code, the app treats this as an OpenAI-compatible provider:

- Uses the **OpenAI client** but points it to `OPENAI_BASE_URL`.
- Uses the configured `OPENAI_MODEL` when calling chat/completions.

### 6.2 Why this design

- You can switch between:
  - Real OpenAI (cloud)  
  - Ollama (local)  
  just by changing env/config.
- For the capstone, we’re demonstrating **pluggable LLM providers** and **cost control**.

---

## 7. Logging & Observability from App Perspective

Even though monitoring is detailed in `MONITORING.md`, here’s how the app itself contributes:

- Structured logs (JSON or key-value) on each request:
  - Route.
  - Status code.
  - Latency.
  - Error type (if any).
  - LLM + YouTube call counts per request.

- Prometheus metrics exposed at `/metrics`:
  - `yt_llm_requests_total{route="/api/v1/suggestions",status="200"}`
  - `yt_llm_request_latency_seconds_bucket{...}`
  - `yt_llm_llm_calls_total`
  - `yt_llm_youtube_calls_total`
  - etc.

These are then visualised via Grafana and used by Alertmanager for critical alerts.

---

## 8. Local Development vs Cloud Deployment

### 8.1 Local dev

Typical pattern:

1. Run backend locally with `uvicorn` or `fastapi dev`.
2. Use local `.env`:
   - `LLM_PROVIDER=none` (to avoid calling external LLMs).
   - Or point to a local Ollama instance if you run one on your laptop.
3. Use fake or limited YouTube keys and stubbed tests.

### 8.2 Cloud deployment (GCP + k3s)

- All configuration is injected via:
  - **ConfigMap** (`yt-llm-config`).
  - **Secrets** (`yt-llm-secrets`).
- CI/CD:
  - Builds & pushes Docker image → GHCR.
  - Terraform ensures the VM + static IP + firewall.
  - Ansible provisions k3s, Ollama, cert-manager, kube-prometheus-stack, and the app.
  - GitHub Actions `deploy-staging` & `deploy-prod` jobs run `ansible-playbook` with different `K8S_NS` and hosts.

---

## 9. How to Call the API Manually (Examples)

### 9.1 From your laptop (curl)

```bash
API_TOKEN="your-token-here"
HOST="music.<YOUR_STATIC_IP>.sslip.io"

curl -X POST "https://${HOST}/api/v1/suggestions"   -H "Content-Type: application/json"   -H "Authorization: Bearer ${API_TOKEN}"   -d '{
    "prompt": "Give me 5 chill lofi beats to study to",
    "max_results": 5
  }'
```

### 9.2 From a simple Python script

```python
import os
import requests

API_TOKEN = os.getenv("API_TOKEN")
HOST = os.getenv("HOST", "music.<YOUR_STATIC_IP>.sslip.io")

payload = {
    "prompt": "Rock songs like early Muse but a bit more electronic",
    "max_results": 5,
}

resp = requests.post(
    f"https://{HOST}/api/v1/suggestions",
    headers={
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=30,
)

resp.raise_for_status()
data = resp.json()
for item in data.get("items", []):
    print(f"- {item['title']} → {item['url']}")
```

---

## 10. Future Enhancements

Some natural next steps that build on this foundation:

- Full user identity & playlists:
  - Persist user accounts and stored “favorite” suggestion sets.
- Richer filters:
  - BPM range, mood classification, language constraints.
- More providers:
  - Support multiple LLMs (OpenAI, Claude, Gemini) behind a unified interface.
- Better auth:
  - Replace API tokens with an actual login flow (OAuth2, OIDC).

For the capstone, the current design already demonstrates:

- A usable web app.
- A clean JSON API with authentication.
- Pluggable LLM backend (now using Ollama in the cloud).
- Integration with YouTube and full cloud-native deployment.