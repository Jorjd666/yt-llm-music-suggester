# yt-llm-music-suggester – Demo & Operations Cheat Sheet

**demo-friendly** README, focused on:

- What the app does (in human words)
- How to use the **GUI** in the browser
- How to call the API with **curl** (and get ✅ positive responses)
- How to authenticate with the **Bearer token**
- How to open **Grafana** (dashboards) and **Alertmanager** (alerts)
- Where to look for deeper docs

For full technical details, see:

- `ARCHITECTURE.md` – high-level architecture & flows  
- `INFRASTRUCTURE.md` – Terraform / Ansible / k3s / GCP VM  
- `DEPLOYMENT.md` – CI/CD pipeline, environments, rollback  
- `MONITORING.md` – Prometheus, Grafana, ServiceMonitor, alerts  
- `APP.md` – FastAPI app, models, business logic  
- `SECURITY.md` – secrets, auth, hardening  
- `PRESENTATION_NOTES.md` – your extended speaking script

---

## 1. What the app does (short story)

The app is a **FastAPI-based music recommender**:

1. You type a **genre / mood / era / language** in a small web UI.
2. The backend calls **YouTube Data API** to fetch candidate music videos.
3. Candidates are sent to an **LLM running on the VM via Ollama** (OpenAI-compatible API).
4. The LLM **re-ranks, deduplicates, and enriches** results with short reasons & tags.
5. The UI shows **cards** with thumbnails, titles, channels and the reason text.

It’s deployed on a **GCP VM** running **k3s**, fronted by **Traefik Ingress** with **cert-manager** TLS.

---

## 2. URLs you need for the live demo

Assuming your static IP is `34.40.121.89` (current Terraform setup) and `sslip.io`:

- **Staging app UI**  
  `https://music-staging.34.40.121.89.sslip.io/`

- **Production app UI**  
  `https://music.34.40.121.89.sslip.io/`

- **Grafana (monitoring dashboards)**  
  `https://grafana.34.40.121.89.sslip.io/`

> If you ever recreate the VM and change the IP, these hosts become:  
> `music-staging.<NEW-IP>.sslip.io`, `music.<NEW-IP>.sslip.io`, `grafana.<NEW-IP>.sslip.io`.

---

## 3. Getting the API Bearer token

The app can be **locked behind an API token**. The token is injected from CI as `API_TOKEN`
and stored in a Kubernetes Secret (`yt-llm-secrets`), then exposed as `API_TOKEN` env var
in the `yt-llm` Deployment.

You can get the value in two ways:

### 3.1 From Kubernetes (VM shell)

SSH into the VM:

```bash
ssh -i ~/.ssh/yt-llm-k3s debian@34.40.121.89
```

Then:

```bash
# Production / music namespace
sudo k3s kubectl -n music exec deploy/yt-llm -- printenv API_TOKEN
```

Copy the value (a long hex-like string). This is the **raw token**, *without* `Bearer` in front.

### 3.2 From GitHub Secrets (CI/CD)

Alternatively, open the repo → **Settings → Secrets and variables → Actions** and find the
`API_TOKEN` secret. That’s the same value used during deployment.

---

## 4. Using the GUI with the Bearer token

1. Open the **production UI** in your browser:
   - `https://music.34.40.121.89.sslip.io/`

2. On first use, if `API_TOKEN` is set, the page will ask you for a token.
   - Paste the **raw token** (e.g., `e57607...53805aa`) – **do not** type `Bearer` here.
   - The UI stores it in `localStorage` and automatically sends:
     ```http
     Authorization: Bearer <your-token>
     ```

3. Fill the fields, for example:
   - Genre: `lofi`
   - Mood: `chill`
   - Era: `any`
   - Language: `en`
   - Limit: `5`

4. Click **“Suggest”**.

✅ **Expected:** a list of cards with:
- Thumbnail
- Title + channel
- Short description (“reason”)
- Tags
- Link to YouTube (opens in new tab)

If the token is wrong or missing, you’ll see a 401 in the browser console or an error on screen.

---

## 5. Happy-path curl tests (with positive responses)

Replace `PROD_HOST` / `STAGING_HOST` below with the real host when needed, for example:

```bash
export PROD_HOST="music.34.40.121.89.sslip.io"
export STAGING_HOST="music-staging.34.40.121.89.sslip.io"
export API_TOKEN="<paste token here>"
```

### 5.1 Health check

```bash
curl -k https://$PROD_HOST/healthz
```

✅ Expected (HTTP 200):

```json
{"status": "ok"}
```

### 5.2 Metrics endpoint

