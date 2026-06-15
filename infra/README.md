# k8s-logviewer — Test Infrastructure

Local Kubernetes cluster with five dummy microservices that generate realistic,
interacting log output — the test harness for `k8s-logviewer`.

## Prerequisites

**Docker Desktop** must be installed and running before anything else.
Download from https://www.docker.com/products/docker-desktop/

`k3d` and `kubectl` are installed automatically by `setup.sh` if not present
(via Homebrew on Mac, or direct download on Linux).

## Quick start

```bash
cd infra
./setup.sh          # one-shot: install deps → create cluster → build → deploy
```

Or, if you already have k3d and kubectl:

```bash
make setup
```

## Services

| Service | Log format | Pace | Highlights |
|---|---|---|---|
| `api-gateway` | JSON | Fast (0.3–3 s) | HTTP method/path/status/latency, rate limit warnings, upstream errors |
| `auth-service` | logfmt | Medium (0.8–2.5 s) | Login events, JWT validation, brute-force detection |
| `user-service` | Timestamped text | Medium (0.7–2 s) | DB queries, cache hit/miss, slow query warnings, CRUD |
| `notification-service` | Nested JSON | Slow (1.5–4 s) | Email bounces/retries, webhook delivery, queue depth |
| `worker` | Bracketed text | Slow+bursty (2–8 s) | Multi-step jobs with progress, failures, scheduled triggers |

Each service runs with **2 replicas** to simulate real multi-pod scenarios
(important for testing the log viewer's interleaving and pod-selection features).

### Log levels in use

`DEBUG`, `INFO`, `WARN`, `ERROR` — all services emit all levels to give you
something to filter and highlight.

### Good filter/monitor test cases

| Pattern | What it hits |
|---|---|
| `ERROR` | Cross-service errors (DB failures, provider errors, job failures) |
| `WARN` | Rate limits, slow queries, bounces, brute force |
| `brute force` | Auth-service attack detection |
| `slow query` | User-service DB performance warnings |
| `job failed` | Worker job failures |
| `req-` | Any request ID (for tracing a request across services) |
| `usr-10042` | A specific user across all services |

## Make targets

```bash
make setup          # full setup
make build          # rebuild images only
make load           # rebuild + import into k3d
make deploy         # re-apply manifests
make status         # kubectl get pods
make logs           # tail all services
make logs SERVICE=auth-service  # tail one service
make restart        # rolling restart all deployments
make teardown       # delete cluster
```

## Rebuilding after code changes

```bash
make load    # rebuilds images and re-imports
make deploy  # re-applies manifests (triggers rolling update)
```
