# Architecture Overview

## 1. Project Summary

**YT LLM Music Suggester** is a full-stack, LLM-powered web application that helps users discover YouTube music based on mood/genre prompts. It combines:

- A web UI for entering prompts and viewing ranked YouTube suggestions.
- A FastAPI backend that orchestrates YouTube search & LLM reranking.
- A self-hosted LLM (Ollama) running on the same GCP VM.
- A lightweight Kubernetes cluster (k3s) with automated CI/CD, TLS, and monitoring.

The goal is to demonstrate **production-style architecture**: containers, Kubernetes, IaC, CI/CD, monitoring, and security-minded configuration.

---

## 2. High-Level Architecture

```text
+------------------------+          +-------------------------+
|        Browser         |  HTTPS   |   Traefik Ingress (k3s) |
|  (User's web client)   +--------->+  music*.sslip.io       |
+-----------+------------+          +-----------+-------------+
            |                                    |
            |                                    v
            |                       +---------------------------+
            |                       |  yt-llm Service (ClusterIP|
            |                       |  + Deployment / Pods)     |
            |                       |  FastAPI + Frontend       |
            |                       +-----+---------------------+
            |                             |
            |                             | HTTP (internal)
            |                             v
            |                 +---------------------------+
            |                 |  YouTube Data API (cloud)|
            |                 +---------------------------+
            |
            |                             HTTP (OpenAI-compatible)
            |                             to VM host IP:11434
            |                             via k8s node network
            |                             (no public exposure)
            |                             v
            |                 +---------------------------+
            |                 |     Ollama (VM host)      |
            |                 |  llama3.2:3b LLM model    |
            |                 +---------------------------+
            |
            |                    Metrics
            |   +-----------------------------------------------+
            |   |                                               v
            |   |       +--------------------------+   +--------------------+
            |   +------>+  Prometheus (k8s)        |   |   Grafana (k8s)   |
            |           |  + Alertmanager          |   |  Dashboards       |
            |           +--------------------------+   +--------------------+
            |
            |  Logs via k3s / container runtime (not centralized yet)
```

---

## 3. Components

### 3.1 Frontend (Web UI)

- Served as static assets by the FastAPI container.
- Main features:
  - Inputs for genre/mood, optional filters (era, language, number of suggestions).
  - Text field for **API token**.
  - “Suggest” button that calls the backend.
  - Error messages surfaced directly in the UI.

**Key responsibilities**

- Collect user input.
- Send authenticated requests to the backend (`Authorization: Bearer <token>`).
- Display ranked YouTube results returned by the API.

---

### 3.2 Backend (FastAPI)

- Runs inside the `yt-llm` Kubernetes Deployment.
- Exposes several HTTP endpoints:

  - `GET /healthz` – health check used by:
    - k8s readiness & liveness probes
    - CI/CD health checks after deploy
  - `POST /suggest` – main business endpoint:
    - Accepts prompt + filters from UI.
    - Validates **API token**.
    - Calls YouTube API for candidate videos.
    - Calls Ollama (via OpenAI-compatible client) to rerank candidates.
    - Returns ranked list to the frontend.
  - `GET /metrics` – Prometheus metrics endpoint.
  - (FastAPI also exposes `/docs` & `/openapi.json` for API documentation.)

**Responsibilities**

- Auth: simple bearer token check (`API_TOKEN`).
- Coordination between external APIs:
  - YouTube Data API for raw results.
  - Ollama (LLM) for semantic ranking.
- Applying rate limiting, timeouts & error handling.
- Emitting metrics for Prometheus (e.g. request counts, latencies, errors).

---

### 3.3 LLM Integration (Ollama on VM)

Instead of calling a paid cloud LLM (OpenAI, Claude, Gemini), this project uses **Ollama** running on the GCP VM:

- Ollama is installed and managed by Ansible on the VM host:
  - Systemd service: `ollama.service`.
  - Config tuned for a small cloud VM (2 vCPU / 4GB):
    - Reduced context window.
    - Limited number of concurrent models.
