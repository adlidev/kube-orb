"""
Single-page wizard screen.
Everything on one scrollable form — namespace, services, mode,
filters, highlights, monitors, health, save config, launch.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
    Static,
)

from ..models import HealthConfig, LogMode, SessionConfig


def _section(title: str) -> Static:
    return Static(f"── {title} ", classes="wizard-section-header")


class SinglePageWizard(Screen[SessionConfig | None]):

    BINDINGS = [
        Binding("ctrl+q", "cancel", "Cancel", show=True),
    ]

    def __init__(self, initial_namespace: str = "default") -> None:
        super().__init__()
        self._initial_namespace = initial_namespace
        self._deployments: list[str] = []
        self._pod_counts: dict[str, int] = {}
        self._saved_filters:   list[str] = []
        self._saved_highlights: list[str] = []
        self._saved_monitors:  list[str] = []
        self._saved_configs:   list[str] = []

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="wizard-scroll"):

            # ── Namespace ─────────────────────────────────────────────────
            yield Static("── Namespace ", id="ns-header", classes="wizard-section-header")
            yield Select(
                options=[(self._initial_namespace, self._initial_namespace)],
                prompt="Select a namespace …",
                id="ns-select",
                allow_blank=False,
                value=self._initial_namespace,
            )
            yield Horizontal(
                Input(placeholder="Or type a namespace manually …", id="ns-input"),
                Button("Refresh services ↺", id="ns-refresh"),
                classes="wizard-row",
            )

            # ── Load saved config ─────────────────────────────────────────
            yield _section("Load saved config (optional)")
            yield Select(
                options=[],
                prompt="Select a saved config to pre-fill …",
                id="cfg-select",
                allow_blank=True,
            )

            # ── Services ──────────────────────────────────────────────────
            yield _section("Services to watch")
            yield Horizontal(
                Button("Select all", id="dep-all"),
                Button("Clear",      id="dep-clear"),
                classes="wizard-row",
            )
            yield ScrollableContainer(
                Vertical(id="dep-checks"),
                id="dep-scroll",
            )
            yield Static("(No deployments found — enter a namespace above and click Refresh)",
                         id="dep-empty", classes="wizard-hint")

            # ── Log mode ──────────────────────────────────────────────────
            yield _section("Log mode")
            with RadioSet(id="mode-radio"):
                yield RadioButton("Stream  — live tail", value=True, id="mode-stream")
                yield RadioButton("Dump    — fetch existing logs then stop", id="mode-dump")
            with Vertical(id="dump-opts", classes="wizard-subsection"):
                yield Static("Fetch last N lines:", classes="wizard-hint")
                yield Input(placeholder="e.g. 500", id="dump-tail")
                yield Static("— or — fetch logs since:", classes="wizard-hint")
                yield Input(placeholder="e.g. 1h, 30m", id="dump-since")

            # ── Filters ───────────────────────────────────────────────────
            yield _section("Filters — hide matching lines")
            yield Static("Saved filters (check to activate):", classes="wizard-hint")
            yield ScrollableContainer(
                Vertical(id="filter-checks"),
                id="filter-scroll",
            )
            yield Input(placeholder="Add filters: ERROR, /5[0-9]{2}/, …",
                        id="filter-input")
            yield Checkbox("Save new filter strings to list",
                           id="filter-save", value=True)

            # ── Highlights ────────────────────────────────────────────────
            yield _section("Highlights — emphasise matching lines")
            yield Static("Saved highlights (check to activate):", classes="wizard-hint")
            yield ScrollableContainer(
                Vertical(id="hl-checks"),
                id="hl-scroll",
            )
            yield Input(placeholder="Add highlights: WARN, brute force, …",
                        id="hl-input")
            yield Checkbox("Save new highlight strings to list",
                           id="hl-save", value=True)

            # ── Monitor strings ───────────────────────────────────────────
            with Vertical(id="monitor-section"):
                yield _section("Monitor strings — collect matches in side panel")
                yield Static("Saved monitors (check to activate):", classes="wizard-hint")
                yield ScrollableContainer(
                    Vertical(id="mon-checks"),
                    id="mon-scroll",
                )
                yield Input(placeholder="Add monitors: job failed, OOM, …",
                            id="mon-input")
                yield Checkbox("Save new monitor strings to list",
                               id="mon-save", value=True)

            # ── Pod health ────────────────────────────────────────────────
            with Vertical(id="health-section"):
                yield _section("Pod health monitoring")
                yield Checkbox("Enable pod health panel", id="health-enable", value=False)
                with Vertical(id="health-opts"):
                    yield Static("Check interval (minutes, min 1):", classes="wizard-hint")
                    yield Input("5", id="health-interval")

            # ── Display options ───────────────────────────────────────────
            yield _section("Display options")
            yield Checkbox(
                "Color full line (off = color pod name prefix only)",
                id="color-full-line",
                value=False,
            )

            # ── Save config ───────────────────────────────────────────────
            yield _section("Save config for reuse (optional)")
            yield Input(placeholder="Config name, e.g. 'prod-debug' — leave blank to skip",
                        id="save-name")

            # ── Launch ────────────────────────────────────────────────────
            with Horizontal(classes="wizard-row"):
                yield Button("Launch →", variant="primary", id="launch")
                yield Button("Cancel", variant="error", id="cancel")

    # ── Mount: populate dynamic content ───────────────────────────────────────

    def on_mount(self) -> None:
        self.query_one("#dump-opts").display = False
        self.query_one("#health-opts").display = False
        self._load_saved_strings()
        self._populate_namespaces()
        self._refresh_saved_configs()

    def _populate_namespaces(self) -> None:
        from .. import kubectl as k
        try:
            namespaces = k.get_namespaces()
        except Exception:
            namespaces = [self._initial_namespace]

        sel = self.query_one("#ns-select", Select)
        options = [(ns, ns) for ns in namespaces]
        sel.set_options(options)

        # Pre-select the context namespace if present, else first available
        if self._initial_namespace in namespaces:
            sel.value = self._initial_namespace
        elif namespaces:
            sel.value = namespaces[0]

        # Update section header to show detected context namespace
        detected = self._initial_namespace
        self.query_one("#ns-header", Static).update(
            f"── Namespace  (kubectl context: {detected}) "
        )

        # Load deployments for the selected namespace
        self._refresh_deployments()

    def _active_namespace(self) -> str:
        """Return whichever namespace is active — manual input overrides the select."""
        manual = self.query_one("#ns-input", Input).value.strip()
        if manual:
            return manual
        val = self.query_one("#ns-select", Select).value
        if val and val is not Select.BLANK:
            return str(val)
        return self._initial_namespace

    def _refresh_deployments(self) -> None:
        from .. import kubectl as k
        ns = self._active_namespace()
        dep_container = self.query_one("#dep-checks", Vertical)
        dep_container.remove_children()
        self._deployments = []
        self._pod_counts = {}

        try:
            deps = k.get_deployments(ns)
            self._deployments = [d.name for d in deps]
            self._pod_counts = {d.name: d.pod_count for d in deps}
        except Exception as exc:
            self.query_one("#dep-empty", Static).update(
                f"Error: {exc}\nCheck that the namespace exists and kubectl is configured."
            )
            self.query_one("#dep-empty").display = True
            return

        if not self._deployments:
            self.query_one("#dep-empty", Static).update(
                f"No deployments found in namespace '{ns}'."
            )
            self.query_one("#dep-empty").display = True
            return

        self.query_one("#dep-empty").display = False
        for name in self._deployments:
            count = self._pod_counts.get(name, 0)
            dep_container.mount(
                Checkbox(f"{name}  ({count} pod{'s' if count != 1 else ''})",
                         value=True, id=f"dep-{name}")
            )

    def _load_saved_strings(self) -> None:
        from ..config import load_saved_strings
        saved = load_saved_strings()
        self._saved_filters    = saved.filters
        self._saved_highlights = saved.highlights
        self._saved_monitors   = saved.monitors
        self._populate_string_checks("filter-checks", self._saved_filters,   [])
        self._populate_string_checks("hl-checks",     self._saved_highlights, [])
        self._populate_string_checks("mon-checks",    self._saved_monitors,   [])

    def _populate_string_checks(
        self,
        container_id: str,
        strings: list[str],
        active: list[str],
    ) -> None:
        container = self.query_one(f"#{container_id}", Vertical)
        container.remove_children()
        for s in strings:
            container.mount(
                Checkbox(s, value=(s in active), id=f"{container_id}-{abs(hash(s))}")
            )

    def _refresh_saved_configs(self) -> None:
        from ..config import list_saved_configs
        ns = self._active_namespace()
        self._saved_configs = list_saved_configs(ns)
        sel = self.query_one("#cfg-select", Select)
        options = [(name, name) for name in self._saved_configs]
        sel.set_options(options if options else [("(no saved configs)", "__none__")])

    def _apply_saved_config(self, name: str) -> None:
        from ..config import load_session_config
        ns = self._active_namespace()
        cfg = load_session_config(ns, name)
        if cfg is None:
            return

        # Re-populate string checklists with config's active strings
        self._populate_string_checks("filter-checks", self._saved_filters,    cfg.filters)
        self._populate_string_checks("hl-checks",     self._saved_highlights,  cfg.highlights)
        self._populate_string_checks("mon-checks",    self._saved_monitors,    cfg.monitors)

        # Re-select deployments
        for name_dep in self._deployments:
            cb_id = f"dep-{name_dep}"
            try:
                cb = self.query_one(f"#{cb_id}", Checkbox)
                cb.value = name_dep in cfg.deployments
            except Exception:
                pass

        # Mode
        rs = self.query_one("#mode-radio", RadioSet)
        rs.pressed_index = 1 if cfg.mode == LogMode.DUMP else 0

        if cfg.tail:
            self.query_one("#dump-tail", Input).value = str(cfg.tail)
        if cfg.since:
            self.query_one("#dump-since", Input).value = cfg.since

        self.query_one("#health-enable", Checkbox).value = cfg.health.enabled
        self.query_one("#health-interval", Input).value = str(cfg.health.interval_minutes)
        self.query_one("#color-full-line", Checkbox).value = cfg.color_full_line

    # ── Events ────────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ns-refresh":
            self._refresh_deployments()
            self._refresh_saved_configs()
        elif event.button.id == "dep-all":
            for cb in self.query("#dep-checks Checkbox"):
                cb.value = True
        elif event.button.id == "dep-clear":
            for cb in self.query("#dep-checks Checkbox"):
                cb.value = False
        elif event.button.id == "launch":
            self._launch()
        elif event.button.id == "cancel":
            self.action_cancel()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        is_dump = event.index == 1
        self.query_one("#dump-opts").display = is_dump
        self.query_one("#monitor-section").display = not is_dump
        self.query_one("#health-section").display = not is_dump

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "health-enable":
            self.query_one("#health-opts").display = event.value

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "ns-select":
            # Namespace changed — reload deployments and saved configs
            self.query_one("#ns-input", Input).value = ""  # clear manual override
            self._refresh_deployments()
            self._refresh_saved_configs()
        elif event.select.id == "cfg-select":
            value = event.value
            if value and value != "__none__" and value is not Select.BLANK:
                self._apply_saved_config(str(value))

    # ── Assemble and launch ───────────────────────────────────────────────────

    def _launch(self) -> None:
        from ..config import add_to_saved_strings, parse_string_input

        ns = self._active_namespace()
        if not ns:
            self.notify("Select or enter a namespace.", severity="warning")
            return

        # Deployments
        deployments = [
            cb.label.plain.split("  (")[0]
            for cb in self.query("#dep-checks Checkbox")
            if cb.value
        ]
        if not deployments:
            self.notify("Select at least one service.", severity="warning")
            return

        # Mode
        rs = self.query_one("#mode-radio", RadioSet)
        is_dump = rs.pressed_index == 1
        mode = LogMode.DUMP if is_dump else LogMode.STREAM

        tail: int | None = None
        since: str | None = None
        if is_dump:
            tail_raw = self.query_one("#dump-tail", Input).value.strip()
            since_raw = self.query_one("#dump-since", Input).value.strip()
            if tail_raw:
                try:
                    tail = int(tail_raw)
                except ValueError:
                    self.notify("Tail must be a number.", severity="warning")
                    return
            if since_raw:
                since = since_raw

        # Collect strings helper
        def collect(checks_id: str, saved: list[str], input_id: str, save_id: str) -> list[str]:
            active = [
                s for cb, s in zip(
                    self.query(f"#{checks_id} Checkbox"), saved
                )
                if cb.value
            ]
            raw = self.query_one(f"#{input_id}", Input).value.strip()
            new = parse_string_input(raw) if raw else []
            merged = active + [s for s in new if s not in active]
            if new and self.query_one(f"#{save_id}", Checkbox).value:
                truly_new = [s for s in new if s not in saved]
                if truly_new:
                    cat = save_id.split("-")[0]   # "filter" / "hl" / "mon"
                    cat_map = {"filter": "filters", "hl": "highlights", "mon": "monitors"}
                    add_to_saved_strings(cat_map[cat], truly_new)
            return merged

        filters    = collect("filter-checks", self._saved_filters,    "filter-input", "filter-save")
        highlights = collect("hl-checks",     self._saved_highlights,  "hl-input",     "hl-save")
        monitors: list[str] = []
        if not is_dump:
            monitors = collect("mon-checks", self._saved_monitors, "mon-input", "mon-save")

        # Health
        health = HealthConfig()
        if not is_dump:
            health.enabled = self.query_one("#health-enable", Checkbox).value
            if health.enabled:
                try:
                    health.interval_minutes = max(
                        1, int(self.query_one("#health-interval", Input).value.strip() or "5")
                    )
                except ValueError:
                    self.notify("Health interval must be a number.", severity="warning")
                    return

        # Save config
        save_name = self.query_one("#save-name", Input).value.strip() or None

        color_full_line = self.query_one("#color-full-line", Checkbox).value

        config = SessionConfig(
            namespace=ns,
            deployments=deployments,
            mode=mode,
            tail=tail,
            since=since,
            filters=filters,
            highlights=highlights,
            monitors=monitors,
            health=health,
            color_full_line=color_full_line,
            name=save_name,
        )

        if save_name:
            from ..config import save_session_config
            save_session_config(config)

        self.dismiss(config)

    def action_cancel(self) -> None:
        self.dismiss(None)
