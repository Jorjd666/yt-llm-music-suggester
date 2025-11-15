# yt-llm-music-suggester

A production-minded **FastAPI** service that suggests YouTube music videos for a given *genre/mood/era/language*.
It fetches candidates from the **YouTube Data API v3**, then uses an **LLM** (OpenAI **or** a local Ollama model via an OpenAI-compatible API) to re-rank, diversify, and annotate picks with short descriptions and tags.

---

## Features

- **FastAPI** backend: `/healthz`, `/suggest`, `/metrics` (Prometheus)
- **Tiny browser UI** at `/` (no build tools): inputs + thumbnail cards with links & reasons
- **YouTube search (Music category)** with retries and robust error handling
- **LLM re-ranking + enrichment** (OpenAI cloud or local **Ollama** with `OPENAI_BASE_URL`)
- **Rate limiting** via `slowapi` (e.g., `10/minute`)
- **Structured logging** with `loguru`
- **12-factor config** via env vars and `.env`
- **Unit tests** with `pytest`
- **Docker** multi-stage build
- **GitHub Actions** CI: tests + **multi-arch** image (linux/amd64 & linux/arm64) pushed to GHCR
- **Kubernetes**: Deployment, Service, Ingress (Traefik), liveness/readiness, resource limits/requests
- **Monitoring**: `/metrics` for Prometheus; `/healthz` for probes
- **Cloud-ready**: Terraform (GCP VM + firewall + static IP) & Ansible (K3s install + rollout)
- **Cost awareness**: throttle YouTube results & LLM budget; can disable LLM (`LLM_PROVIDER=none`)

---

## Architecture (Mermaid)

```mermaid
flowchart LR
  subgraph Client
    UI[Browser UI @ /] -->|POST /suggest| API
    SWAGGER[/Swagger UI @ /docs/]
  end

  subgraph Service[FastAPI Service]
    API[FastAPI\n/healthz /suggest /metrics]
    YT[YouTube Client]
    LLM[LLM Client\n(OpenAI-compatible)]
    LOG[Structured Logging]
    RL[Rate Limit (slowapi)]
  end

  API --> RL
  API --> YT
  API --> LLM
  API --> LOG
  API -->|/metrics| PROM[Prometheus Scrape]

  subgraph External
    YTAPI[(YouTube Data API v3)]
    OAI[(OpenAI / Ollama\nOpenAI-compatible API)]
    GHCR[(GHCR Docker Registry)]
  end

  YT -->|candidates| YTAPI
  LLM -->|rerank| OAI

  subgraph Platform
    K8s[Deployment + Service + Ingress]
    CI[GitHub Actions CI]
  end

  CI --> GHCR
  GHCR --> K8s
  K8s --> Service
  PROM[(Prometheus)] -->|scrape| API
```

---

## Requirements

- Python 3.11+
- **YouTube Data API v3** key
- One of:
  - **OpenAI** API key, or
  - **Ollama** running locally (OpenAI-compatible) with a pulled model (e.g. `llama3.1:8b`)

---

## Quickstart (Local)

1) **Create virtualenv & install dependencies (using `uv venv`)**
```bash
uv venv
source .venv/bin/activate          # uv creates .venv by default
pip install -r requirements.txt
```

2) **Configure environment**
```bash
cp .env.example .env
# Edit .env with your keys and options
# Required: YOUTUBE_API_KEY
# If using OpenAI cloud:
#   LLM_PROVIDER=openai
#   OPENAI_API_KEY=sk-...
# If using local Ollama (OpenAI-compatible API):
#   LLM_PROVIDER=openai
#   OPENAI_BASE_URL=http://localhost:11434/v1
#   OPENAI_API_KEY=ollama
#   OPENAI_MODEL=llama3.1:8b
# (optional) API_TOKEN=<random>  # if set, /suggest requires Bearer token
```

> **Ollama setup (optional)**  
> Install Ollama, then:
> ```bash
> ollama serve
> ollama pull llama3.1:8b   # base model (not -instruct)
> ```
> Update `.env` as shown above.

3) **Run the API**
```bash
uvicorn app.main:app --reload --port 8020
```

