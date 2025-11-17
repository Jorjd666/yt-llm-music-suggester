# Security Overview

This document describes the main security measures implemented in the **yt-llm-music-suggester** project and how they fit together across application code, infrastructure, and operations.

---

## 1. Authentication & Authorization

### 1.1 API Authentication

The public backend API enforces a **Bearer token** on all non-health endpoints:

- Protected endpoints (e.g. `POST /api/v1/suggestions`) require:
  - HTTP header: `Authorization: Bearer <API_TOKEN>`
- The token value is **not** hard-coded:
  - Stored in Kubernetes as a Secret (`yt-llm-secrets` → `API_TOKEN`)
  - Injected into the application container via environment variable
- Requests with missing or invalid tokens:
  - Return `401 Unauthorized` with a structured JSON error payload
  - Do *not* reveal whether the token is close to valid

There is no user-by-user role system (RBAC) in this project; access is **all-or-nothing** based on possession of the shared API token, appropriate for a demo / capstone service.

### 1.2 Read-Only Public Endpoints

The following endpoints are intentionally unauthenticated:

- `GET /healthz` — simple health check for probes and CI/CD
- `GET /metrics` — Prometheus scraping (secured at the network/cluster level, not via token)

These are meant for infrastructure components (Kubernetes, Prometheus) rather than public users.

---

## 2. Secret Management

### 2.1 Where Secrets Live

Sensitive values are stored as **Kubernetes Secrets**, not in code:

- Namespace: `staging` and `music`
- Secret name: `yt-llm-secrets`
- Keys:
  - `YOUTUBE_API_KEY`
  - `OPENAI_API_KEY` (unused for live traffic when using Ollama, kept for compatibility)
  - `API_TOKEN`

These are:

- Created/updated by Ansible through **templated YAML** under `/tmp/secret.yaml` on the VM
- Applied with `k3s kubectl apply -f /tmp/secret.yaml`
- Marked `no_log: true` in Ansible, so values are **not printed in CI logs**

### 2.2 CI/CD Secret Handling

In GitHub Actions:

- Secrets are stored in **GitHub Actions secrets**:
  - `YOUTUBE_API_KEY`
  - `OPENAI_API_KEY`
  - `API_TOKEN`
  - `ACME_EMAIL`
  - `GCP_SA_KEY`
  - `SSH_PRIVATE_KEY`
- They are injected into jobs via `secrets.*` and passed to Ansible as `-e` vars.
- Workflows avoid echoing secrets; only presence/absence is validated.

### 2.3 No Hardcoded Secrets in Repo

- API tokens, API keys, SSH keys, and service account JSON are never committed.
- Secret values only exist at runtime in:
  - GitHub secret store
  - The GCP VM environment (transient Ansible process)
  - Kubernetes Secret objects

---

## 3. Transport Security (HTTPS / TLS)

### 3.1 Ingress + TLS

All user-facing traffic to the app and Grafana uses HTTPS:

- TLS is handled by **cert-manager** + **Let’s Encrypt** (staging & production issuers)
- Traefik Ingress objects:
  - `yt-llm-ing` in namespaces `staging` and `music`
  - `kps-grafana` in namespace `monitoring`
- Certificates:
  - `yt-llm-tls` per environment for the app
  - `grafana-tls` for Grafana

The Ansible playbook ensures:

- `ClusterIssuer` for `letsencrypt-staging` and `letsencrypt-production`
- Ingress annotations:
  - `cert-manager.io/cluster-issuer: <issuer>`
  - `kubernetes.io/ingress.class: traefik`
- TLS sections: hostnames on `*.sslip.io` + linked secrets

### 3.2 DNS / Domains

The app uses a static GCP external IP and **sslip.io** for DNS:

- `music.<IP>.sslip.io` → production namespace `music`
- `music-staging.<IP>.sslip.io` → staging namespace `staging`
- `grafana.<IP>.sslip.io` → monitoring namespace `monitoring`

Even though sslip.io is a convenience wildcard DNS, the app still benefits from full HTTPS with valid Let’s Encrypt certs.

---

## 4. Container & Kubernetes Security

### 4.1 Application Container Hardening

The main `yt-llm` Deployment applies sensible security contexts:

- `runAsNonRoot: true`
- `runAsUser: 10001`
- `allowPrivilegeEscalation: false`
- `readOnlyRootFilesystem: true`

This reduces the blast radius of any compromise inside the app container.

Resources are constrained:

- Requests: CPU `50m`, Memory `64Mi`
- Limits: CPU `200m`, Memory `256Mi`

This helps with stability on a small VM and avoids noisy-neighbor issues internally.

### 4.2 Network & Firewall

At the GCP level:

- A firewall rule `allow-web-ssh` allows only:
  - TCP 22 (SSH)
  - TCP 80, 443 (HTTP/HTTPS)
  - TCP 30080 (optional NodePort, if used)
- Firewall targets instances tagged with a specific tag (e.g. `yt-llm-k3s-tag`)
- `source_ranges = ["0.0.0.0/0"]` opens these ports, but **only** these ports are exposed.