- The model pulled & used in production:
  - `llama3.2:3b` (smaller, resource-friendly model).
- Ollama exposes an **OpenAI-compatible HTTP API** on the host:
  - `http://<vm-internal-ip>:11434/v1`
- The FastAPI backend talks to it like a normal OpenAI client:

  ```text
  OPENAI_BASE_URL = "http://<vm-ip>:11434/v1"
  OPENAI_MODEL    = "llama3.2:3b"
  OPENAI_API_KEY  = ""  (unused for local Ollama)
  ```

**Why this design**

- Avoids cost and throttling of hosted LLMs.
- Keeps the same code-path as OpenAI (just change base URL/model).
- Demonstrates how to integrate **self-hosted LLMs** into a cloud app.

---

### 3.4 Kubernetes (k3s)

The cluster is a **single-node k3s** installation on the VM, installed via Ansible.

**Key namespaces**

- `staging` – staging environment for the app.
- `music` – production environment for the app.
- `monitoring` – Prometheus + Alertmanager + Grafana (kube-prometheus-stack).
- `cert-manager` – TLS certificate management.

**Core resources**

- **Deployment `yt-llm`** (in `staging` and `music`)
  - 1 replica
  - Resource requests/limits:
    - `requests: cpu 50m, memory 64Mi`
    - `limits: cpu 200m, memory 256Mi`
  - Probes:
    - Readiness: `GET /healthz`
    - Liveness: `GET /healthz`
  - Environment via ConfigMap + Secret.

- **Service `yt-llm-svc`**
  - ClusterIP service exposing port 80 → container port 8000.
  - Annotated for Prometheus scraping:
    - `prometheus.io/scrape: "true"`
    - `prometheus.io/path: "/metrics"`
    - `prometheus.io/port: "8000"`

- **Ingress `yt-llm-ing`**
  - IngressClass: `traefik`.
  - Hostnames:
    - `music-staging.<ip>.sslip.io` (staging)
    - `music.<ip>.sslip.io` (prod)
  - TLS secret: `yt-llm-tls`.
  - Certificate issued via cert-manager ClusterIssuer.

---

### 3.5 Networking, TLS & Domains

