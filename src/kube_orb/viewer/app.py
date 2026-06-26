"""
Main viewer application.

Launches with a SessionConfig and wires together:
  - One log-streaming coroutine per pod (or a dump loader)
  - MainStreamPanel  — the primary log display
  - SearchPanel      — live search
  - MonitorPanel     — passive string accumulation  (stream mode only)
  - HealthPanel      — pod health alerts            (stream mode only)
  - String-editing overlays for E / H / M keybinds
  - Ctrl+S save-to-file dialog
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header

from ..colors import assign_colors
from ..config import compile_patterns, matches
from ..models import LogLine, LogMode, SessionConfig
from .panels.health import HealthPanel
from .panels.main_stream import MainStreamPanel
from .panels.monitor import MonitorPanel
from .panels.search import SearchPanel
from .widgets import SaveDialog, StringEditBar


class ViewerApp(App):
    """The log viewer."""

    TITLE = "kube-orb"
    CSS_PATH = "viewer.tcss"

    BINDINGS = [
        Binding("e",       "edit_filters",    "Edit excludes",   show=True),
        Binding("h",       "edit_highlights", "Edit highlights", show=True),
        Binding("m",       "edit_monitors",   "Edit monitors",   show=True),
        Binding("space",   "toggle_pause",    "Pause / Resume",  show=True),
        Binding("ctrl+s",  "save_logs",       "Save logs",       show=True),
        Binding("c",       "collapse_panel",  "Collapse panel",  show=True),
        Binding("ctrl+c",  "quit",            "Quit",            show=True),
        Binding("/",       "toggle_search",   "Search",          show=True),
        Binding("t",       "toggle_color",    "Color mode",      show=True),
    ]

    def __init__(self, config: SessionConfig) -> None:
        super().__init__()
        self._config = config
        self._is_stream = config.mode == LogMode.STREAM

        # Compiled match patterns — updated live when user edits strings
        self._filter_patterns:    list[re.Pattern] = compile_patterns(config.filters)
        self._highlight_patterns: list[re.Pattern] = compile_patterns(config.highlights)
        self._monitor_patterns:   list[re.Pattern] = compile_patterns(config.monitors)

        # Full log buffer (all lines received, post-filter applied at display time)
        self._buffer: list[LogLine] = []

        # Pod → color mapping
        self._color_map: dict[str, str] = {}

        self._paused = False
        self._pending_lines: list[LogLine] = []   # buffered while paused

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="panels"):
            yield MainStreamPanel(id="main-stream")
            yield SearchPanel(id="search-panel")
            if self._is_stream:
                yield MonitorPanel(id="monitor-panel")
                yield HealthPanel(
                    config=self._config.health,
                    id="health-panel",
                )
        yield StringEditBar(id="edit-bar")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one(SearchPanel).display = False
        self.query_one(MainStreamPanel).set_color_mode(self._config.color_full_line)

        from .. import kubectl as k

        # Resolve pods from selected deployments
        deployments = k.get_deployments(self._config.namespace)
        dep_map = {d.name: d for d in deployments}
        selected_deps = [dep_map[n] for n in self._config.deployments if n in dep_map]
        pods = k.get_pods_for_deployments(self._config.namespace, selected_deps)

        if not pods:
            self.notify("No pods found for selected deployments.", severity="error")
            return

        self._color_map = assign_colors([p.name for p in pods])

        if self._is_stream:
            # Launch one streaming task per pod
            for pod in pods:
                self.run_worker(
                    self._stream_pod(pod.name),
                    name=f"stream-{pod.name}",
                    exclusive=False,
                )
            # Start health polling if enabled
            if self._config.health.enabled:
                pod_names = [p.name for p in pods]
                self.run_worker(
                    self._poll_health(pod_names),
                    name="health-poll",
                )
        else:
            self.run_worker(self._load_dump(pods), name="dump-loader")

    # ── Log ingestion ──────────────────────────────────────────────────────────

    async def _stream_pod(self, pod_name: str) -> None:
        from .. import kubectl as k
        async for line in k.stream_logs(
            pod_name,
            self._config.namespace,
            since=self._config.since,
            tail=self._config.tail,
        ):
            self._ingest(line)

    async def _load_dump(self, pods) -> None:
        from .. import kubectl as k
        all_lines: list[LogLine] = []
        for pod in pods:
            lines = await k.dump_logs(
                pod.name,
                self._config.namespace,
                since=self._config.since,
                tail=self._config.tail,
            )
            all_lines.extend(lines)
        # Sort by receive time (they each have received_at from when fetched)
        all_lines.sort(key=lambda l: l.received_at)
        for line in all_lines:
            self._ingest(line)

    def _ingest(self, line: LogLine) -> None:
        """Process one incoming log line through filters and routing."""
        # Apply exclusion filter
        if self._filter_patterns and matches(line.content, self._filter_patterns):
            return

        self._buffer.append(line)

        if self._paused:
            self._pending_lines.append(line)
            self._update_pause_indicator()
            return

        self._deliver_to_panels(line)

    def _deliver_to_panels(self, line: LogLine) -> None:
        color = self._color_map.get(line.pod_name, "#ffffff")
        is_highlight = bool(self._highlight_patterns and
                            matches(line.content, self._highlight_patterns))

        self.query_one(MainStreamPanel).add_line(line, color, is_highlight)

        if self._is_stream and self._monitor_patterns:
            if matches(line.content, self._monitor_patterns):
                self.query_one(MonitorPanel).add_line(line, color)

    # ── Pause / resume ─────────────────────────────────────────────────────────

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if not paused and self._pending_lines:
            for line in self._pending_lines:
                self._deliver_to_panels(line)
            self._pending_lines.clear()
        self._update_pause_indicator()

    def _update_pause_indicator(self) -> None:
        n = len(self._pending_lines)
        panel = self.query_one(MainStreamPanel)
        panel.set_paused(self._paused, n)

    # ── Pattern updates (from live string editing) ─────────────────────────────

    def update_filters(self, new_strings: list[str]) -> None:
        self._config.filters = new_strings
        self._filter_patterns = compile_patterns(new_strings)
        # Re-render the main stream with updated filter (rebuild from buffer)
        self._rerender_main_stream()

    def update_highlights(self, new_strings: list[str]) -> None:
        self._config.highlights = new_strings
        self._highlight_patterns = compile_patterns(new_strings)
        self._rerender_main_stream()

    def update_monitors(self, new_strings: list[str]) -> None:
        self._config.monitors = new_strings
        self._monitor_patterns = compile_patterns(new_strings)

    def _rerender_main_stream(self) -> None:
        """Replay buffer through updated filters and highlights."""
        panel = self.query_one(MainStreamPanel)
        panel.clear()
        for line in self._buffer:
            if self._filter_patterns and matches(line.content, self._filter_patterns):
                continue
            color = self._color_map.get(line.pod_name, "#ffffff")
            is_hl = bool(self._highlight_patterns and
                         matches(line.content, self._highlight_patterns))
            panel.add_line(line, color, is_hl)

    # ── Health polling ─────────────────────────────────────────────────────────

    async def _poll_health(self, pod_names: list[str]) -> None:
        from .. import kubectl as k
        interval = max(1, self._config.health.interval_minutes) * 60
        baseline: dict[str, int] = {}   # pod_name → restart count at session start

        while True:
            statuses = k.get_pod_statuses(self._config.namespace, pod_names)
            health_panel = self.query_one(HealthPanel)
            threshold = self._config.health.restart_threshold

            for status in statuses:
                if status.name not in baseline:
                    baseline[status.name] = status.restart_count

                restart_delta = status.restart_count - baseline[status.name]
                is_unhealthy = not status.is_healthy or restart_delta >= threshold

                if is_unhealthy:
                    health_panel.update_pod(status, restart_delta)

            await asyncio.sleep(interval)

    # ── Keybind actions ────────────────────────────────────────────────────────

    def action_toggle_pause(self) -> None:
        if not self._is_stream:
            return
        self.set_paused(not self._paused)

    def action_edit_filters(self) -> None:
        bar = self.query_one(StringEditBar)
        bar.open("filters", self._config.filters, self._on_filters_edited)

    def action_edit_highlights(self) -> None:
        bar = self.query_one(StringEditBar)
        bar.open("highlights", self._config.highlights, self._on_highlights_edited)

    def action_edit_monitors(self) -> None:
        if not self._is_stream:
            return
        bar = self.query_one(StringEditBar)
        bar.open("monitors", self._config.monitors, self._on_monitors_edited)

    def _on_filters_edited(self, new_strings: list[str], save: bool) -> None:
        self.update_filters(new_strings)
        if save:
            from ..config import add_to_saved_strings
            existing = self._config.filters
            truly_new = [s for s in new_strings if s not in existing]
            if truly_new:
                add_to_saved_strings("filters", truly_new)

    def _on_highlights_edited(self, new_strings: list[str], save: bool) -> None:
        self.update_highlights(new_strings)
        if save:
            from ..config import add_to_saved_strings
            existing = self._config.highlights
            truly_new = [s for s in new_strings if s not in existing]
            if truly_new:
                add_to_saved_strings("highlights", truly_new)

    def _on_monitors_edited(self, new_strings: list[str], save: bool) -> None:
        self.update_monitors(new_strings)
        if save:
            from ..config import add_to_saved_strings
            existing = self._config.monitors
            truly_new = [s for s in new_strings if s not in existing]
            if truly_new:
                add_to_saved_strings("monitors", truly_new)

    def action_save_logs(self) -> None:
        ns = self._config.namespace
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"kube-orb-{ns}-{ts}.log"
        self.push_screen(
            SaveDialog(default_name=default_name),
            self._do_save,
        )

    def _do_save(self, path_str: str | None) -> None:
        if not path_str:
            return
        path = Path(path_str)
        lines = [line.display for line in self._buffer]
        try:
            path.write_text("\n".join(lines) + "\n")
            self.notify(f"Saved {len(lines)} lines to {path}", severity="information")
        except OSError as exc:
            self.notify(f"Save failed: {exc}", severity="error")

    def action_toggle_color(self) -> None:
        self._config.color_full_line = not self._config.color_full_line
        panel = self.query_one(MainStreamPanel)
        panel.set_color_mode(self._config.color_full_line)
        self._rerender_main_stream()
        mode = "full line" if self._config.color_full_line else "name only"
        self.notify(f"Color mode: {mode}")

    def action_toggle_search(self) -> None:
        panel = self.query_one(SearchPanel)
        panel.display = not panel.display
        if panel.display:
            panel.query_one("#search-input").focus()

    def action_collapse_panel(self) -> None:
        # Find the focused widget's nearest panel ancestor and toggle it
        focused = self.focused
        if focused is None:
            return
        for panel_cls in (MainStreamPanel, SearchPanel, MonitorPanel, HealthPanel):
            try:
                panel = focused.ancestors_with_self.filter(panel_cls).first()  # type: ignore
                panel.toggle_collapsed()
                return
            except Exception:
                continue

    def action_quit(self) -> None:
        self.exit()

    # ── Cross-panel: line-select jump ─────────────────────────────────────────

    def on_search_panel_line_selected(self, event) -> None:
        self.set_paused(True)
        self.query_one(MainStreamPanel).jump_to_line(event.line)

    def on_monitor_panel_line_selected(self, event) -> None:
        self.set_paused(True)
        self.query_one(MainStreamPanel).jump_to_line(event.line)