Within Kubernetes:

- External access only through Traefik Ingress and TLS.
- Prometheus / Alertmanager / Grafana exposed via ClusterIP and Ingress (Grafana) rather than NodePorts.

### 4.3 K3s / Single-Node Cluster

The k3s cluster is:

- Single-node (control-plane + workload)
- Intended for demo / capstone usage, not high-security multi-tenant production
- Automatically bootstrapped via the `get.k3s.io` install script

Security trade-offs to note:

- Single-node cluster = no separation between control-plane and workloads
- Root access to VM gives full control over cluster

---

## 5. Supply Chain & CI/CD Security

### 5.1 Docker Image Build & Scan

The CI/CD pipeline:

1. Builds the application image via `docker/build-push-action` with a multi-stage Dockerfile.
2. Pushes images to **GitHub Container Registry (GHCR)**.
3. Runs a **Trivy** scan against the built image:
   - `vuln-type: os,library`
   - `severity: CRITICAL,HIGH`
   - `ignore-unfixed: true`
   - Non-blocking (`exit-code: 0`), but results appear in CI logs.

While the scan is non-blocking for convenience, it provides visibility into vulnerabilities and could be made blocking later.

### 5.2 GitOps-Style Deployment

Deployments to staging and production:

- Use **GitHub Actions** + **Ansible** over SSH to the k3s VM.
- Separate jobs:
  - `deploy-staging`
  - `deploy-prod` (depends on successful staging)
- After each deploy:
  - `/healthz` is checked via HTTPS
  - On failure:
    - `kubectl rollout undo` executed against the relevant Deployment

This gives a simple but effective **rollback** story.

### 5.3 SSH Access

SSH into the VM:

- Uses an **ed25519** key stored only in GitHub Secrets and your local machine
- GitHub workflow writes it to `~/.ssh/id_ed25519` inside the runner
- `StrictHostKeyChecking no` is set in CI for automation convenience
  - Note: outside CI, you still keep strict checking on your laptop

---

## 6. LLM & Ollama Security

### 6.1 OpenAI-Compatible Interface

The app talks to an OpenAI-compatible API endpoint:

- In cloud deployment, this is **Ollama** on the VM host via:
  - `OPENAI_BASE_URL = "http://<VM_INTERNAL_IP>:11434/v1"`
  - `OPENAI_MODEL = "llama3.2:3b"`

Security properties:

- Calls remain inside the VM’s private network (Pod → Node IP)
- No traffic to external LLM providers unless explicitly configured otherwise

### 6.2 Model Selection & Resource Limits

- The chosen model `llama3.2:3b` is relatively small:
  - Less CPU/RAM pressure → less risk of node instability under load
- Ollama config (`/etc/ollama/config.yaml`) sets conservative limits:
  - `num_ctx: 2048`
  - `num_thread: 2`
  - `max_loaded_models: 1`

This protects the VM from being overwhelmed by a large model footprint.

---

## 7. Logging & Privacy

### 7.1 Application Logging

The backend logs:

- Request/response information at a high level (status, path, timings)
- Errors and stack traces when exceptions occur

Care is taken to avoid logging:

- Full authorization headers
- Full API keys or tokens
- Sensitive request payloads in error messages

### 7.2 Prometheus & Grafana

Metrics and dashboards:

- Expose performance and health metrics (request counts, latencies, errors)
- Are not tied to user-identifiable data in this project
- Are accessible via HTTPS (Grafana Ingress with TLS)

---

## 8. OWASP & Hardening Checklist

While this is a capstone/demo project, several OWASP-aligned practices are followed:

- ✅ No secrets in code or repo
- ✅ HTTPS enforced via TLS certificates
- ✅ Simple but strict API authentication for protected endpoints
- ✅ Non-root containers with privilege escalation disabled
- ✅ Resource limits to avoid DoS from accidental overload
- ✅ Basic supply chain checks (Trivy)
- ✅ Centralized metrics / monitoring (Prometheus + Grafana)
- ✅ Rollback on failed deployments

Areas explicitly *out of scope* for this project’s level:

- No full user identity system (no OAuth2 / OIDC)
- No per-user authorization / roles (RBAC)
- No WAF or rate limiting at the ingress layer (only app-level logical limits)
- No detailed data classification (the app does not persist user data in a DB)

---

## 9. How to Talk About Security in the Presentation

When presenting, you can summarize like this:

> “For security, I focused on three layers:
>  1. **Access control**: the API uses a Bearer token stored in Kubernetes Secrets and never in code.
>  2. **Transport & infra**: all external traffic goes over HTTPS via Traefik + cert-manager + Let’s Encrypt; the VM is protected by GCP firewall rules, and the Kubernetes workloads run as non-root with resource limits.
>  3. **Supply chain & observability**: images are scanned with Trivy in CI, and I use kube-prometheus-stack (Prometheus + Alertmanager + Grafana) to monitor health and performance so I can notice and respond to issues early.”

You can then mention that for a production system you’d add: user identity, stricter network policies, rate-limiting at ingress, and potentially a Web Application Firewall (WAF).