4) **Try it**
```bash
# Health & metrics
curl -sS http://localhost:8020/healthz
curl -sS http://localhost:8020/metrics | head

# Suggestions (with optional Bearer token if API_TOKEN is set)
curl -sS -X POST http://localhost:8020/suggest \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"genre":"lofi","mood":"chill","limit":3}' | jq .
```

5) **Open the tiny UI**  
Visit `http://localhost:8020/` in a browser.  
(If `API_TOKEN` is set, the page will prompt once and store it in `localStorage`.)

6) **Swagger / OpenAPI client**  
- **Interactive docs (Swagger UI):** `http://localhost:8020/docs`  
  You can execute the `POST /suggest` call right in the browser.  
  Click **Authorize** and paste `Bearer <API_TOKEN>` if you enabled the token.  
- **OpenAPI JSON:** `http://localhost:8020/openapi.json`  
  Import this into Postman/Insomnia/etc. to generate a client automatically.

---

## Configuration

All options can be set via environment variables (in `.env` locally, or injected in your platform):

| Variable | Required | Default | Description |
|---|---|---|---|
| `YOUTUBE_API_KEY` | **Yes** | — | YouTube Data API v3 key |
| `LLM_PROVIDER` | No | `openai` | `openai` or `none` (bypass LLM re-rank) |
| `OPENAI_API_KEY` | If using OpenAI cloud | — | OpenAI key |
| `OPENAI_BASE_URL` | No | — | Override OpenAI base URL (e.g., `http://localhost:11434/v1` for Ollama) |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | OpenAI/Ollama model name (e.g., `llama3.1:8b`) |
| `MAX_YT_RESULTS` | No | `25` | Size of the YouTube candidate set |
| `MAX_SUGGESTIONS` | No | `10` | Final number of suggestions returned |
| `REQUESTS_TIMEOUT` | No | `10` | Outbound HTTP timeout (seconds) |
| `RATE_LIMIT` | No | `10/minute` | Per-IP rate limit for `/suggest` |
| `API_TOKEN` | No | — | If set, `/suggest` requires `Authorization: Bearer <token>` |

---

## API

### `POST /suggest`
**Request**
```json
{
  "genre": "rock",
  "mood": "energetic",
  "era": "90s",
  "language": "en",
  "limit": 10
}
```

**Response**
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

### `GET /metrics`
Prometheus metrics exposed by `prometheus_fastapi_instrumentator`.

### `GET /docs`
Swagger UI (interactive) — run API calls from your browser.

---

## Docker

Build & run locally:
```bash
docker build -t yt-llm-music-suggester:latest .
docker run --rm \
  -p 8020:8000 \  # map local 8020 -> container 8000
  --env-file .env \
  yt-llm-music-suggester:latest
```
> ✅ Keeping `8020:8000` is correct here because the container listens on **8000**, and we expose it on **localhost:8020**.

Multi-arch image is published by CI to GHCR:
```
ghcr.io/<owner>/yt-llm-music-suggester:latest
```

---

## Kubernetes (example)

**Prereqs**: a cluster (Docker Desktop k8s / k3s / GKE), and an ingress (e.g., Traefik or NGINX).  
We ship example manifests in `k8s/`.

1) **Create ConfigMap & Secret** (or manage secrets your way)
```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.example.yaml  # edit or replace with your real Secret
```

2) **Deploy service**
```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

3) **Ingress**
- With **Traefik** + `sslip.io` host (e.g., `music.<EXTERNAL-IP>.sslip.io`):
```bash
kubectl apply -f k8s/ingress.yaml
```

**Why `sslip.io`?**  
`sslip.io` is a free wildcard DNS service that converts an IP address into a valid hostname (e.g., `34.61.9.73.sslip.io`).  
This lets you test Ingress hosts **without buying a domain** or managing DNS records.  
- Works great for demos/POCs and local/k3s clusters.  
- When you’re ready for production, switch to your real domain and add TLS via cert‑manager + Let’s Encrypt.

4) **Rollout / updates**
- **Pin by digest** (recommended on Apple Silicon):
```bash
kubectl -n music set image deploy/yt-llm \
  api=ghcr.io/<owner>/yt-llm-music-suggester@sha256:<arm64_or_amd64_digest>
