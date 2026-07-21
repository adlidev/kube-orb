# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Release process

Releases are built and published automatically by `.github/workflows/publish.yml`.

**To cut a release:**
1. Bump `version` in `pyproject.toml`
2. Commit and push to `main`
3. Create and publish a GitHub Release (tag e.g. `v1.1.0`) — the workflow triggers automatically, runs the test matrix, then builds and publishes to PyPI

**Manual re-run:** if a publish job fails (e.g. transient PyPI error), re-run it via GitHub Actions → workflow_dispatch without cutting a new release.

**⚠️ One-time PyPI setup required** — publishing will fail with an auth error until this workflow is registered as a Trusted Publisher on PyPI:
- pypi.org → kube-orb project → Manage → Publishing → "Add a new publisher"
- Owner: `adlidev`
- Repository: `kube-orb`
- Workflow filename: `publish.yml`
- Environment name: *(leave blank)*

## Commands

```bash
# Install in editable mode (sets up both entry points)
# NOTE: dev deps are a PEP 735 dependency group, not an extra — `.[dev]`
# silently installs nothing (pip just warns "does not provide the extra").
pip install -e . --group dev
# or with uv:
uv pip install -e . --group dev

# Run the TUI app (dev mode with live reload via textual-dev)
hatch run dev
# or directly:
textual run --dev src/kube_orb/__main__.py

# Run the app normally
kube-orb

# Run all tests
pytest
# or via hatch:
hatch run test

# Run a single test file
pytest tests/test_config.py

# Run a single test class or method
pytest tests/test_config.py::TestParseStringInput::test_comma_separated
```

### Test infrastructure (local k8s cluster)

```bash
cd infra
./setup.sh              # one-shot: install deps, create k3d cluster, build, deploy
make build              # rebuild Docker images for all services
make load               # rebuild + import into k3d
make deploy             # re-apply k8s manifests
make status             # kubectl get pods
make logs               # tail all services
make logs SERVICE=worker  # tail one service
make restart            # rolling restart all deployments
make teardown           # delete k3d cluster
```

The test cluster runs in the `logviewer-dev` namespace with 8 services (`api-gateway`, `auth-service`, `user-service`, `notification-service`, `worker`, `database`, `cache`, `scheduler`), each with 2 replicas.

## Architecture

kube-orb is a **Textual TUI** app with two entry points:

- `kube-orb` (`src/kube_orb/cli.py`) — main CLI. If enough args are provided, launches the viewer directly; otherwise falls through to the wizard.
- `kube-orb-inject` (`src/kube_orb/inject.py`) — test utility that writes messages to a pod's stdout via `kubectl exec`, causing them to appear in the live log stream.

### Data flow

```
CLI args / Wizard
       ↓
  SessionConfig          (models.py)
       ↓
  ViewerApp              (viewer/app.py)
       ↓ asyncio workers (one per pod)
  kubectl.stream_logs()  (kubectl.py)  — async subprocess, kubectl logs -f
       ↓ LogLine objects
  _ingest() → filter → _deliver_to_panels()
       ↓
  MainStreamPanel / MonitorPanel / HealthPanel / SearchPanel
```

### Key modules

| Module | Purpose |
|---|---|
| `models.py` | All shared dataclasses: `SessionConfig`, `LogLine`, `Deployment`, `Pod`, `PodStatus`, `HealthConfig` |
| `kubectl.py` | All Kubernetes interaction via subprocess `kubectl`. No Python k8s client. `stream_logs()` is an async generator; `dump_logs()` is one-shot. `stream_logs()` normalizes `since` to `"1s"` when unset or all-zero (`_normalize_since()`), so a live session only collects new lines instead of replaying the pod's full buffered history — kubectl treats an all-zero `--since` identically to omitting it entirely ("no limit"), so `"0s"` would silently dump full history; `dump_logs()` has no such default (unset `since` = full history). |
| `config.py` | Persists session configs to `~/.config/kube-orb/namespaces/<ns>/<name>.yaml` and global saved strings to `~/.config/kube-orb/strings.yaml`. Also owns pattern compilation: plain strings are `re.escape`d; `/regex/`-wrapped strings compile as real regex. |
| `colors.py` | Assigns a distinct ANSI/CSS color to each pod name. |
| `jsonlog.py` | Detects single-JSON-object log lines and extracts level/message/timestamp (checking a few conventional key names) for the optional readable-formatting toggle. Detection runs regardless of the toggle, since the Enter-for-detail view needs it too. |
| `viewer/app.py` | `ViewerApp` — the main Textual `App`. Owns the log buffer, pause state, pattern state, and pod/deployment lifecycle. |
| `viewer/panels/` | Four panels: `MainStreamPanel` (primary log display), `SearchPanel` (live search), `MonitorPanel` (passive pattern accumulation), `HealthPanel` (restart/health alerts). |
| `viewer/widgets.py` | Shared widgets: `StringEditModal` (F/H/M editing), `SaveDialog`, `PodSelectorModal`, `PaneSizeModal`, `JsonDetailModal`, `MonitorContextModal`. |
| `wizard/` | Three-tab Textual wizard (`SinglePageWizard` screen) — Targets → Strings → Options — produces a `SessionConfig`. |

### Pattern matching

Filters, highlights, and monitors all share the same matching syntax (in `config.py`):
- Plain strings are matched as literals (dots and special chars are escaped).
- `/pattern/` strings are compiled as regex.
- Comma-separated input is parsed by `parse_string_input()`.

### Package layout

`src/kube_orb/` is the canonical source package. The legacy `src/kube_illume/` directory has been removed after migrating the tests and imports to `kube_orb`.

### Test infrastructure services

`infra/services/` contains simple Python Flask/HTTP servers that generate realistic, interleaved log output in different formats (JSON, logfmt, bracketed text). They are built into Docker images and deployed to a local k3d cluster to serve as live test targets for kube-orb.
