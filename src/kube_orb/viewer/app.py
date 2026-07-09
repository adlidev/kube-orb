"""
Main viewer application.

Launches with a SessionConfig and wires together:
  - One log-streaming coroutine per pod (or a dump loader)
  - MainStreamPanel  — the primary log display
  - SearchPanel      — live search
  - MonitorPanel     — passive string accumulation  (stream mode only)
  - HealthPanel      — pod health alerts            (stream mode only)
  - String-editing overlays for F / H / M keybinds
  - Ctrl+S save-to-file dialog
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Rule

from .. import _scrollbar
from ..colors import assign_colors
from ..config import compile_patterns, matches
from ..models import LogLine, LogMode, SessionConfig
from .panels.health import HealthPanel
from .panels.main_stream import MainStreamPanel
from .panels.monitor import MonitorPanel
from .panels.search import SearchPanel
from .widgets import JsonDetailModal, PaneSizeModal, PodSelectorModal, SaveDialog, StringEditModal

_scrollbar.install()


class ViewerApp(App):
    """The log viewer."""

    TITLE = "kube-orb"
    CSS_PATH = "viewer.tcss"

    # Dragging a side panel's header trades height with MainStreamPanel (the
    # only auto-filling `1fr` panel) — never with a neighboring side panel.
    MAIN_STREAM_MIN_HEIGHT = 20
    SIDE_PANEL_MIN_HEIGHT = 4

    # Force an early backfill flush past this many buffered lines, rather
    # than waiting on every pod to catch up (or the watchdog) — bounds the
    # worst case (e.g. a deliberately long `since` on a very busy pod) to a
    # sort+dispatch of a few thousand lines instead of an unbounded one that
    # could noticeably stall the UI. Below the main buffer's own 20,000 cap
    # since this is meant to catch a burst, not hold a whole session.
    BACKFILL_BUFFER_CAP = 3000

    BINDINGS = [
        Binding("f",       "edit_filters",    "Edit Filters",    show=True,  priority=True),
        Binding("h",       "edit_highlights", "Edit highlights", show=True,  priority=True),
        Binding("m",       "edit_monitors",   "Edit monitors",   show=True,  priority=True),
        Binding("space",   "toggle_pause",    "Pause / Resume",  show=True,  priority=True),
        Binding("ctrl+s",  "save_logs",       "Save logs",       show=True,  priority=True),
        Binding("ctrl+q",  "quit",            "Quit",            show=True,  priority=True),
        Binding("/",       "toggle_search",   "Search",          show=True,  priority=True),
        Binding("t",       "toggle_color",    "Color mode",      show=True,  priority=True),
        Binding("w",       "toggle_wrap",     "Wrap",            show=True,  priority=True),
        Binding("p",       "manage_pods",     "Pods",            show=True,  priority=True),
        Binding("l",       "edit_layout",     "Pane sizes",      show=True,  priority=True),
        Binding("j",       "toggle_json",     "JSON format",     show=True,  priority=True),
    ]

    def __init__(self, config: SessionConfig) -> None:
        super().__init__()
        self._config = config
        self._is_stream = config.mode == LogMode.STREAM

        # Compiled match patterns — updated live when user edits strings
        self._filter_patterns:    list[re.Pattern] = compile_patterns(config.filters,    config.filters_ignore_case)
        self._highlight_patterns: list[re.Pattern] = compile_patterns(config.highlights, config.highlights_ignore_case)
        self._monitor_patterns:   list[re.Pattern] = compile_patterns(config.monitors,   config.monitors_ignore_case)

        # Full log buffer — capped to avoid unbounded memory / slow rerenders
        self._buffer: list[LogLine] = []
        self._buffer_cap = 20_000

        # Pod → color mapping
        self._color_map: dict[str, str] = {}

        self._paused = False
        self._pending_lines: list[LogLine] = []   # buffered while paused
        self._paused_since_last_ui = 0            # lines received since last indicator update

        # Deployment → list of pod names currently streaming
        self._deployment_pods: dict[str, list[str]] = {}

        # Backfill interleaving (only active when config.since requests a
        # look-back window in stream mode) — see _handle_backfill_line().
        # Concurrent per-pod streams don't arrive in chronological order, so
        # a backfill burst is held and sorted by real log_timestamp before
        # display, rather than shown in arrival order and clumped per pod.
        # None = no backfill in progress (the common case — zero overhead).
        self._backfill_pending: set[str] | None = None
        self._backfill_buffer: list[LogLine] = []
        self._backfill_cutoff: datetime | None = None
        self._backfill_watchdog = None

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
        yield Rule()
        yield Footer()

    def _side_panels(self) -> list[Vertical]:
        """Every panel other than MainStreamPanel that can be dragged/resized."""
        panels = [self.query_one(SearchPanel)]
        if self._is_stream:
            panels.append(self.query_one(MonitorPanel))
            panels.append(self.query_one(HealthPanel))
        return panels

    def _visible_side_panels(self) -> list[tuple[str, Vertical]]:
        """(label, panel) for side panels currently shown and expanded —
        the only ones a percentage-based size actually means anything for."""
        labeled: list[tuple[str, Vertical]] = [("Search", self.query_one(SearchPanel))]
        if self._is_stream:
            labeled.append(("Monitor", self.query_one(MonitorPanel)))
            labeled.append(("Health", self.query_one(HealthPanel)))
        return [
            (label, panel) for label, panel in labeled
            if panel.display and not getattr(panel, "_collapsed", False)
        ]

    def resize_panel(self, panel: Vertical, delta: int) -> None:
        """
        Grow/shrink one side panel by `delta` rows, taking the difference
        from (or giving it back to) MainStreamPanel — never from another
        side panel — and never letting MainStreamPanel drop below
        MAIN_STREAM_MIN_HEIGHT.
        """
        if delta == 0:
            return
        total = self.query_one("#panels").outer_size.height
        if total <= 0:
            return

        # outer_size (not size) — size excludes a panel's own border row, but
        # styles.height (what we're setting below) is border-inclusive. Mixing
        # the two produces an off-by-one every time a bordered panel resizes.
        others_height = sum(
            p.outer_size.height for p in self._side_panels() if p is not panel
        )
        new_height = panel.outer_size.height + delta
        new_height = max(new_height, self.SIDE_PANEL_MIN_HEIGHT)
        max_allowed = total - others_height - self.MAIN_STREAM_MIN_HEIGHT
        new_height = min(new_height, max(max_allowed, self.SIDE_PANEL_MIN_HEIGHT))
        panel.styles.height = new_height

    async def on_mount(self) -> None:
        self.query_one(SearchPanel).display = False
        panel = self.query_one(MainStreamPanel)
        panel.set_color_mode(self._config.color_full_line)
        panel.set_wrap(self._config.line_wrap)
        panel.set_json_format(self._config.json_format)
        search_panel = self.query_one(SearchPanel)
        search_panel.set_wrap(self._config.line_wrap)
        search_panel.set_color_mode(self._config.color_full_line)
        if self._is_stream:
            monitor_panel = self.query_one(MonitorPanel)
            monitor_panel.set_wrap(self._config.line_wrap)
            monitor_panel.set_color_mode(self._config.color_full_line)

        # Give focus to the log display so all key bindings are reachable
        self.query_one("#stream-log").focus()

        # Run blocking kubectl calls off the event loop so the TUI stays responsive
        self.run_worker(self._init_pods(), name="init-pods")

    async def _init_pods(self) -> None:
        from .. import kubectl as k

        # Resolve pods from selected deployments (blocking subprocess, runs in worker)
        deployments = await asyncio.get_event_loop().run_in_executor(
            None, k.get_deployments, self._config.namespace
        )
        dep_map = {d.name: d for d in deployments}
        selected_deps = [dep_map[n] for n in self._config.deployments if n in dep_map]
        pods = await asyncio.get_event_loop().run_in_executor(
            None, k.get_pods_for_deployments, self._config.namespace, selected_deps
        )

        if not pods:
            self.notify("No pods found for selected deployments.", severity="error")
            return

        self._color_map = assign_colors([p.name for p in pods])
        self.query_one(SearchPanel).set_color_map(self._color_map)
        if self._is_stream:
            self.query_one(MonitorPanel).set_color_map(self._color_map)
            self.query_one(MonitorPanel).set_patterns(self._monitor_patterns)

        if self._is_stream:
            self._start_streaming(selected_deps, pods)
            if self._config.health.enabled:
                pod_names = [p.name for p in pods]
                self.run_worker(
                    self._poll_health(pod_names),
                    name="health-poll",
                )
        else:
            self.run_worker(self._load_dump(pods), name="dump-loader")

    # ── Pod stream management ─────────────────────────────────────────────────

    def _start_streaming(self, deps, pods) -> None:
        """Start streaming workers for a set of deployments and their pods."""
        from .. import kubectl as k

        for dep in deps:
            self._deployment_pods[dep.name] = []

        if k.wants_backfill(self._config.since):
            # A look-back window means every pod's stream opens with a
            # backfill burst. Hold lines from all of them until every pod
            # has either caught up to live or the watchdog fires, then
            # deliver the whole burst sorted by real timestamp — otherwise
            # they show up in arrival order, clumped one pod at a time.
            # (wants_backfill, not a truthiness check: a user-entered "0"
            # is non-empty but kubectl treats it as no window at all — see
            # kubectl._normalize_since — so it shouldn't trigger a 5-second
            # wait for a backfill that will never arrive.)
            self._backfill_pending = {p.name for p in pods}
            self._backfill_cutoff = datetime.now(timezone.utc)
            self._backfill_watchdog = self.set_timer(5.0, self._backfill_watchdog_fire)

        for pod in pods:
            self._deployment_pods.setdefault(pod.deployment, []).append(pod.name)
            self.run_worker(
                self._stream_pod(pod.name),
                name=f"stream-{pod.name}",
                exclusive=False,
            )

    def add_deployment_to_stream(self, deployment_name: str) -> None:
        """Dynamically add a deployment's pods to the live stream."""
        if deployment_name in self._deployment_pods:
            self.notify(f"Already streaming {deployment_name}", severity="warning")
            return

        from .. import kubectl as k
        try:
            all_deps = k.get_deployments(self._config.namespace)
            dep = next((d for d in all_deps if d.name == deployment_name), None)
            if dep is None:
                self.notify(f"Deployment '{deployment_name}' not found", severity="error")
                return
            pods = k.get_pods_for_deployments(self._config.namespace, [dep])
        except Exception as exc:
            self.notify(f"Failed to get pods: {exc}", severity="error")
            return

        if not pods:
            self.notify(f"No pods found for {deployment_name}", severity="warning")
            return

        # Assign colors for new pods
        new_names = [p.name for p in pods if p.name not in self._color_map]
        if new_names:
            all_names = list(self._color_map) + new_names
            self._color_map = assign_colors(all_names)

        self._deployment_pods[deployment_name] = [p.name for p in pods]
        self._config.deployments.append(deployment_name)

        for pod in pods:
            self.run_worker(
                self._stream_pod(pod.name),
                name=f"stream-{pod.name}",
                exclusive=False,
            )
        self.notify(f"Now streaming {deployment_name} ({len(pods)} pod{'s' if len(pods) != 1 else ''})")

    def remove_deployment_from_stream(self, deployment_name: str) -> None:
        """Stop streaming a deployment's pods."""
        pod_names = self._deployment_pods.pop(deployment_name, [])
        if not pod_names:
            return
        for worker in self.workers:
            if worker.name in {f"stream-{p}" for p in pod_names}:
                worker.cancel()
        if deployment_name in self._config.deployments:
            self._config.deployments.remove(deployment_name)
        self.notify(f"Stopped streaming {deployment_name}")

    # ── Log ingestion ──────────────────────────────────────────────────────────

    async def _stream_pod(self, pod_name: str) -> None:
        from .. import kubectl as k
        import time
        backoff = 2.0
        error_count = 0  # consecutive errors; reset on clean stream
        while True:
            try:
                batch: list[LogLine] = []
                last_flush = time.monotonic()
                async for line in k.stream_logs(
                    pod_name,
                    self._config.namespace,
                    since=self._config.since,
                    tail=self._config.tail,
                ):
                    batch.append(line)
                    now = time.monotonic()
                    if len(batch) >= 20 or (now - last_flush) >= 0.1:
                        for l in batch:
                            self._ingest(l)
                        batch.clear()
                        last_flush = now
                        await asyncio.sleep(0)
                for l in batch:
                    self._ingest(l)
                # Stream ended cleanly — reconnect silently
                error_count = 0
                backoff = 2.0
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                error_count += 1
                # Only notify on the first error per pod; suppress repetitive reconnect spam
                if error_count == 1:
                    self.notify(f"{pod_name}: stream error — {exc}",
                                severity="warning", timeout=5)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

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
        if self._filter_patterns and matches(line.content, self._filter_patterns):
            return

        if self._backfill_pending is not None:
            self._handle_backfill_line(line)
            return

        self._buffer.append(line)
        if len(self._buffer) > self._buffer_cap:
            del self._buffer[: self._buffer_cap // 10]  # trim 10% at a time

        if self._paused:
            self._pending_lines.append(line)
            self._paused_since_last_ui += 1
            if self._paused_since_last_ui >= 100:
                self._paused_since_last_ui = 0
                self._update_pause_indicator()
            return

        self._deliver_to_panels(line)

    def _deliver_to_panels(self, line: LogLine) -> None:
        color = self._color_map.get(line.pod_name, "#ffffff")
        hl = self._highlight_patterns if (self._highlight_patterns and
             matches(line.content, self._highlight_patterns)) else None

        self.query_one(MainStreamPanel).add_line(line, color, hl)

        if self._is_stream and self._monitor_patterns:
            if matches(line.content, self._monitor_patterns):
                try:
                    self.query_one(MonitorPanel).add_line(line, color)
                except Exception:
                    pass

    # ── Backfill interleaving ────────────────────────────────────────────────

    def _handle_backfill_line(self, line: LogLine) -> None:
        """
        Route one line while a backfill burst is in progress (see
        _start_streaming). Lines from every pod are held until all pods have
        either caught up to live, the watchdog fires, or BACKFILL_BUFFER_CAP
        is hit, then flushed sorted by real timestamp — otherwise each pod's
        backlog displays as one arrival-order clump instead of properly
        interleaved history.
        """
        is_backfill = (
            line.log_timestamp is not None
            and self._backfill_cutoff is not None
            and line.log_timestamp < self._backfill_cutoff
        )
        if not is_backfill:
            # This pod has caught up to live. Still hold the line (rather
            # than display it immediately) if other pods are still behind,
            # so a fast pod's live lines don't jump ahead of a slow pod's
            # still-pending backfill.
            self._backfill_pending.discard(line.pod_name)

        self._backfill_buffer.append(line)
        if not self._backfill_pending or len(self._backfill_buffer) >= self.BACKFILL_BUFFER_CAP:
            self._flush_backfill()

    def _backfill_watchdog_fire(self) -> None:
        self._backfill_watchdog = None
        if self._backfill_pending:
            self._flush_backfill()

    def _flush_backfill(self) -> None:
        lines, self._backfill_buffer = self._backfill_buffer, []
        self._backfill_pending = None
        self._backfill_cutoff = None
        if self._backfill_watchdog is not None:
            self._backfill_watchdog.stop()
            self._backfill_watchdog = None
        # Fallback for the rare line whose timestamp didn't parse — a single
        # shared "now" (not received_at, which is naive local time and would
        # misorder against real UTC timestamps by the local tz offset).
        fallback = datetime.now(timezone.utc)
        lines.sort(key=lambda l: l.log_timestamp or fallback)
        for line in lines:
            self._ingest(line)  # _backfill_pending is now None, so this goes through normally

    # ── Pause / resume ─────────────────────────────────────────────────────────

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        # Update indicator first — this sets auto_scroll=True on the RichLog before
        # scroll_to_end() fires, so the widget is already in live-follow mode when
        # new lines arrive from the pending flush.
        self._update_pause_indicator()
        if not paused:
            self.query_one(MainStreamPanel).scroll_to_end()
            if self._pending_lines:
                self.run_worker(self._flush_pending(), group="flush-pending", exclusive=True)

    async def _flush_pending(self) -> None:
        lines, self._pending_lines = self._pending_lines, []
        # Cap at 500 — discard oldest if the backlog is huge
        if len(lines) > 500:
            lines = lines[-500:]
        for i, line in enumerate(lines):
            self._deliver_to_panels(line)
            if i % 50 == 49:
                await asyncio.sleep(0)
        self._update_pause_indicator()

    def _update_pause_indicator(self) -> None:
        n = len(self._pending_lines)
        panel = self.query_one(MainStreamPanel)
        panel.set_paused(self._paused, n)

    # ── Pattern updates (from live string editing) ─────────────────────────────

    def update_filters(self, new_strings: list[str]) -> None:
        self._config.filters = new_strings
        self._filter_patterns = compile_patterns(new_strings, self._config.filters_ignore_case)

    def update_highlights(self, new_strings: list[str]) -> None:
        self._config.highlights = new_strings
        self._highlight_patterns = compile_patterns(new_strings, self._config.highlights_ignore_case)

    def update_monitors(self, new_strings: list[str]) -> None:
        self._config.monitors = new_strings
        self._monitor_patterns = compile_patterns(new_strings, self._config.monitors_ignore_case)
        self.query_one(MonitorPanel).set_patterns(self._monitor_patterns)

    def _apply_edits_and_resume(self) -> None:
        """
        Rebuild both panels from the full buffer, then re-engage live-follow.
        Called when an F/H/M edit modal closes. Rebuilding from `_buffer`
        (which already holds every line received while paused) makes the
        pending queue redundant, so we clear it rather than running the async
        flush — avoiding double-delivery when a rebuild and a flush would
        otherwise race. Also drops hits for monitors that were just unchecked
        and re-shows everything buffered while the modal was open.
        """
        self._rerender_main_stream()
        if self._is_stream:
            self.query_one(MonitorPanel).rebuild(self._buffer)
        if self._is_stream:
            self._pending_lines.clear()
            self._paused_since_last_ui = 0
            self._paused = False
            self._update_pause_indicator()
            self.query_one(MainStreamPanel).scroll_to_end()

    def _rerender_main_stream(self) -> None:
        """Replay buffer through updated filters and highlights."""
        panel = self.query_one(MainStreamPanel)
        panel.clear()
        for line in self._buffer:
            if self._filter_patterns and matches(line.content, self._filter_patterns):
                continue
            color = self._color_map.get(line.pod_name, "#ffffff")
            hl = self._highlight_patterns if (self._highlight_patterns and
                 matches(line.content, self._highlight_patterns)) else None
            panel.add_line(line, color, hl)

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
        from ..config import load_saved_strings
        self.push_screen(
            StringEditModal("filters", self._config.filters, load_saved_strings().filters),
            self._on_filters_edited,
        )

    def action_edit_highlights(self) -> None:
        from ..config import load_saved_strings
        self.push_screen(
            StringEditModal("highlights", self._config.highlights, load_saved_strings().highlights),
            self._on_highlights_edited,
        )

    def action_edit_monitors(self) -> None:
        if not self._is_stream:
            return
        from ..config import load_saved_strings
        self.push_screen(
            StringEditModal("monitors", self._config.monitors, load_saved_strings().monitors),
            self._on_monitors_edited,
        )

    def _on_filters_edited(self, result: tuple[list[str], bool] | None) -> None:
        if result is not None:
            new_strings, save = result
            if save:
                from ..config import add_to_saved_strings, load_saved_strings
                saved = load_saved_strings().filters
                truly_new = [s for s in new_strings if s not in saved]
                if truly_new:
                    add_to_saved_strings("filters", truly_new)
                    self.notify(f"Saved {len(truly_new)} filter(s) to saved settings")
            self.update_filters(new_strings)
        # Resume live-follow on close, whether applied or cancelled.
        self._apply_edits_and_resume()

    def _on_highlights_edited(self, result: tuple[list[str], bool] | None) -> None:
        if result is not None:
            new_strings, save = result
            if save:
                from ..config import add_to_saved_strings, load_saved_strings
                saved = load_saved_strings().highlights
                truly_new = [s for s in new_strings if s not in saved]
                if truly_new:
                    add_to_saved_strings("highlights", truly_new)
                    self.notify(f"Saved {len(truly_new)} highlight(s) to saved settings")
            self.update_highlights(new_strings)
        self._apply_edits_and_resume()

    def _on_monitors_edited(self, result: tuple[list[str], bool] | None) -> None:
        if result is not None:
            new_strings, save = result
            if save:
                from ..config import add_to_saved_strings, load_saved_strings
                saved = load_saved_strings().monitors
                truly_new = [s for s in new_strings if s not in saved]
                if truly_new:
                    add_to_saved_strings("monitors", truly_new)
                    self.notify(f"Saved {len(truly_new)} monitor(s) to saved settings")
            self.update_monitors(new_strings)
        self._apply_edits_and_resume()

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
        full_line = self._config.color_full_line

        self.query_one(MainStreamPanel).set_color_mode(full_line)
        self._rerender_main_stream()

        search_panel = self.query_one(SearchPanel)
        search_panel.set_color_mode(full_line)
        query = search_panel.query_one("#search-input", Input).value
        search_panel.search(self._buffer, query)

        if self._is_stream:
            monitor_panel = self.query_one(MonitorPanel)
            monitor_panel.set_color_mode(full_line)
            monitor_panel.rebuild(self._buffer)

        mode = "full line" if full_line else "name only"
        self.notify(f"Color mode: {mode}")

    def action_toggle_wrap(self) -> None:
        self._config.line_wrap = not self._config.line_wrap
        wrap = self._config.line_wrap
        self.query_one(MainStreamPanel).set_wrap(wrap)
        self.query_one(SearchPanel).set_wrap(wrap)
        if self._is_stream:
            self.query_one(MonitorPanel).set_wrap(wrap)
        # RichLog only applies wrap to new writes — re-render buffer so existing lines reflow
        self._rerender_main_stream()
        self.notify(f"Line wrap: {'on' if wrap else 'off'}")

    def action_toggle_json(self) -> None:
        self._config.json_format = not self._config.json_format
        panel = self.query_one(MainStreamPanel)
        panel.set_json_format(self._config.json_format)
        self._rerender_main_stream()
        self.notify(f"JSON format: {'on' if self._config.json_format else 'raw'}")

    def show_json_detail(self, idx: int | None) -> None:
        if idx is None:
            return
        parsed = self.query_one(MainStreamPanel).get_parsed_json(idx)
        if parsed is None:
            return
        self.push_screen(JsonDetailModal(parsed.pretty))

    def action_toggle_search(self) -> None:
        panel = self.query_one(SearchPanel)
        panel.display = not panel.display
        if panel.display:
            panel.query_one("#search-input").focus()
        else:
            self.query_one("#stream-log").focus()

    def action_manage_pods(self) -> None:
        self.push_screen(
            PodSelectorModal(
                namespace=self._config.namespace,
                active_deployments=list(self._config.deployments),
            ),
            self._on_pods_selected,
        )

    def _on_pods_selected(self, new_deployments: list[str] | None) -> None:
        if new_deployments is None:
            return
        current = set(self._config.deployments)
        new = set(new_deployments)
        for dep in new - current:
            self.add_deployment_to_stream(dep)
        for dep in current - new:
            self.remove_deployment_from_stream(dep)

    def action_edit_layout(self) -> None:
        panels = self._visible_side_panels()
        if not panels:
            self.notify("No resizable panes are currently visible.", severity="warning")
            return
        total = self.query_one("#panels").outer_size.height
        if total <= 0:
            return
        entries = [
            (label, round(panel.outer_size.height / total * 100))
            for label, panel in panels
        ]
        self.push_screen(PaneSizeModal(entries), self._on_layout_edited)

    def _on_layout_edited(self, result: dict[str, int] | None) -> None:
        if result is None:
            return
        panels = dict(self._visible_side_panels())
        total = self.query_one("#panels").outer_size.height
        if total <= 0:
            return

        heights = {
            label: max(self.SIDE_PANEL_MIN_HEIGHT, round(pct / 100 * total))
            for label, pct in result.items()
            if label in panels
        }

        remaining = total - sum(heights.values())
        if remaining < self.MAIN_STREAM_MIN_HEIGHT:
            self.notify(
                f"Those sizes would leave only {remaining} rows for the main "
                f"stream (minimum {self.MAIN_STREAM_MIN_HEIGHT}). Reduce one "
                f"or more percentages and try again.",
                severity="error",
            )
            return

        for label, height in heights.items():
            panels[label].styles.height = height

    # ── Cross-panel: line-select jump ─────────────────────────────────────────

    def on_health_panel_add_to_stream(self, event) -> None:
        self.add_deployment_to_stream(event.deployment_name)

    def on_search_panel_line_selected(self, event) -> None:
        self.set_paused(True)
        self._jump_to_line(event.line)

    def on_monitor_panel_line_selected(self, event) -> None:
        self.set_paused(True)
        self._jump_to_line(event.line)

    def _jump_to_line(self, target: LogLine) -> None:
        """Rebuild the main stream showing context around target, with it highlighted."""
        # Try identity first, fall back to content match if buffer was trimmed
        idx = next((i for i, l in enumerate(self._buffer) if l is target), None)
        if idx is None:
            idx = next((i for i, l in enumerate(self._buffer)
                        if l.pod_name == target.pod_name and l.content == target.content), None)
        if idx is None:
            self.notify("Line no longer in buffer.", severity="warning")
            return
        start = max(0, idx - 100)
        context = self._buffer[start: idx + 11]
        panel = self.query_one(MainStreamPanel)
        panel.clear()
        for line in context:
            if self._filter_patterns and matches(line.content, self._filter_patterns):
                continue
            color = self._color_map.get(line.pod_name, "#ffffff")
            is_target = line is target
            hl = self._highlight_patterns if (not is_target and self._highlight_patterns and
                 matches(line.content, self._highlight_patterns)) else None
            panel.add_line(line, color, hl, is_target=is_target)
        panel.scroll_to_end()
