# Infrastructure Overview

This document describes the full infrastructure for the **YT LLM Music Suggester** project: cloud resources, Kubernetes, monitoring stack, and automation.

It’s meant to be read together with `ARCHITECTURE.md`.

---

## 1. High-Level Infrastructure Diagram (Text)

```text
GitHub (repo + Actions)
    |
    |  CI: build + test + Trivy
    |  CD: ansible-playbook via SSH
    v
GCP Project
  ├─ Static external IP (regional)
  ├─ Firewall rule (22/80/443/30080)
  └─ Compute Engine VM (yt-llm-k3s: e2-medium, 4GB RAM, 30GB disk)
        ├─ Host services
        │    ├─ k3s (single-node Kubernetes + Traefik)
        │    ├─ Ollama (llama3.2:3b model, HTTP API on :11434)
        │    └─ containerd (pulled app image)
        └─ Kubernetes namespaces
             ├─ cert-manager
             ├─ monitoring (Prometheus + Alertmanager + Grafana)
             ├─ staging (yt-llm app)
             └─ music (yt-llm app - “prod”)
```

---

## 2. Cloud Infrastructure (Terraform)

Terraform lives under:

```text
infra/terraform/
  main.tf
  providers.tf
  vars.tf
  outputs.tf
  terraform.tfstate
```

### 2.1. Provider

- **Provider**: `hashicorp/google`
- Project, region and zone are injected via TF variables and GitHub Actions env/vars.

### 2.2. Resources

#### 2.2.1 Static IP

`google_compute_address.ip`

- Type: regional **external static IP**
- Name: `yt-llm-k3s-ip`
- Region: `europe-west3`
- This IP is reused between VMs so ingress DNS never changes.
- CI uses `gcloud compute addresses describe` to resolve the IP by name and build `*.sslip.io` hostnames.

#### 2.2.2 Firewall

`google_compute_firewall.allow_web_ssh`

- Network: `default`
- Ports allowed from `0.0.0.0/0`:
  - `22` (SSH)
  - `80` (HTTP)
  - `443` (HTTPS)
  - `30080` (NodePort, if ever needed)
- Target tag: `${var.instance_tag}` (e.g. `yt-llm-k3s-tag`)

#### 2.2.3 Compute Engine VM

`google_compute_instance.k3s_vm`

- Name: `yt-llm-k3s`
- Machine type: `e2-medium` (2 vCPU, 4GB RAM)
- Disk:
  - 30GB, `pd-balanced`
  - Image: `debian-cloud/debian-12`
- Network:
  - Network: `default`
  - External IP: attached static IP
- Metadata:
  - `enable-oslogin = TRUE` (SSH via OS Login)
- Service Account:
  - Scope: `cloud-platform` (for future use, logs, etc.)
- Tags:
  - `${var.instance_tag}` to match the firewall rule.

> Terraform is intentionally **minimal**: it only provisions base compute + network and leaves Kubernetes, cert-manager, monitoring, and the app to Ansible.

---

## 3. Configuration Management (Ansible)

Ansible lives under:

```text
infra/ansible/
  ansible.cfg
  inventory.ini        # created dynamically in CI
  site.yml             # main playbook
```

### 3.1. Inventory

In CI, `inventory.ini` is generated like this:

```ini
[gcp]
gcpvm ansible_host=<GCP_VM_IP> ansible_user=debian ansible_ssh_private_key_file=~/.ssh/id_ed25519
```

Locally you can do the same with your own SSH key.

### 3.2. Playbook: `site.yml`

The playbook is a single play targeting the `gcp` host. It manages:

1. **System prep**
2. **Ollama installation and model pull**
3. **k3s installation**
4. **cert-manager** setup
5. **Monitoring** stack (kube-prometheus-stack)
6. **Application** deployment (staging/prod)
7. **Ingress + TLS**
8. Endpoint/debug info

Key variables:

```yaml
# namespaces / hosts
k8s_ns: "music" | "staging"
host: "music.<ip>.sslip.io" | "music-staging.<ip>.sslip.io"
monitoring_ns: "monitoring"
grafana_host: "grafana.<ip>.sslip.io"

# image / secrets
image: "ghcr.io/<owner>/yt-llm-music-suggester:<tag>"
yt_key: "{{ YT_KEY }}"
openai_key: "{{ OPENAI_KEY }}"
api_token: "{{ API_TOKEN }}"

# SSL / cert-manager
acme_email: "{{ ACME_EMAIL }}"
issuer_env: "staging" | "production"   # decides ClusterIssuer

# monitoring flags
manage_cert_manager: true
manage_monitoring: true

# Ollama
enable_ollama: true
ollama_model: "llama3.2:3b"
```

The CI pipeline passes these via `-e` when calling `ansible-playbook`.

---

## 4. Host-Level Setup (Ansible)

### 4.1. System Prep

Tasks:

- Force **noninteractive apt**
- Force **IPv4** for apt to avoid IPv6 DNS issues
- Clear any apt/dpkg locks and recover partially configured packages
- Add a **2G swapfile** (idempotent)
- Install base tools: `curl`, `git`, `ca-certificates`

### 4.2. Ollama on Host

Tasks when `enable_ollama=true`:

1. **Install Ollama**:

   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. Ensure service is **enabled + started** via `systemd`.
3. Create `/etc/ollama/config.yaml` with conservative resource limits:

   ```yaml
   num_ctx: 2048
   num_thread: 2
   max_loaded_models: 1
   ```

4. Pull the chosen model:

   ```bash
   ollama pull {{ ollama_model }}
   ```

- Current model in production: **`llama3.2:3b`** (smaller/lighter variant).
- The app connects to Ollama via:
  - `OPENAI_BASE_URL=http://<vm-internal-ip>:11434/v1`
  - `LLM_PROVIDER=openai` (Ollama speaks OpenAI-compatible API).

> This setup avoids any external paid LLMs for runtime, while tests can still use OpenAI-compatible mocks/local providers.

### 4.3. k3s (Single-Node Kubernetes)

- Install script:

  ```bash
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644" sh -s -
  ```

- The playbook then:
  - Waits for `k3s` systemd service to be `active`.
  - Waits for node `Ready` via `k3s kubectl get nodes`.
  - Ensures basic namespaces exist (`staging`, `music`, etc.).

Traefik is the built-in ingress controller used for all external routing.

---

## 5. Kubernetes Components (via Ansible)

### 5.1. cert-manager

Installed via Helm when `manage_cert_manager=true`:

- Repo: `jetstack`
- Release: `cert-manager`
- Namespace: `cert-manager`
- CRDs: `crds.enabled=true`

ClusterIssuers created:

- **letsencrypt-staging**
- **letsencrypt-production**

Each uses HTTP-01 validation through Traefik and the configured `acme_email`. The active issuer is chosen per environment with:

```yaml
issuer_name: "letsencrypt-staging" | "letsencrypt-production"
```

### 5.2. Monitoring Stack (kube-prometheus-stack)

Installed via Helm when `manage_monitoring=true`:

- Repo: `prometheus-community`
- Release: `kps`
- Namespace: `monitoring`

Includes:

- **Prometheus**
- **Alertmanager**
- **Grafana**
- Node exporter, kube-state-metrics, etc.

Grafana is exposed via TLS-enabled Ingress:

- Host: `grafana.<static-ip>.sslip.io`
- TLS secret: `grafana-tls`
- Uses the same ClusterIssuer (`issuer_name`) as the app.

### 5.3. ServiceMonitor for the App

Ansible applies `yt-llm-servicemonitor` in the `monitoring` namespace, which:

- Selects Service `yt-llm-svc` by label `app: yt-llm` in the app namespace (staging/music).
- Scrapes on:
  - Port: `http`
  - Path: `/metrics`
  - Interval: `30s`

This feeds metrics into Prometheus and makes them visible in Grafana.

### 5.4. Application Manifests

Generated on the fly by Ansible into `/tmp/*.yaml` and applied with `k3s kubectl apply`.

#### 5.4.1 ConfigMap

`yt-llm-config`:

```yaml
LLM_PROVIDER: "openai"
OPENAI_BASE_URL: "http://<vm-internal-ip>:11434/v1"
OPENAI_MODEL: "<ollama_model>"
RATE_LIMIT: "10/minute"
MAX_YT_RESULTS: "25"
MAX_SUGGESTIONS: "10"
REQUESTS_TIMEOUT: "10"
```

#### 5.4.2 Secrets

`yt-llm-secrets` (Opaque, stringData):

- `YOUTUBE_API_KEY`
- `OPENAI_API_KEY` (only used if remote OpenAI is enabled; otherwise blank)
- `API_TOKEN` (per-user token for the frontend auth field)

No secrets are hardcoded; CI injects them from GitHub Secrets.

#### 5.4.3 Deployment

`Deployment/yt-llm`:

- Replicas: **1** (staging & prod)
- Container image: GHCR image built per commit.
- Probes:
  - Readiness: `GET /healthz`
  - Liveness:  `GET /healthz`
- Resources:
  - Requests: `50m` CPU, `64Mi` RAM
  - Limits:   `200m` CPU, `256Mi` RAM
- Security Context:
  - `runAsNonRoot: true`, `runAsUser: 10001`
  - `allowPrivilegeEscalation: false`
  - `readOnlyRootFilesystem: true`

#### 5.4.4 Service

`Service/yt-llm-svc`:

- Type: `ClusterIP` (Ingress fronted)
- Port:
  - Name: `http`
  - Port: `80`
  - TargetPort: `8000`
- Annotations for Prometheus scraping:

```yaml
prometheus.io/scrape: "true"
prometheus.io/path: "/metrics"
prometheus.io/port: "8000"
```

#### 5.4.5 Ingress

`Ingress/yt-llm-ing` (per namespace):

- Class: `traefik`
- Host:
  - `music-staging.<ip>.sslip.io` (staging)
  - `music.<ip>.sslip.io` (prod)
- TLS:
  - `secretName: yt-llm-tls`
  - `cert-manager.io/cluster-issuer: "<issuer_name>"`

This yields full HTTPS termination via Let’s Encrypt in both environments.

---

## 6. CI/CD Pipeline (GitHub Actions)

Workflow file: `.github/workflows/ci-cd.yml`

Jobs:

1. **build-test**
   - Checkout, install deps, run pytest.
   - Uses fake API keys/env so tests don’t hit real services.

2. **docker**
   - Multi-arch build (`linux/amd64`, `linux/arm64`) with `docker/build-push-action`.
   - Pushes to GHCR:
     - `:latest`
     - `:<git-sha>`

3. **trivy**
   - Non-blocking vulnerability scan of the GHCR image.

4. **resolve-ip**
   - Uses GCP service account to read static address by name (`TF_ADDRESS_NAME`).
   - Exposes:
     - `GCP_VM_IP`
     - `HOST_STAGING`
     - `HOST_PROD`

5. **deploy-staging**
   - Creates SSH key + config for `gcpvm` host.
   - Generates `infra/ansible/inventory.ini` dynamically.
   - Runs:

     ```bash
     ansible-playbook -i inventory.ini site.yml        -e K8S_NS="staging"        -e HOST="${HOST_STAGING}"        -e IMAGE="<ghcr image>"        -e YT_KEY="${YOUTUBE_API_KEY}"        -e OPENAI_KEY="${OPENAI_API_KEY}"        -e API_TOKEN="${API_TOKEN}"        -e ACME_EMAIL="${ACME_EMAIL}"        -e ISSUER_ENV=staging
     ```

   - Performs `/healthz` HTTP 200 loop against staging.
   - If health fails but deployment succeeded, runs a **rollout undo** as rollback.

6. **deploy-prod**
   - Same pattern as staging, but with:
     - `K8S_NS="music"`
     - `HOST="${HOST_PROD}"`
     - `ISSUER_ENV=production`
   - Health check `/healthz` and rollback on failure.

> This satisfies: automated testing, container build, vulnerability scanning, and automated deployment with rollback for both staging and production.

---

## 7. Secrets & Configuration Management

All sensitive values are **never** committed in git. They are passed via:

- **GitHub Secrets**:
  - `YOUTUBE_API_KEY`
  - `OPENAI_API_KEY` (optional)
  - `API_TOKEN`
  - `SSH_PRIVATE_KEY`
  - `GCP_SA_KEY`
  - `ACME_EMAIL`
- **GitHub Environment/Repo Vars**:
  - `GCP_PROJECT_ID`
  - `GCP_REGION`
  - `TF_ADDRESS_NAME`

Ansible receives these as extra vars (`-e`) and injects them into Kubernetes Secrets.

---

## 8. How to Recreate the Infrastructure

### 8.1. Prerequisites

- GCP project + billing enabled.
- Terraform installed locally.
- gcloud SDK locally (or use CI as the source of truth).
- GitHub repo with appropriate Secrets/Vars configured.

### 8.2. Steps

1. **Terraform apply** (from `infra/terraform`):

   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

   This creates the static IP, firewall, and VM.

2. **SSH to VM** (optional sanity check):

   ```bash
   ssh debian@<static_ip>
   ```

3. **CI/CD Deploy**

   - Push to `main` or trigger `workflow_dispatch` for `ci-cd` workflow.
   - Pipeline will:
     - Test
     - Build + push image
     - Scan with Trivy
     - Discover VM IP
     - Run Ansible for staging + production

4. **Validate Endpoints**

   - App health:
     - `https://music-staging.<ip>.sslip.io/healthz`
     - `https://music.<ip>.sslip.io/healthz`
   - App UI:
     - `https://music-staging.<ip>.sslip.io/`
     - `https://music.<ip>.sslip.io/`
   - Grafana:
     - `https://grafana.<ip>.sslip.io/`

---

## 9. Notes and Trade-offs

- **Single-node k3s**:
  - Great for a teaching/demo setup and cost effective.
  - Not HA; a single VM is a single point of failure.
- **Ollama on host**:
  - Avoids external LLM costs and latency.
  - Uses local CPU only; model size must be chosen to fit 4GB RAM.
- **sslip.io for DNS**:
  - Removes the need for manual DNS management during the project.
  - In a production system, custom domain + DNS records would replace this.

This infra stack is intentionally opinionated: **Terraform for base infra**, **Ansible for k3s + app**, and **GitHub Actions for CI/CD**. It demonstrates reproducibility, automation, and observability end-to-end.