- **Ingress controller**: Traefik (bundled with k3s).
- **External DNS**: using [sslip.io](https://sslip.io), which maps:
  - `music.34.40.121.89.sslip.io` → `34.40.121.89`
  - `music-staging.34.40.121.89.sslip.io` → same IP, different hostname.
- **TLS certs**: cert-manager + Let’s Encrypt:
  - ClusterIssuers:
    - `letsencrypt-staging`
    - `letsencrypt-production`
  - Automatically issues certificates for:
    - App ingress (staging & prod).
    - Grafana ingress.

This setup provides **real HTTPS** with valid certificates (production issuer) and allows separate staging/prod hostnames using the same static IP.

---

### 3.6 Infrastructure as Code

Infrastructure is fully automated and reproducible via **Terraform + Ansible**.

#### Terraform (infra/terraform)

- Creates:
  - **Static external IP** (`yt-llm-k3s-ip`).
  - **Firewall rule** permitting SSH/HTTP/HTTPS/NodePort.
  - **Compute Engine VM**:
    - Machine type: `e2-medium` (2 vCPU, 4GB RAM).
    - Boot disk: 30GB, Debian 12.
    - Metadata: OS Login enabled.
- Exposes outputs used by CI/CD:
  - `static_ip` – used to construct sslip.io hostnames.
  - `vm_name`.

#### Ansible (infra/ansible)

Single `site.yml` playbook that:

1. Prepares the OS
   - Creates swap.
   - Installs base tools (curl, git, ca-certificates).

2. Installs & configures **Ollama**
   - Installs Ollama binary + systemd service.
   - Applies safe resource limits (`/etc/ollama/config.yaml`).
   - Pulls the `llama3.2:3b` model.

3. Installs **k3s** and waits for node readiness.

4. Installs **cert-manager** via Helm.

5. Installs **kube-prometheus-stack** (Prometheus, Alertmanager, Grafana).

6. Creates **ServiceMonitor** for the `yt-llm` Service.

7. Deploys the **application**
   - Writes ConfigMap, Secret, Deployment, Service, and Ingress manifests.
   - Restarts the Deployment when Secrets change (so token/keys are picked up).

The same playbook is used for both staging and production; namespaces and hostnames are passed in as extra-vars from the CI pipeline.

---

### 3.7 CI/CD Pipeline

Implemented with **GitHub Actions**.

**Job flow**

1. `build-test`
   - Checkout code.
   - Install dependencies.
   - Run unit + integration tests with stubbed API keys.

2. `docker`
   - Build multi-arch image (amd64 + arm64) via Buildx.
   - Push to GitHub Container Registry (GHCR).

3. `trivy`
   - Scan the built image for vulnerabilities.
   - Non-blocking, but surfaces findings.

4. `resolve-ip`
   - Uses `gcloud` + service account to look up the static IP resource by name.
   - Constructs:
     - `music-staging.<ip>.sslip.io`
     - `music.<ip>.sslip.io`

5. `deploy-staging`
   - SSH into the VM via GitHub secret key.
   - Generates Ansible inventory pointing at the VM.
   - Runs `ansible-playbook site.yml` with:
     - `K8S_NS=staging`
     - `HOST=music-staging.<ip>.sslip.io`
     - Secrets (YouTube key, API token, ACME email, etc.).
   - Performs HTTP health check against `https://music-staging.../healthz`.
   - On failure, rolls back the Deployment in the `staging` namespace.

6. `deploy-prod`
   - Runs only if staging succeeded.
   - Same pattern, but with:
     - `K8S_NS=music`
     - `HOST=music.<ip>.sslip.io`
     - `ISSUER_ENV=production` for real Let’s Encrypt certs.
   - Health check + rollback logic as in staging.

This pipeline ensures that:

- Every commit to `main` goes through tests, image build, scanning, and staged rollouts.
- Production is **only** updated after a successful staging deployment.

---

## 4. Authentication & Authorization

For this project, authentication is intentionally simple:

- **Token-based API authentication**
  - A single secret `API_TOKEN` is injected into the backend via Kubernetes Secret.
  - The frontend requires the user to paste this token into the UI.
  - Requests to `/suggest` must include `Authorization: Bearer <token>`.

**Rationale**

- Keeps implementation simple while still satisfying the **“authentication required”** project requirement.
- Avoids storing user credentials or managing sessions.
- Demonstrates how to secure internal APIs quickly in a small project.

In future iterations, this could be extended to:

- Per-user accounts and tokens (backed by a database).
- Role-based authorization around admin/normal users.
- Moving from a single shared token to per-user API keys.

---

## 5. Non-Goals and Trade-offs

- **No persistent database**
  - All data is derived on request from YouTube and the LLM.
  - This reduces complexity and operational overhead.
- **Single-node cluster**
  - k3s on one VM is sufficient to demonstrate Kubernetes concepts.
  - High availability and multi-node clustering are out of scope.
- **Local LLM vs hosted LLM**
  - Using Ollama trades some model quality/latency for cost control and independence from vendor throttling.
  - The design keeps an easy escape hatch: switch `OPENAI_BASE_URL` and `OPENAI_MODEL` to point at a hosted provider.

---

## 6. Summary

This architecture is intentionally “small but real”:

- Full web app with frontend + backend.
- Self-hosted LLM integrated over an OpenAI-compatible API.
- Kubernetes (k3s) with proper namespaces, ingress, TLS, and resource limits.
- Terraform + Ansible for fully reproducible infrastructure.
- GitHub Actions CI/CD with automated testing, image builds, scanning, deployment, health checks, and rollback.
- Observability provided by Prometheus + Grafana + Alertmanager.

