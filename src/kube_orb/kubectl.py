"""
kubectl abstraction layer.

All Kubernetes interaction goes through this module via subprocess calls to
the user's existing kubectl binary (inheriting their kubeconfig and auth).
No Python k8s client dependency — works with any cluster, any auth method.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from collections.abc import AsyncIterator
from datetime import datetime

from .models import Deployment, LogLine, Pod, PodStatus


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _run(args: list[str], check: bool = True) -> str:
    """Run a kubectl command, return stdout as str. Raises on non-zero exit."""
    result = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=check,
    )
    return result.stdout.strip()


def _run_json(args: list[str]) -> dict | list:
    """Run kubectl with -o json and return parsed output."""
    return json.loads(_run([*args, "-o", "json"]))


# kubectl --timestamps=true prefixes each line with an RFC3339Nano timestamp
# (up to 9 fractional-second digits) and a space, e.g.
# "2026-07-08T12:34:56.789012345Z log line content here".
_TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2}) "
)


def _split_timestamp(raw: str) -> tuple[datetime | None, str]:
    """
    Split a kubectl --timestamps=true line into (parsed timestamp, content).
    Returns (None, raw) unchanged if the line doesn't start with a
    recognizable timestamp (defensive — should always match in practice).
    """
    m = _TIMESTAMP_RE.match(raw)
    if not m:
        return None, raw
    base, frac, tz = m.groups()
    # datetime.fromisoformat only accepts up to microsecond (6-digit)
    # precision on Python 3.10/3.11; truncate rather than pad-and-fail.
    frac = (frac or "").ljust(6, "0")[:6]
    tz = "+00:00" if tz == "Z" else tz
    try:
        timestamp = datetime.fromisoformat(f"{base}.{frac}{tz}")
    except ValueError:
        return None, raw
    return timestamp, raw[m.end():]


# A --since value that is zero in every unit ("0", "0s", "0h", "00", ...).
# Doesn't attempt to parse compound durations like "0h0m0s" -- not something
# anyone hand-types; the realistic cases are a single zero, bare or with one
# unit suffix.
_ZERO_SINCE_RE = re.compile(r"^0+(?:\.0+)?(ns|us|µs|ms|s|m|h)?$")


def _normalize_since(since: str | None) -> str:
    """
    kubectl (Go's duration parser) treats an all-zero --since value exactly
    like omitting the flag: "no time limit", not "since right now" — it
    silently replays a pod's ENTIRE buffered history instead of only new
    lines. Confirmed directly against a live cluster: --since 0s, --since 0,
    and no --since flag at all all return identical output; --since 1s
    correctly returns nothing already logged.

    Substitute a tiny positive duration for None/empty/zero, so both the
    "leave since blank" default and a user typing a literal "0" get the
    "only new lines" behavior they actually asked for, instead of an
    unbounded history dump.
    """
    if not since or _ZERO_SINCE_RE.match(since.strip()):
        return "1s"
    return since


def wants_backfill(since: str | None) -> bool:
    """
    True if `since` represents a genuine, non-trivial look-back window —
    i.e. whether the caller should expect (and handle) a historical
    backfill burst. Mirrors _normalize_since()'s zero-detection, so a user
    typing a literal "0" doesn't trigger backfill-merge handling (which
    waits for pods to "catch up") for a window kubectl will treat as empty
    anyway — see stream_logs().
    """
    return bool(since) and not _ZERO_SINCE_RE.match(since.strip())


# ─── Context / namespace ─────────────────────────────────────────────────────

def get_current_namespace() -> str:
    """
    Return the namespace set in the active kubectl context.
    Falls back to 'default' if none is configured.
    """
    try:
        ns = _run([
            "config", "view",
            "--minify",
            "-o", "jsonpath={.contexts[0].context.namespace}",
        ])
        return ns or "default"
    except subprocess.CalledProcessError:
        return "default"


def get_namespaces() -> list[str]:
    """Return all namespace names the user can see."""
    data = _run_json(["get", "namespaces"])
    return [item["metadata"]["name"] for item in data.get("items", [])]


# ─── Deployments / pods ──────────────────────────────────────────────────────

def get_deployments(namespace: str) -> list[Deployment]:
    """
    Return deployments in the namespace, each with pod count and label selector.
    """
    data = _run_json(["get", "deployments", "-n", namespace])
    deployments = []
    for item in data.get("items", []):
        name = item["metadata"]["name"]
        selector = item["spec"].get("selector", {}).get("matchLabels", {})
        replicas = item["status"].get("availableReplicas") or 0
        deployments.append(Deployment(
            name=name,
            namespace=namespace,
            pod_count=replicas,
            selector=selector,
        ))
    return sorted(deployments, key=lambda d: d.name)


def get_pods_for_deployment(namespace: str, deployment: Deployment) -> list[Pod]:
    """Return pods matching a deployment's label selector."""
    selector = ",".join(f"{k}={v}" for k, v in deployment.selector.items())
    return _get_pods_by_selector(namespace, selector, deployment.name)


def get_pods_for_deployments(namespace: str, deployments: list[Deployment]) -> list[Pod]:
    """Return all pods across a list of deployments."""
    pods: list[Pod] = []
    for dep in deployments:
        pods.extend(get_pods_for_deployment(namespace, dep))
    return pods


