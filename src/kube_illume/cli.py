"""
CLI entry point for kube-illume.

If enough arguments are provided to fully specify a session, the viewer
launches directly. Otherwise (or with --wizard), the interactive wizard runs.
"""
from __future__ import annotations

import sys

import click

from .models import HealthConfig, LogMode, SessionConfig


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-n", "--namespace", default=None,
              help="Kubernetes namespace (default: current kubectl context namespace).")
@click.option("-p", "--pod", "pods", multiple=True, metavar="NAME",
              help="Deployment name to watch. Repeatable. Use multiple times for multiple services.")
@click.option("--all-pods", is_flag=True,
              help="Watch all deployments in the namespace.")
@click.option("--stream", "mode", flag_value="stream", default=True,
              help="Live tail mode (default).")
@click.option("--dump", "mode", flag_value="dump",
              help="Fetch existing logs and exit. No live stream.")
@click.option("--tail", type=int, default=None, metavar="N",
              help="(Dump mode) Last N lines to fetch.")
@click.option("--since", default=None, metavar="DURATION",
              help="(Dump mode) Fetch logs from this far back, e.g. 1h, 30m.")
@click.option("-c", "--config", "config_name", default=None, metavar="NAME",
              help="Load a saved config by name (scoped to namespace).")
@click.option("--save-config", default=None, metavar="NAME",
              help="Save this session's config under NAME before launching.")
@click.option("-f", "--filter", "filters", multiple=True, metavar="PATTERN",
              help="Hide lines matching PATTERN. Repeatable. Use /regex/ for regex.")
@click.option("-H", "--highlight", "highlights", multiple=True, metavar="PATTERN",
              help="Highlight lines matching PATTERN. Repeatable.")
@click.option("-m", "--monitor", "monitors", multiple=True, metavar="PATTERN",
              help="(Stream mode) Collect matching lines in monitor panel. Repeatable.")
@click.option("--health", is_flag=True,
              help="(Stream mode) Enable pod health monitoring panel.")
@click.option("--health-interval", type=int, default=5, show_default=True, metavar="MINUTES",
              help="Pod health check interval in minutes (min 1).")
@click.option("--health-restart-threshold", type=int, default=1, show_default=True,
              metavar="N", hidden=True,
              help="Show pods in health panel when restart delta >= N (default 1).")
@click.option("--wizard", is_flag=True,
              help="Force the interactive setup wizard even if all args are provided.")
def main(
    namespace: str | None,
    pods: tuple[str, ...],
    all_pods: bool,
    mode: str,
    tail: int | None,
    since: str | None,
    config_name: str | None,
    save_config: str | None,
    filters: tuple[str, ...],
    highlights: tuple[str, ...],
    monitors: tuple[str, ...],
    health: bool,
    health_interval: int,
    health_restart_threshold: int,
    wizard: bool,
) -> None:
    """
    kube-illume — Interactive Kubernetes log viewer.

    Run with no arguments to launch the setup wizard.
    Provide --namespace and --pod flags to skip the wizard.

    \b
    Examples:
      kube-illume                                    # wizard
      kube-illume -n production -p api-gateway -p auth-service --stream
      kube-illume -n staging --dump --tail 500
      kube-illume -n default -p worker -f DEBUG -H ERROR --health
    """
    from . import kubectl as k
    from .config import (
        add_to_saved_strings,
        load_session_config,
        parse_string_input,
        save_session_config,
    )

    # ── Resolve namespace ────────────────────────────────────────────────────
    if namespace is None:
        namespace = k.get_current_namespace()

    # ── Decide: wizard or direct launch ─────────────────────────────────────
    needs_wizard = wizard or (not pods and not all_pods and not config_name)
    if needs_wizard:
        _run_wizard(namespace)
        return

    # ── Load saved config (pre-fill) ─────────────────────────────────────────
    session: SessionConfig | None = None
    if config_name:
        session = load_session_config(namespace, config_name)
        if session is None:
            click.echo(f"No saved config '{config_name}' found for namespace '{namespace}'.",
                       err=True)
            sys.exit(1)

    # ── Build / override SessionConfig ───────────────────────────────────────
    # CLI flags override anything from the loaded config
    if session is None:
        session = SessionConfig(namespace=namespace, deployments=[])

    if pods:
        session.deployments = list(pods)
    elif all_pods:
        session.deployments = [d.name for d in k.get_deployments(namespace)]

    session.mode = LogMode(mode)
    if tail is not None:
        session.tail = tail
    if since is not None:
        session.since = since

    # Merge CLI strings with any loaded-config strings
    def _merge(existing: list[str], incoming: tuple[str, ...]) -> list[str]:
        extra: list[str] = []
        for raw in incoming:
            extra.extend(parse_string_input(raw))
        return existing + [s for s in extra if s not in existing]

    session.filters    = _merge(session.filters,    filters)
    session.highlights = _merge(session.highlights, highlights)
    session.monitors   = _merge(session.monitors,   monitors)

    if health:
        session.health.enabled = True
    session.health.interval_minutes = max(1, health_interval)
    session.health.restart_threshold = health_restart_threshold

    # ── Validate ─────────────────────────────────────────────────────────────
    if not session.deployments:
        click.echo("No deployments specified. Use --pod NAME or --all-pods.", err=True)
        sys.exit(1)

    # ── Optionally save config ────────────────────────────────────────────────
    if save_config:
        session.name = save_config
        save_session_config(session)
        click.echo(f"Config saved as '{save_config}' for namespace '{namespace}'.")

    # ── Launch viewer ─────────────────────────────────────────────────────────
    _run_viewer(session)


def _run_wizard(namespace: str) -> None:
    from .wizard.app import WizardApp
    app = WizardApp(initial_namespace=namespace)
    result = app.run()
    if result is None:
        # User cancelled
        sys.exit(0)
    _run_viewer(result)


def _run_viewer(config: SessionConfig) -> None:
    from .viewer.app import ViewerApp
    app = ViewerApp(config=config)
    app.run()
