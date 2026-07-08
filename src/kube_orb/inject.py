"""
kube-orb-inject — test utility for injecting log messages into running pods.

Writes directly to the pod's stdout via kubectl exec so the message appears
in the live log stream exactly like a real log line.

Usage:
  kube-orb-inject                          # interactive: pick pod, loop for messages
  kube-orb-inject -n logviewer-dev -d api-gateway -m "ERROR: test error"
  kube-orb-inject -n logviewer-dev -p api-gateway-xyz-abc -m "WARN: test"
"""
from __future__ import annotations

import subprocess
import sys

import click


def _list_pods(namespace: str) -> list[tuple[str, str]]:
    """Return list of (pod_name, deployment_name) tuples."""
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", namespace,
         "-o", "custom-columns=NAME:.metadata.name,DEPLOY:.metadata.labels.app",
         "--no-headers"],
        capture_output=True, text=True,
    )
    pods = []
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            pods.append((parts[0], parts[1]))
    return pods


def _resolve_pod(namespace: str, deployment: str | None, pod: str | None) -> str | None:
    """Resolve a specific pod name from either a deployment name or direct pod name."""
    if pod:
        return pod

    pods = _list_pods(namespace)
    if not pods:
        return None

    if deployment:
        matches = [p for p, d in pods if d == deployment]
        if not matches:
            click.echo(f"No pods found for deployment '{deployment}'.", err=True)
            return None
        # Pick the first one (could add round-robin later)
        return matches[0]

    return None


def _inject(namespace: str, pod_name: str, message: str, prefix: str) -> bool:
    """Write a message to the pod's stdout. Returns True on success."""
    full_message = f"{prefix}{message}" if prefix else message
    # Write to /proc/1/fd/1 — the main process's stdout fd — so it appears in kubectl logs
    result = subprocess.run(
        ["kubectl", "exec", pod_name, "-n", namespace, "--",
         "sh", "-c", f"echo '{full_message}' > /proc/1/fd/1"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo(f"Inject failed: {result.stderr.strip()}", err=True)
        return False
    return True


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-n", "--namespace", default=None,
              help="Kubernetes namespace (default: current kubectl context).")
@click.option("-d", "--deployment", default=None, metavar="NAME",
              help="Deployment name — a pod from this deployment will be chosen.")
@click.option("-p", "--pod", default=None, metavar="NAME",
              help="Exact pod name to inject into.")
@click.option("-m", "--message", "messages", multiple=True, metavar="MSG",
              help="Message(s) to inject. Omit for interactive mode.")
@click.option("--prefix", default="[TEST] ", show_default=True,
              help="Prefix prepended to every injected message.")
@click.option("--no-prefix", is_flag=True,
              help="Suppress the prefix entirely.")
def main(
    namespace: str | None,
    deployment: str | None,
    pod: str | None,
    messages: tuple[str, ...],
    prefix: str,
    no_prefix: bool,
) -> None:
    """
    Inject log messages into a running pod for testing kube-orb filters/monitors.

    Messages are written to the pod's stdout so they appear in the live log stream.

    \b
    Examples:
      kube-orb-inject                                        # fully interactive
      kube-orb-inject -d api-gateway -m "ERROR: test"
      kube-orb-inject -d worker -m "job failed" -m "OOM killed"
      kube-orb-inject -p api-gateway-7d9f-xkcd --no-prefix -m "raw message"
    """
    from . import kubectl as k

    if no_prefix:
        prefix = ""

    # Resolve namespace
    if namespace is None:
        namespace = k.get_current_namespace()

    # If neither deployment nor pod given, show a picker
    if not deployment and not pod:
        pods = _list_pods(namespace)
        if not pods:
            click.echo(f"No pods found in namespace '{namespace}'.", err=True)
            sys.exit(1)

        click.echo(f"\nPods in namespace '{namespace}':\n")
        for i, (pname, dname) in enumerate(pods):
            click.echo(f"  [{i}] {pname}  ({dname})")
        click.echo()

        choice = click.prompt("Select pod number", type=int)
        if choice < 0 or choice >= len(pods):
            click.echo("Invalid choice.", err=True)
            sys.exit(1)
        pod = pods[choice][0]

    # Resolve to a specific pod name
    target_pod = _resolve_pod(namespace, deployment, pod)
    if not target_pod:
        click.echo("Could not resolve a target pod.", err=True)
        sys.exit(1)

    click.echo(f"Injecting into pod: {target_pod}  (namespace: {namespace})")
    click.echo(f"Prefix: '{prefix}'\n")

    # One-shot mode
    if messages:
        for msg in messages:
            ok = _inject(namespace, target_pod, msg, prefix)
            if ok:
                click.echo(f"  ✓ {prefix}{msg}")
        return

    # Interactive loop
    click.echo("Interactive mode — type a message and press Enter. Ctrl+C to quit.\n")
    while True:
        try:
            msg = click.prompt("Message")
            ok = _inject(namespace, target_pod, msg, prefix)
            if ok:
                click.echo(f"  ✓ Injected")
        except (click.Abort, KeyboardInterrupt):
            click.echo("\nDone.")
            break
