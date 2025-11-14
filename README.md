
# yt-llm-music-suggester

A production‑minded FastAPI service that suggests YouTube music videos for a given *genre/mood/era/language*.  
It fetches candidates from the **YouTube Data API v3**, then uses an **LLM** (OpenAI by default) to re-rank,
diversify, and annotate picks with short descriptions and tags.

## Features
- FastAPI backend with `/healthz` and `/suggest` endpoints
- YouTube search (category: Music) with robust error handling + retries
- LLM re-ranking + enrichment (explanations, mood/energy tags)
- Rate limiting via `slowapi`
- Structured logging via `loguru`
- Config via environment variables with `.env` support
- Unit tests with `pytest`
- Dockerfile (multi-stage), GitHub Actions CI (lint + tests + build)
- Kubernetes manifests (Deployment, Service, Ingress, ConfigMap, Secret template)
- Ready for cloud deploy (containerized), HTTPS via Ingress + cert-manager (example annotations)
- Minimal cost awareness: maxResults and LLM token budget are configurable

## Quickstart

1) **Create a virtual env and install deps**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) **Set secrets**
Create `.env` from the example and fill in keys:
```bash
cp .env.example .env
# Edit .env with your keys
```

3) **Run locally**
```bash
uvicorn app.main:app --reload --port 8000
```

4) **Try it**
```bash
curl -X POST http://localhost:8000/suggest \
  -H "Content-Type: application/json" \
  -d '{"genre":"lofi", "mood":"chill", "limit":10}'
```

## Configuration

Env vars (place in `.env` or inject in your platform):
- `YOUTUBE_API_KEY` (required): YouTube Data API v3 API key.
- `OPENAI_API_KEY` (required if OPENAI is used): OpenAI API key.
- `LLM_PROVIDER` (default: `openai`): `openai` (default) or `none` (bypass re-rank).
- `OPENAI_MODEL` (default: `gpt-4o-mini`): Any supported chat model.
- `MAX_YT_RESULTS` (default: `25`): YouTube search result size.
- `MAX_SUGGESTIONS` (default: `10`): Final suggestions cap.
- `REQUESTS_TIMEOUT` (default: `10`): Seconds for outbound requests.
- `RATE_LIMIT` (default: `10/minute`): Slowapi rate limit per client IP.

## API

### `POST /suggest`
Body:
```json
{
  "genre": "rock",
  "mood": "energetic",
  "era": "90s",
  "language": "en",
  "limit": 10
}
```
Response:
```json
{
  "suggestions": [
    {
      "title": "...",
      "videoId": "...",
      "channelTitle": "...",
      "url": "https://www.youtube.com/watch?v=...",
      "reason": "short LLM blurb",
      "tags": ["mood", "energy", "subgenre"],
      "publishedAt": "ISO8601"
    }
  ],
  "source_counts": { "youtube_candidates": 25, "llm_ranked": 10 }
}
```

### `GET /healthz`
Liveness probe.

## Docker

```bash
docker build -t yt-llm-music-suggester:latest .
docker run --rm -p 8000:8000 --env-file .env yt-llm-music-suggester:latest
```

## Kubernetes (example)

- Edit `k8s/secret.example.yaml` and create a real secret in your cluster.
- Adjust `k8s/ingress.yaml` host + TLS.
- Apply:
```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
```

## CI (GitHub Actions)
On push/PR: run lint + tests, then (optionally) build and push Docker image (you can wire in your registry).

## Testing
```bash
pytest -q
```

## Notes
- If you want to avoid LLM costs during development, set `LLM_PROVIDER=none`.
- The LLM prompt is designed to avoid duplicates and prefer official videos where possible.
- This project is ready to be extended with a frontend (e.g., small React UI) or auth middleware.