```bash
curl -k https://$PROD_HOST/metrics | head
```

✅ Expected: a bunch of Prometheus metrics (`http_requests_total`, `process_cpu_seconds_total`, etc.).

### 5.3 Suggest endpoint (authenticated)

```bash
curl -k -X POST "https://$PROD_HOST/suggest"       -H "Content-Type: application/json"       -H "Authorization: Bearer $API_TOKEN"       -d '{
    "genre": "lofi",
    "mood": "chill",
    "era": "any",
    "language": "en",
    "limit": 3
  }' | jq .
```

✅ Expected (HTTP 200): JSON like:

```json
{
  "suggestions": [
    {
      "title": "…",
      "videoId": "…",
      "channelTitle": "…",
      "url": "https://www.youtube.com/watch?v=…",
      "reason": "short explanation from the LLM",
      "tags": ["chill", "lofi", "instrumental"],
      "publishedAt": "2024-01-01T00:00:00Z"
    }
  ],
  "source_counts": {
    "youtube_candidates": 25,
    "llm_ranked": 3
  }
}
```

If `LLM_PROVIDER` or Ollama is misconfigured, you’ll see a clear error message in the response,
and logs in the pod will show context; for the demo, everything is wired to Ollama.

---

## 6. Grafana – dashboards

URL:

```text
https://grafana.34.40.121.89.sslip.io/
```

### 6.1 Getting the Grafana admin password

On the VM:

```bash
ssh -i ~/.ssh/yt-llm-k3s debian@34.40.121.89

# Get password from the kube-prometheus-stack Secret
sudo k3s kubectl -n monitoring get secret kps-grafana       -o jsonpath="{.data.admin-password}" | base64 -d; echo
```

Default username is:

```text
admin
```

Use `admin` + the decoded password to log in.

### 6.2 Useful dashboards for the demo

Once inside Grafana (with Prometheus as the default datasource):

- **Kubernetes / Compute Resources / Pods / Namespace “music”**
  - Shows CPU/memory for the `yt-llm` pod.
- **Kubernetes / Networking / Namespace “music”**
  - Shows HTTP traffic and errors.
- Custom dashboard (if you created one) using metrics like:
  - `http_requests_total{path="/suggest"}`
  - `process_cpu_seconds_total`
  - `python_gc_objects_collected_total` (if exposed)

For a quick graph while you demo:

1. Click **“+ Create → Dashboard → Add a new panel”**.
2. Query: `http_requests_total{handler="/suggest"}`.
3. Set visualization to **Time series** and hit **Apply**.

When you click “Suggest” in the UI during the demo, the graph should move.

---

## 7. Alertmanager – viewing alerts

Alertmanager is installed via **kube-prometheus-stack** but is **not exposed publicly**
(to keep the attack surface small). You access it via `kubectl port-forward`.

### 7.1 Get kubeconfig locally (once)

On the VM:

```bash
sudo cat /etc/rancher/k3s/k3s.yaml
```

Copy this file to your laptop as `k3s-kubeconfig.yaml`, then edit the `server:` line to use
the VM’s external IP:

```yaml
server: https://34.40.121.89:6443
```

On your laptop:

```bash
export KUBECONFIG=~/k3s-kubeconfig.yaml
kubectl get nodes
# should show: yt-llm-k3s Ready
```

### 7.2 Port-forward Alertmanager

From your laptop (with `KUBECONFIG` set):

```bash
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-alertmanager 9093:9093
```

Then open in your browser:

```text
http://localhost:9093/
```

✅ Expected: Alertmanager UI showing “No alerts firing” under normal conditions.

You can trigger sample alerts (e.g., by killing the `yt-llm` pod or increasing resource
usage) – see `MONITORING.md` if you want explicit steps.

---

## 8. Where to find more details

- **Architecture, flows, sequence diagrams:** `ARCHITECTURE.md`
- **VM, k3s, Terraform, Ansible:** `INFRASTRUCTURE.md`
- **CI/CD, jobs, rollback strategy:** `DEPLOYMENT.md`
- **App internals & API schema:** `APP.md`
- **Monitoring stack & alert rules:** `MONITORING.md`
- **Security model & hardening:** `SECURITY.md`
- **Your speaking script:** `PRESENTATION_NOTES.md`

For the actual **live demo**, you can almost entirely drive from this README:

1. Show the **GUI**, do a successful suggestion with visible cards.  
2. Show **curl /healthz** and **curl /suggest** with Bearer.  
3. Jump into **Grafana**, show a graph moving when you hit `/suggest`.  
4. Optionally show **Alertmanager** UI via port-forward.
