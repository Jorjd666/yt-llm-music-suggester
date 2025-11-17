# Monitoring & Observability

This document describes how monitoring and alerting are implemented for the **yt-llm-music-suggester** project, and how to access and extend them.

---

## 1. Stack Overview

Monitoring is based on the **kube-prometheus-stack** Helm chart, which installs:

- **Prometheus** – metrics collection and storage
- **Alertmanager** – routing and handling of alerts
- **Grafana** – dashboards and visualization
- **Node Exporter / Kube State Metrics** – cluster and node metrics
- **ServiceMonitor** – custom scrape configuration for the yt-llm app

All these components are deployed into the **`monitoring`** namespace on the k3s cluster.

The stack is installed by Ansible via Helm:

- Namespace: `monitoring`
- Release name: `kps`
- Chart: `prometheus-community/kube-prometheus-stack`

---

## 2. Kubernetes Resources

### 2.1 Monitoring Namespace

- Namespace: `monitoring`
- Created by Ansible (`Ensure monitoring namespace exists` task)

```bash
sudo k3s kubectl get ns monitoring
```

### 2.2 Core Monitoring Pods

Typical pods (names may differ slightly due to hashes):

- `kps-kube-prometheus-stack-prometheus-0`
- `alertmanager-kps-kube-prometheus-stack-alertmanager-0`
- `kps-grafana-...`
- `kps-kube-state-metrics-...`
- `kps-prometheus-node-exporter-...`
- `kps-kube-prometheus-stack-operator-...`

Check status:

```bash
sudo k3s kubectl get pods -n monitoring -o wide
```

### 2.3 Services and Ingress

Key services in `monitoring`:

- `kps-kube-prometheus-stack-prometheus` (ClusterIP)
- `kps-kube-prometheus-stack-alertmanager` (ClusterIP)
- `kps-grafana` (ClusterIP)

Grafana is exposed via **Traefik Ingress** with TLS:

- Namespace: `monitoring`
- Ingress: `kps-grafana`
- Host: `grafana.<STATIC_IP>.sslip.io`
- Certificate: `grafana-tls` (managed by cert-manager / Let’s Encrypt)

Example check:

```bash
sudo k3s kubectl get ingress -n monitoring
sudo k3s kubectl get certificate -n monitoring
```

---

## 3. Application Metrics (yt-llm)

### 3.1 ServiceMonitor

The Ansible playbook creates a **ServiceMonitor** to attach the app service to Prometheus:

- Namespace: `monitoring`
- Name: `yt-llm-servicemonitor`
- Selector: `app: yt-llm`
- Scrape namespace: `music` (production app namespace)
- Endpoint:
  - Port: `http`
  - Path: `/metrics`
  - Interval: `30s`

The corresponding YAML (applied via Ansible):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: yt-llm-servicemonitor
  namespace: monitoring
  labels:
    release: kps
spec:
  selector:
    matchLabels:
      app: yt-llm
  namespaceSelector:
    matchNames:
      - music
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

The app’s Kubernetes Service (`yt-llm-svc` in namespace `music`) is annotated for Prometheus and exposes:

- Port name: `http`
- Port: `80` (targetPort `8000`)
- Path: `/metrics`

Verify ServiceMonitor:

```bash
sudo k3s kubectl get servicemonitor -n monitoring
sudo k3s kubectl describe servicemonitor yt-llm-servicemonitor -n monitoring
```

### 3.2 App Metrics Endpoint

The FastAPI app exposes metrics at `/metrics` in Prometheus format, for example:

- HTTP request counts / latencies
- LLM call counts
- YouTube API call metrics
- Rate limiter metrics

You can hit this endpoint via:

```bash
curl -s https://music.<STATIC_IP>.sslip.io/metrics
```

(Use the proper production hostname from the Ingress.)

---

## 4. Grafana

### 4.1 Accessing Grafana

URL:

- **Production Grafana**: `https://grafana.<STATIC_IP>.sslip.io/`

TLS is handled by Traefik + cert-manager via Let’s Encrypt.

### 4.2 Credentials

By default, kube-prometheus-stack creates a Grafana admin Secret:

```bash
sudo k3s kubectl get secret -n monitoring | grep grafana
sudo k3s kubectl get secret kps-grafana -n monitoring -o jsonpath='{.data.admin-user}' | base64 -d; echo
sudo k3s kubectl get secret kps-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Use these values as:

- Username: `<admin-user>`
- Password: `<admin-password>`

You should change the password after first login.

### 4.3 Data Source

kube-prometheus-stack auto-configures a **Prometheus** data source:

- Name: typically `Prometheus`
- URL: internal service (`http://kps-kube-prometheus-stack-prometheus:9090`)