def _get_pods_by_selector(namespace: str, selector: str, deployment_name: str) -> list[Pod]:
    data = _run_json(["get", "pods", "-n", namespace, "-l", selector])
    pods = []
    for item in data.get("items", []):
        name = item["metadata"]["name"]
        phase = item["status"].get("phase", "Unknown")
        ready = _pod_ready(item)
        restarts = _pod_restart_count(item)
        pods.append(Pod(
            name=name,
            namespace=namespace,
            deployment=deployment_name,
            phase=phase,
            restart_count=restarts,
            ready=ready,
        ))
    return pods


def _pod_ready(item: dict) -> bool:
    for cond in item.get("status", {}).get("conditions", []):
        if cond.get("type") == "Ready":
            return cond.get("status") == "True"
    return False


def _pod_restart_count(item: dict) -> int:
    total = 0
    for cs in item.get("status", {}).get("containerStatuses", []):
        total += cs.get("restartCount", 0)
    return total


# ─── Pod health polling ───────────────────────────────────────────────────────

def get_pod_statuses(namespace: str, pod_names: list[str]) -> list[PodStatus]:
    """
    Poll current health for a specific list of pod names.
    Used by the health panel on its interval.
    """
    if not pod_names:
        return []

    data = _run_json(["get", "pods", "-n", namespace])
    statuses = []
    name_set = set(pod_names)

    for item in data.get("items", []):
        name = item["metadata"]["name"]
        if name not in name_set:
            continue

        phase = item["status"].get("phase", "Unknown")
        ready = _pod_ready(item)
        restarts = _pod_restart_count(item)

        # Age: seconds since pod started
        start_str = item["status"].get("startTime")
        if start_str:
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            age = (datetime.now(start.tzinfo) - start).total_seconds()
        else:
            age = 0.0

        # Owning deployment (best-effort via labels)
        labels = item["metadata"].get("labels", {})
        deployment = (
            labels.get("app")
            or labels.get("app.kubernetes.io/name")
            or name.rsplit("-", 2)[0]   # fallback: strip pod hash suffix
        )

        statuses.append(PodStatus(
            name=name,
            deployment=deployment,
            phase=phase,
            restart_count=restarts,
            ready=ready,
            age_seconds=age,
        ))

    return statuses


# ─── Log streaming ────────────────────────────────────────────────────────────

async def stream_logs(
    pod_name: str,
    namespace: str,
    since: str | None = None,
    tail: int | None = None,
) -> AsyncIterator[LogLine]:
    """
    Async generator yielding LogLine objects from a single pod.
    Runs kubectl logs -f in a subprocess, reads lines as they arrive.
    Caller should run one coroutine per pod and merge with asyncio.

    NOTE: unlike dump_logs(), `since` is never sent as an all-zero value
    here (see _normalize_since) when unset. Without a meaningful --since
    bound, `kubectl logs -f` first dumps the pod's entire buffered history
    before it starts following — for a live stream that means a session,
    by default, only collects new lines from the moment it starts rather
    than replaying everything. Pass an explicit `since` (e.g. "1h") to opt
    into a look-back window instead.

    Requests --timestamps=true so each LogLine gets a real log_timestamp
    (see models.LogLine) — used to interleave a backfill burst across pods
    correctly. The timestamp is parsed and stripped back out of `content`,
    so displayed/matched text is identical to what --timestamps=false would
    have produced.
    """
    args = ["kubectl", "logs", "-f", pod_name, "-n", namespace, "--timestamps=true"]
    args += ["--since", _normalize_since(since)]
    if tail is not None:
        args += ["--tail", str(tail)]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    assert proc.stdout is not None
    try:
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            raw = line_bytes.decode(errors="replace").rstrip("\n")
            log_time, content = _split_timestamp(raw)
            yield LogLine(
                pod_name=pod_name,
                content=content,
                log_timestamp=log_time,
            )
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


async def dump_logs(
    pod_name: str,
    namespace: str,
    since: str | None = None,
    tail: int | None = None,
) -> list[LogLine]:
    """
    Fetch a bounded set of log lines from a pod (no follow).
    Used in dump mode.
    """
    args = ["kubectl", "logs", pod_name, "-n", namespace, "--timestamps=false"]
    if since:
        args += ["--since", since]
    if tail is not None:
        args += ["--tail", str(tail)]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    lines = stdout.decode(errors="replace").splitlines()
    return [LogLine(pod_name=pod_name, content=line) for line in lines if line]


# ─── Pod restart actions ──────────────────────────────────────────────────────

def delete_pod(pod_name: str, namespace: str) -> bool:
    """
    Delete a pod immediately (deployment controller will recreate it).
    Returns True on success.
    """
    try:
        _run(["delete", "pod", pod_name, "-n", namespace, "--grace-period=0"])
        return True
    except subprocess.CalledProcessError:
        return False


def rollout_restart(deployment_name: str, namespace: str) -> bool:
    """
    Graceful rolling restart of a deployment.
    Returns True on success.
    """
    try:
        _run(["rollout", "restart", f"deployment/{deployment_name}", "-n", namespace])
        return True
    except subprocess.CalledProcessError:
        return False
