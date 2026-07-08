"""
kubectl abstraction layer.

All Kubernetes interaction goes through this module via subprocess calls to
the user's existing kubectl binary (inheriting their kubeconfig and auth).
No Python k8s client dependency — works with any cluster, any auth method.
"""
from __future__ import annotations

import asyncio
import json
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

    NOTE: unlike dump_logs(), `since` defaults to "0s" here (not omitted)
    when unset. Without a --since bound, `kubectl logs -f` first dumps the
    pod's entire buffered history before it starts following — for a live
    stream that means a session, by default, only collects new lines from
    the moment it starts rather than replaying everything. Pass an explicit
    `since` (e.g. "1h") to opt into a look-back window instead.
    """
    args = ["kubectl", "logs", "-f", pod_name, "-n", namespace, "--timestamps=false"]
    args += ["--since", since or "0s"]
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
            yield LogLine(
                pod_name=pod_name,
                content=line_bytes.decode(errors="replace").rstrip("\n"),
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