You can see it under **Configuration → Data sources** in Grafana.

### 4.4 Dashboards

The chart ships multiple pre-built dashboards for:

- Kubernetes / Nodes
- Kubelet
- API Server
- etc.

To create a **custom dashboard for the yt-llm app**:

1. Log into Grafana.
2. Go to **Dashboards → New → New Dashboard**.
3. Click **Add a new panel**.
4. Select the **Prometheus** data source.
5. Enter a PromQL query, for example:

   ```promql
   sum(rate(http_requests_total{app="yt-llm"}[5m]))
   ```

6. Set a title like **yt-llm – Request Rate**.
7. Click **Apply**, then **Save dashboard** (give it a clear name, e.g. *yt-llm App Overview*).

You can add more panels, such as:

- **LLM request count** (if exported)
- **LLM latency** histogram
- **Error rate** (HTTP 5xx)
- **CPU / Memory usage** of the pod (`container_cpu_usage_seconds_total`, `container_memory_usage_bytes`).

---

## 5. Prometheus

### 5.1 Accessing Prometheus UI (optional)

Prometheus is exposed as a **ClusterIP** only (for safety). To access its UI, use port-forwarding from your local machine:

```bash
# From your laptop:
ssh -i ~/.ssh/yt-llm-k3s -L 9090:localhost:9090 debian@<STATIC_IP>

# Then on the VM:
sudo k3s kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090
```

Now open in your browser:

- `http://localhost:9090`

### 5.2 Querying Metrics

In the Prometheus UI, you can run queries such as:

- `up{job="kubernetes-apiservers"}` – API server health
- `up{app="yt-llm"}` – app scrape status
- `sum(rate(http_requests_total{app="yt-llm"}[5m]))` – request rate

If `up{app="yt-llm"}` always returns `1`, Prometheus is scraping the app successfully.

---

## 6. Alerting

### 6.1 Alertmanager

Alertmanager is installed as part of kube-prometheus-stack:

- Service: `kps-kube-prometheus-stack-alertmanager`
- Name: `alertmanager-kps-kube-prometheus-stack-alertmanager-0` (pod)

By default, the chart includes a set of **Kubernetes alerts**, such as:

- Node down
- API server down
- High memory/CPU usage
- etc.

These are managed via:

- `PrometheusRule` resources in the `monitoring` namespace.

You can list them with:

```bash
sudo k3s kubectl get prometheusrule -n monitoring
```

### 6.2 Custom Alerts (future work)

For production, you can add custom alerts for the yt-llm app, e.g.:

- High error rate for `/suggest` endpoint
- No successful LLM calls in last 10 minutes
- Slow responses (> X seconds)

This is done by adding a `PrometheusRule` resource that references the yt-llm metrics. Example skeleton:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: yt-llm-rules
  namespace: monitoring
  labels:
    release: kps
spec:
  groups:
    - name: yt-llm.rules
      rules:
        - alert: YtLlmHighErrorRate
          expr: |
            sum(rate(http_requests_total{app="yt-llm",status=~"5.."}[5m]))
            /
            sum(rate(http_requests_total{app="yt-llm"}[5m])) > 0.05
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High error rate on yt-llm"
            description: "More than 5% of requests are failing over the last 5 minutes."
```

Notification integrations (email, Slack, etc.) are configured in Alertmanager’s configuration. For this project, **in-cluster alert visibility** (via the Alertmanager UI) is sufficient to meet the capstone requirements.

---

## 7. Health Checks & Readiness

The app defines:

- **`/healthz`** – used by:
  - Kubernetes liveness & readiness probes
  - CI/CD health checks after deployment
- **`/metrics`** – used by Prometheus’ ServiceMonitor

Kubernetes config (from the Deployment):

```yaml
readinessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 20
```

This ensures:

- Pods are only added to the service when healthy.
- Broken pods are restarted automatically.
- CI/CD rollouts are blocked/rolled back if health checks fail.

---

## 8. How This Meets the Requirements

- **Observability**: Centralized metrics with Prometheus and dashboards via Grafana.
- **Health checks**: `/healthz` + probes + CI/CD health checks.
- **Performance metrics**: App metrics exposed via `/metrics` and scraped by Prometheus.
- **Alerting**: Alertmanager deployed and wired to Prometheus rules.
- **Production-style monitoring**: Uses industry-standard Kubernetes monitoring patterns (kube-prometheus-stack, ServiceMonitor, PrometheusRule).

This setup is fully automated via Ansible and Helm and rebuilt on every CI/CD deployment, ensuring reproducible and production-style monitoring.