kubectl -n music rollout status deploy/yt-llm
```
- Or use `:latest` and set `imagePullPolicy: Always` for the container.

---

## Monitoring

- `/metrics` endpoint ready for Prometheus scraping.
- `/healthz` wired as liveness/readiness probes in the Deployment.
- Add a ServiceMonitor (if running the Prometheus Operator) and a Grafana dashboard if desired.

---

## CI (GitHub Actions)

- **build-test** job: installs deps, caches pip, runs tests.
- **docker** job: builds **multi-arch** image (amd64 & arm64) using Buildx + QEMU, pushes to GHCR with:
  - `:latest`
  - `:${{ github.sha }}`
- Workflow permissions:
  - `contents: read`, `packages: write` (for GHCR push)

> Optional future CD: patch the deployment to the `${{ github.sha }}` tag automatically after a successful build.

---

## Terraform & Ansible (GCP)

- **Terraform** (`infra/terraform`): minimal GCE VM + firewall + static IP (stop resources when not in use to control costs).
- **Ansible** (`infra/ansible`): installs **k3s** on the VM, waits for node ready, applies app manifests & ingress.  
  If the cluster is slow to serve the OpenAPI schema, `--validate=false` can help apply manifests reliably.

> To save money, you can pause cloud infra. We used it to verify a real cloud path, but local k8s + GHCR is enough for the demo.

---

## Security

- No secrets in the repo; use `.env` locally and **Kubernetes Secrets/CI secrets** in environments.
- Optional `API_TOKEN` enforces Bearer auth on `/suggest`.
- Container uses minimal base (Python slim) via multi-stage build.

---

## Testing

```bash
pytest -q
```

---

## Troubleshooting

- **429 / insufficient_quota** from OpenAI: set `LLM_PROVIDER=none` for demos, or use local **Ollama** with `OPENAI_BASE_URL`.
- **K8s doesn’t pull latest image**: If using `:latest`, add `imagePullPolicy: Always`, or pin by **digest**.
- **Image platform mismatch** on Apple Silicon: ensure the registry has **arm64** manifest (CI pushes multi-arch).
- **Ingress 404**: Confirm ingress class/annotations match your controller (Traefik vs NGINX). Verify `host` + DNS (or `sslip.io` domain).

---

## Demo Script (2–3 minutes)

1. Open `http://localhost:8020/` (or your Ingress host).
2. Enter: `genre=lofi`, `mood=chill`, `limit=5` → **Suggest**.
3. Show result cards: titles, thumbnails, channels, “reason”, links open YouTube.
4. `curl` `/healthz` and `/metrics` to demo readiness & observability.
5. Mention rate limiting, token auth, CI pipeline, and k8s rollout with digest pinning.

---

## Project Checklist Status

- **Web app (FE/BE)** ✅ (FastAPI + tiny UI)
- **Backend API** ✅ (`/healthz`, `/suggest`, `/metrics` + Swagger `/docs`)
- **Database** ➖ (not required)
- **Auth** ✅ (optional Bearer token)
- **LLM integration** ✅ (OpenAI or Ollama; using model `llama3.1:8b` in local mode)
- **Error handling** ✅ (retries/fallbacks)
- **Rate limiting & costs** ✅
- **Public accessibility** ✅ (Ingress + `sslip.io`)
- **HTTPS** 🟡 (cert-manager template ready; not enabled)
- **Domain/DNS** 🟡 (`sslip.io` used; custom domain optional)
- **Code quality** ✅
- **Tests** ✅
- **Git workflow / PRs** ✅
- **Docker** ✅ (multi-stage)
- **Kubernetes** ✅ (manifests + probes + resources)
- **IaC (Terraform)** ✅ (GCE VM + firewall + IP)
- **Ansible** ✅ (K3s install & apply)
- **CI/CD** ✅ (CI builds/pushes; CD manual via kubectl; can automate)
- **Rollback** ✅ (`kubectl rollout undo`)
- **Observability** ✅ (metrics + healthz; dashboards optional)
- **Security practices** ✅ (secrets handling, minimal image)
- **Docs** ✅ (this README)
- **Presentation** 🟡 (slides optional; demo script above)

---

## License

MIT (or your preferred license)
