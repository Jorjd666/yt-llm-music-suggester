# Deployment Guide – yt-llm-music-suggester

This document describes **how code goes from your laptop to production** for the `yt-llm-music-suggester` project.

High‑level flow:

1. **Local dev** → run & test app in Docker locally.
2. **Infrastructure** → create / update GCP VM + static IP with Terraform.
3. **CI/CD pipeline** (GitHub Actions):
   - run tests
   - build & push Docker image to GHCR
   - scan with Trivy
   - resolve GCP static IP via `gcloud`
   - deploy **staging** via Ansible → k3s + cert‑manager + monitoring + app
   - health check → if OK → deploy **production**
4. **Runtime**:
   - App runs in **k3s** on the VM
   - HTTPS via **Traefik + cert‑manager + Let’s Encrypt**
   - Monitoring via **kube‑prometheus‑stack** (Prometheus + Alertmanager + Grafana)
   - LLM served by **Ollama** on the host, app talks to it via an OpenAI‑compatible API.

---

## 1. Environments

You effectively have:

- **Local dev** – everything runs on your machine (optional Ollama).
- **Staging** – Kubernetes namespace: `staging`
  - ingress: `https://music-staging.<STATIC_IP>.sslip.io`
- **Production** – Kubernetes namespace: `music`
  - ingress: `https://music.<STATIC_IP>.sslip.io`
- **Monitoring** – Kubernetes namespace: `monitoring`
  - Grafana ingress: `https://grafana.<STATIC_IP>.sslip.io`

All of these live on the **same GCP VM**, separated by Kubernetes namespaces and Ingress hosts.

---

## 2. Prerequisites

### 2.1. Local machine

- Python 3.11
- Docker
- Terraform CLI
- `gcloud` CLI (optional, mostly handled in CI)
- Git

Clone the repo:

```bash
git clone https://github.com/<your-user>/yt-llm-music-suggester.git
cd yt-llm-music-suggester
```

Create and activate virtualenv (optional but recommended):

```bash
python -m venv .venv
source .venv/bin/activate  # on macOS/Linux
# .venv\Scripts\activate  # on Windows
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 2.2. Cloud resources (GCP)

You need a **GCP project** and a **service account** with permissions for:

- Compute Engine (instances, addresses, firewall)
- Service Account Token Creator (for `gcloud` usage from CI, if needed)

You also need:

- A **service account key JSON**, stored as a GitHub secret (`GCP_SA_KEY`).

---

## 3. Terraform – Infrastructure Deployment

Terraform lives under: `terraform/`

Key files:

- `main.tf` – defines:
  - static external IP (data source)
  - firewall rule (`allow_web_ssh`)
  - VM instance (`google_compute_instance.k3s_vm`)
- `outputs.tf` – exposes:
  - `static_ip`
  - `vm_name`
- `providers.tf` – configures Google provider.

> **Note:** The static IP is typically created once (e.g. via the console or a previous TF version) and then **referenced via a data source**, so Terraform doesn’t recreate it.

### 3.1. Configure Terraform variables

Create `terraform/terraform.tfvars`:

```hcl
project_id        = "your-gcp-project-id"
region            = "europe-west3"
zone              = "europe-west3-c"
vm_name           = "yt-llm-k3s"
machine_type      = "e2-medium"
boot_image        = "debian-cloud/debian-12"
disk_size_gb      = 30
instance_tag      = "yt-llm-k3s-tag"
service_account_email = "your-sa@your-project.iam.gserviceaccount.com"
static_ip_name    = "yt-llm-k3s-ip"
```

### 3.2. Terraform commands

From `terraform/`:

```bash
terraform init
terraform plan
terraform apply
```

Once applied, Terraform will output:

- `static_ip` – used by CI to construct `music*.sslip.io` hostnames
- `vm_name` – name of the VM created

You can verify the instance in the GCP console under **Compute Engine → VM instances**.

---

## 4. GitHub CI/CD – Pipeline Overview

The pipeline definition is in:

- `.github/workflows/ci-cd.yml`

### 4.1. Required GitHub Secrets

Set these in **GitHub → Settings → Secrets and variables → Actions → Secrets**:

- `GCP_SA_KEY` – JSON key for GCP service account
- `SSH_PRIVATE_KEY` – private key that can SSH into `debian@<VM_IP>`
- `YOUTUBE_API_KEY` – YouTube Data API v3 key
- `OPENAI_API_KEY` – (currently unused when Ollama is used, but kept for flexibility)
- `API_TOKEN` – bearer token used by frontend to authenticate to the backend
- `ACME_EMAIL` – email to use for Let’s Encrypt registrations

### 4.2. Required GitHub Variables

Set these in **GitHub → Settings → Secrets and variables → Actions → Variables**:

- `GCP_PROJECT_ID` – your GCP project id
- `GCP_REGION` – e.g. `europe-west3`
- `TF_ADDRESS_NAME` – name of the static IP resource in GCP, e.g. `yt-llm-k3s-ip`

### 4.3. Job breakdown

#### 4.3.1. `build-test`

- Runs unit tests with `pytest`
- Uses stub values for YT/OpenAI keys
- Fails fast if tests break

#### 4.3.2. `docker`

- Builds a multi‑arch Docker image for the app
- Tags and pushes to GHCR:
  - `ghcr.io/<owner>/yt-llm-music-suggester:latest`
  - `ghcr.io/<owner>/yt-llm-music-suggester:<git-sha>`

#### 4.3.3. `trivy`

- Scans the built image for vulnerabilities
- Does **not** fail the build (exit‑code `0`) but reports issues

#### 4.3.4. `resolve-ip`

- Uses `gcloud` with `GCP_SA_KEY` to read the static IP from GCP
- Produces:
  - `GCP_VM_IP`
  - `HOST_STAGING` = `music-staging.<IP>.sslip.io`
  - `HOST_PROD` = `music.<IP>.sslip.io`

#### 4.3.5. `deploy-staging`

- SSH into VM as `debian` using `SSH_PRIVATE_KEY`
- Generates `infra/ansible/inventory.ini` with:
  - `gcpvm ansible_host=<GCP_VM_IP> ansible_user=debian ...`
- Runs:

```bash
ansible-playbook -i inventory.ini site.yml   -e K8S_NS="staging"   -e HOST="${HOST}"   -e IMAGE="${IMAGE}"   -e YT_KEY="${YOUTUBE_API_KEY}"   -e OPENAI_KEY="${OPENAI_API_KEY}"   -e API_TOKEN="${API_TOKEN}"   -e ACME_EMAIL="${ACME_EMAIL}"   -e ISSUER_ENV=staging
```

- Performs `/healthz` checks on staging ingress:
  - `https://music-staging.<IP>.sslip.io/healthz`
- If health check fails → attempts rollback using:
  - `kubectl rollout undo deploy/yt-llm -n staging`

#### 4.3.6. `deploy-prod`

Triggered only if `deploy-staging` succeeds.

- Same flow as staging, but target namespace `music` and `ISSUER_ENV=production`.
- Health check against:
  - `https://music.<IP>.sslip.io/healthz`
- Rollback uses:
  - `kubectl rollout undo deploy/yt-llm -n music`

---

## 5. Ansible – Cluster & App Deployment (site.yml)

Ansible playbook lives in: `infra/ansible/site.yml`

High‑level tasks:

1. **System prep**
   - Non‑interactive APT
   - IPv4‑only APT workaround
   - Clean APT locks, update cache
   - Create 2 GB swap

2. **Ollama on host**
   - Install Ollama via official script
   - Enable and start `ollama` systemd service
   - Configure `/etc/ollama/config.yaml` with conservative resource limits
   - `ollama pull llama3.2:3b` (small, CPU‑friendly model)

3. **k3s install**
   - Install k3s with Traefik ingress controller
   - Wait for node to be `Ready`
   - Verify API server health (`kubectl get ns`)
   - Create target namespace (`staging` or `music`)

4. **cert-manager**
   - Install Helm (if needed)
   - Add Jetstack repo & update
   - Install/upgrade `cert-manager` with CRDs turned on
   - Wait for cert‑manager deployments to be ready
   - Create `ClusterIssuer`s:
     - `letsencrypt-staging`
     - `letsencrypt-production`

5. **Monitoring stack**
   - Ensure `monitoring` namespace exists
   - Install `kube-prometheus-stack` Helm chart (Prometheus, Alertmanager, Grafana)
   - Configure Grafana Ingress with TLS:
     - host `grafana.<IP>.sslip.io`
   - Create `ServiceMonitor` for `yt-llm-svc` so Prometheus scrapes `/metrics`
   - Result: Grafana UI reachable via HTTPS.

6. **App config**
   - Pre‑pull app Docker image via `k3s ctr`
   - ConfigMap:
     - `LLM_PROVIDER=openai` (OpenAI‑compatible)
     - `OPENAI_BASE_URL=http://<vm-internal-ip>:11434/v1` (Ollama)
     - `OPENAI_MODEL=llama3.2:3b`
     - Rate limiting, timeouts, etc.
   - Secret:
     - `YOUTUBE_API_KEY`
     - `OPENAI_API_KEY` (optional / unused in Ollama mode)
     - `API_TOKEN`

7. **App deployment & service**
   - `Deployment` `yt-llm` with 1 replica
   - Probes:
     - readiness + liveness on `/healthz`
   - Resource requests/limits for low‑footprint usage
   - `Service` `yt-llm-svc` (port 80 → 8000) with Prometheus annotations.

8. **Ingress**
   - Traefik ingress with TLS:
     - host `music-staging.<IP>.sslip.io` (staging)
     - host `music.<IP>.sslip.io` (prod)
   - Certificate issued via the appropriate `ClusterIssuer`.

---

## 6. Runtime Verification After Deployment

After a successful pipeline run:

### 6.1. Check cluster + namespaces (via SSH)

```bash
ssh -i ~/.ssh/yt-llm-k3s debian@<STATIC_IP>

sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get pods -n staging -o wide
sudo k3s kubectl get pods -n music -o wide
sudo k3s kubectl get pods -n monitoring -o wide
```

All pods should be `Running` and not CrashLooping.

### 6.2. Check HTTPS & certificates

```bash
sudo k3s kubectl get ingress -A
sudo k3s kubectl get certificate -A
```

You should see:

- Ingresses for `music-staging.*`, `music.*`, `grafana.*`
- Certificates with `READY=True`

### 6.3. Check Ollama

On the VM:

```bash
curl -s http://localhost:11434/api/tags | jq .
```

You should see `llama3.2:3b` as an available model.

### 6.4. Check app environment

```bash
sudo k3s kubectl -n music exec deploy/yt-llm -- env | grep -E 'LLM_PROVIDER|OPENAI_'
```

Expected:

- `LLM_PROVIDER=openai`
- `OPENAI_BASE_URL=http://10.156.0.3:11434/v1` (or similar internal IP)
- `OPENAI_MODEL=llama3.2:3b`

### 6.5. Check service & metrics

```bash
sudo k3s kubectl -n music get svc yt-llm-svc -o wide
```

Then in browser:

- `https://music.<STATIC_IP>.sslip.io/healthz`
- `https://music.<STATIC_IP>.sslip.io/metrics` (should show Prometheus metrics)

### 6.6. Grafana & Prometheus

In browser:

- Grafana: `https://grafana.<STATIC_IP>.sslip.io/`
  - Login with default admin credentials (if unchanged)
  - Data source: `Prometheus` (preconfigured by kube‑prometheus‑stack)
  - Explore metrics: `yt_llm_*` or HTTP metrics from the app.

---

## 7. How to Redeploy / Update

### 7.1. Code‑only changes

For backend/frontend/app logic only:

1. Commit & push to `main`:
   ```bash
   git add .
   git commit -m "feat: tweak recommendations UI"
   git push origin main
   ```
2. Wait for CI:
   - tests → docker build → trivy → staging deploy → prod deploy.
3. Verify in browser (staging then prod).

### 7.2. Infra / cluster changes

If you modify:

- Terraform (`terraform/`)
- Ansible (`infra/ansible/site.yml`)
- CI (`.github/workflows/ci-cd.yml`)

then:

1. Apply Terraform changes locally (if infra changed):
   ```bash
   cd terraform
   terraform plan
   terraform apply
   ```
2. Commit and push infra changes
3. CI will run Ansible with the new playbook.

### 7.3. Rollback strategy

Two main options:

- **Kubernetes rollout undo** (already used in CI):
  - `sudo k3s kubectl -n music rollout undo deploy/yt-llm`
- **Re-run previous successful pipeline** from GitHub Actions UI:
  - Choose older green run → `Re-run workflow`.

---

## 8. Manual one-off deployments (optional)

If you need to bypass CI (e.g. testing Ansible changes):

```bash
# From your laptop
ssh -i ~/.ssh/yt-llm-k3s debian@<STATIC_IP>

# On the VM, if you copy the repo there (optional):
cd ~/yt-llm-music-suggester/infra/ansible

ansible-playbook -i inventory.ini site.yml   -e K8S_NS="staging"   -e HOST="music-staging.<STATIC_IP>.sslip.io"   -e IMAGE="ghcr.io/<owner>/yt-llm-music-suggester:latest"   -e YT_KEY="..."   -e OPENAI_KEY="..."   -e API_TOKEN="..."   -e ACME_EMAIL="..."   -e ISSUER_ENV=staging
```

Normally you won’t need this, because everything is wired through CI/CD, but it’s useful for debugging.

---

## 9. Summary

- **Terraform** provisions a single, beefy enough VM with a static IP and firewall.
- **Ansible** turns that VM into a full cluster:
  - k3s + Traefik
  - cert‑manager + Let’s Encrypt
  - kube‑prometheus‑stack (Prometheus, Alertmanager, Grafana)
  - Ollama (CPU‑friendly LLM) on the host
  - Your app deployed into `staging` + `music` namespaces.
- **GitHub Actions** drive the whole lifecycle:
  - test → build → scan → deploy‑staging → health‑check → deploy‑prod → health‑check.

You now have a **reproducible, cloud‑hosted, monitored, TLS‑secured, LLM‑powered web app** that can be redeployed from a single `git push`.
