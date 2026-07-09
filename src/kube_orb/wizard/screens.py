"""
Three-tab wizard:
  Tab 1 · Targets  — namespace, services, log mode
  Tab 2 · Strings  — filters, highlights, monitors
  Tab 3 · Options  — health, display, save config, launch
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.content import Content
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Rule,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from ..models import HealthConfig, LogMode, SessionConfig


def _section(title: str) -> Static:
    return Static(title, classes="section-title")


class SinglePageWizard(Screen[SessionConfig | None]):
    """Three-tab setup wizard. Class name kept for compatibility with wizard/app.py."""

    BINDINGS = [
        Binding("ctrl+q", "cancel", "Cancel", show=True),
    ]

    def __init__(self, initial_namespace: str = "default") -> None:
        super().__init__()
        self._initial_namespace = initial_namespace
        self._deployments: list[str] = []
        self._pod_counts: dict[str, int] = {}
        # Which deployments should start checked on the *next* checkbox mount.
        # None = default all-checked. Set by _apply_saved_config so the mount
        # (which may happen asynchronously, racing the caller) reflects the
        # saved config instead of blindly checking everything. Consumed once.
        self._pending_deployments: set[str] | None = None
        # Namespace most recently passed to _refresh_deployments(). Lets
        # on_select_changed skip a redundant refresh when Select.Changed for
        # ns-select is still queued after _apply_saved_config already
        # refreshed for that same namespace itself.
        self._last_refreshed_ns: str | None = None
        self._saved_filters:   list[str] = []
        self._saved_highlights: list[str] = []
        self._saved_monitors:  list[str] = []
        self._saved_configs:   list[str] = []
        self._known_namespaces: list[str] = []
        self._initializing_ns = False

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("kube-orb  ·  setup", id="wizard-title")

        with TabbedContent(id="wizard-tabs"):

            # ── Tab 1: Targets ────────────────────────────────────────────────
            with TabPane("Targets", id="tab-targets"):
                with ScrollableContainer(id="targets-scroll"):

                    yield _section("Load saved config")
                    yield Select(
                        options=[],
                        prompt="Select a saved config to pre-fill …",
                        id="cfg-select",
                        allow_blank=True,
                    )

                    yield Rule()
                    yield _section("Namespace")
                    yield Static(
                        f"kubectl context: {self._initial_namespace}",
                        id="ns-header",
                        classes="field-hint",
                    )
                    yield Select(
                        options=[(self._initial_namespace, self._initial_namespace)],
                        id="ns-select",
                        allow_blank=False,
                        value=self._initial_namespace,
                    )
                    yield Input(placeholder="Or type a namespace manually …", id="ns-input")

                    yield Rule()
                    yield _section("Services to watch")
                    with Horizontal(classes="row"):
                        yield Button("Select all", id="dep-all",   classes="btn-small")
                        yield Button("Clear all",  id="dep-clear", classes="btn-small")
                    yield ScrollableContainer(
                        Vertical(id="dep-checks"),
                        id="dep-scroll",
                    )
                    yield Static(
                        "No deployments found — select a namespace and click Refresh",
                        id="dep-empty",
                        classes="field-warn",
                    )

                    yield Rule()
                    yield _section("Log mode")
                    with RadioSet(id="mode-radio"):
                        yield RadioButton("Stream  — live tail", value=True, id="mode-stream")
                        yield RadioButton("Dump    — fetch existing logs then stop", id="mode-dump")
                    with Vertical(id="dump-opts"):
                        yield Label("Last N lines:", classes="field-label")
                        yield Input(placeholder="e.g. 500", id="dump-tail")
                        yield Label("— or since:", classes="field-label")
                        yield Input(placeholder="e.g. 1h, 30m", id="dump-since")
                    with Vertical(id="stream-opts"):
                        yield Label("Since:", classes="field-label")
                        yield Input(placeholder="e.g. 1h, 30m — leave blank for new lines only", id="stream-since")
                        yield Static(
                            "[dim]Leave blank (or enter 0) to only collect new lines from the "
                            "moment the stream starts. Set a duration to also pull in recent "
                            "history when it starts.[/dim]\n"
                            "[dim]Note: with a duration set, nothing is displayed until every "
                            "pod's backlog is fetched and sorted into order — a long duration "
                            "or high-volume pods can mean a delay of several seconds before the "
                            "stream first appears.[/dim]",
                            classes="field-hint",
                            markup=True,
                        )

                with Horizontal(classes="row nav-row"):
                    yield Button("Cancel", variant="error",   id="cancel-1", classes="btn-cancel")
                    yield Button("Next →", variant="primary", id="next-1",   classes="btn-next")

            # ── Tab 2: Patterns ───────────────────────────────────────────────
            with TabPane("Patterns", id="tab-strings"):
                with ScrollableContainer(id="strings-scroll"):

                    with Horizontal(classes="row", id="patterns-edit-row"):
                        yield Static(
                            "Saved patterns are stored in ~/.config/kube-orb/strings.yaml",
                            classes="field-hint",
                            id="patterns-file-hint",
                        )
                        yield Button("Edit in text editor", id="edit-patterns-file", classes="btn-small", variant="primary")
                        yield Button("↺ Reload", id="reload-patterns", classes="btn-small")

                    yield Rule()
                    yield _section("Filters — hide matching lines")
                    yield Label("Saved  (check to activate):", classes="field-label saved-label")
                    yield ScrollableContainer(Vertical(id="filter-checks"), id="filter-scroll")
                    yield Label("Add new:", classes="field-label new-label")
                    yield Input(placeholder="e.g. ERROR, /5[0-9]{2}/  (comma-separated)", id="filter-input")
                    with Horizontal(classes="row option-row"):
                        yield Checkbox("Save new to list", id="filter-save", value=True)
                        yield Checkbox("Ignore case",      id="filter-icase", value=False)

                    yield Rule()
                    yield _section("Highlights — emphasise matching lines")
                    yield Label("Saved  (check to activate):", classes="field-label saved-label")
                    yield ScrollableContainer(Vertical(id="hl-checks"), id="hl-scroll")
                    yield Label("Add new:", classes="field-label new-label")
                    yield Input(placeholder="e.g. WARN, brute force  (comma-separated)", id="hl-input")
                    with Horizontal(classes="row option-row"):
                        yield Checkbox("Save new to list", id="hl-save",   value=True)
                        yield Checkbox("Ignore case",      id="hl-icase",  value=False)

                    with Vertical(id="monitor-section"):
                        yield Rule()
                        yield _section("Monitors — copy matches to monitor panel")
                        yield Label("Saved  (check to activate):", classes="field-label saved-label")
                        yield ScrollableContainer(Vertical(id="mon-checks"), id="mon-scroll")
                        yield Label("Add new:", classes="field-label new-label")
                        yield Input(placeholder="e.g. job failed, OOM  (comma-separated)", id="mon-input")
                        with Horizontal(classes="row option-row"):
                            yield Checkbox("Save new to list", id="mon-save",  value=True)
                            yield Checkbox("Ignore case",      id="mon-icase", value=False)

                with Horizontal(classes="row nav-row"):
                    yield Button("Cancel", variant="error",   id="cancel-2", classes="btn-cancel")
                    yield Button("← Back", variant="default", id="back-2",   classes="btn-back")
                    yield Button("Next →", variant="primary", id="next-2",   classes="btn-next")

            # ── Tab 3: Options ────────────────────────────────────────────────
            with TabPane("Options", id="tab-options"):
                with ScrollableContainer(id="options-scroll"):

                    with Vertical(id="health-section"):
                        yield _section("Pod health monitoring")
                        yield Checkbox("Enable health panel", id="health-enable", value=False)
                        with Vertical(id="health-opts"):
                            yield Label("Check interval (minutes, min 1):", classes="field-label")
                            yield Input("5", id="health-interval")

                    yield Rule()
                    yield _section("Display")
                    yield Checkbox(
                        "Color full line  (default: color pod name only)",
                        id="color-full-line",
                        value=False,
                    )
                    yield Checkbox(
                        "Line wrap  (default: on)",
                        id="line-wrap",
                        value=True,
                    )
                    yield Checkbox(
                        "Format JSON logs  (extract level/message/time; raw otherwise)",
                        id="json-format",
                        value=False,
                    )

                    yield Rule()
                    yield _section("Save config for reuse")
                    yield Label("Name — leave blank to skip:", classes="field-label")
                    yield Input(placeholder="e.g. prod-debug", id="save-name")

                with Horizontal(classes="row nav-row"):
                    yield Button("Cancel",   variant="error",   id="cancel",  classes="btn-cancel")
                    yield Button("← Back",   variant="default", id="back-3",  classes="btn-back")
                    yield Button("Launch →", variant="primary", id="launch",  classes="btn-next")

        yield Static("Ctrl+Q to cancel at any time", id="wizard-footer")

    # ── Mount ─────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.query_one("#dump-opts").display = False
        self.query_one("#stream-opts").display = True
        self.query_one("#health-opts").display = False
        self._load_saved_strings()
        self._populate_namespaces()

    # ── Namespace helpers ─────────────────────────────────────────────────────

    def _populate_namespaces(self) -> None:
        from .. import kubectl as k
        try:
            namespaces = k.get_namespaces()
        except Exception:
            namespaces = [self._initial_namespace]

        self._known_namespaces = namespaces
        self._initializing_ns = True
        sel = self.query_one("#ns-select", Select)
        options = [(ns, ns) for ns in namespaces]
        sel.set_options(options)

        if self._initial_namespace in namespaces:
            sel.value = self._initial_namespace
        elif namespaces:
            sel.value = namespaces[0]

        self.query_one("#ns-header", Static).update(
            f"kubectl context: {self._initial_namespace}"
        )

        def _after_init() -> None:
            self._initializing_ns = False
            self._refresh_deployments()
            self._refresh_saved_configs()

        self.call_after_refresh(_after_init)

    def _active_namespace(self) -> str:
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
        self._last_refreshed_ns = ns
        self._deployments = []
        self._pod_counts = {}
        self.query_one("#dep-checks", Vertical).remove_children()

        # Consume immediately — this is the one mount this pending selection
        # was set for. Any later, unrelated refresh should default to all-checked.
        pending = self._pending_deployments
        self._pending_deployments = None

        try:
            deps = k.get_deployments(ns)
            self._deployments = [d.name for d in deps]
            self._pod_counts = {d.name: d.pod_count for d in deps}
        except Exception as exc:
            self.query_one("#dep-empty", Static).update(f"Error: {exc}")
            self.query_one("#dep-empty").display = True
            return

        if not self._deployments:
            self.query_one("#dep-empty", Static).update(
                f"No deployments found in '{ns}'"
            )
            self.query_one("#dep-empty").display = True
            return

        self.query_one("#dep-empty").display = False

        names = list(self._deployments)
        counts = dict(self._pod_counts)
        self.run_worker(
            self._mount_dep_checks(names, counts, pending),
            exclusive=True,
            name="dep-mount",
        )

    async def _mount_dep_checks(
        self, names: list[str], counts: dict[str, int], pending: set[str] | None
    ) -> None:
        dep_container = self.query_one("#dep-checks", Vertical)
        await dep_container.remove_children()
        for name in names:
            count = counts.get(name, 0)
            checked = True if pending is None else (name in pending)
            await dep_container.mount(
                Checkbox(
                    f"{name}  ({count} pod{'s' if count != 1 else ''})",
                    value=checked,
                    id=f"dep-{name}",
                )
            )


    # ── String helpers ────────────────────────────────────────────────────────

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

        def _do_mount() -> None:
            for s in strings:
                # Content(s) (not the raw str) — Checkbox labels parse Textual
                # markup by default, and a pattern like "[debug]" is valid
                # (empty) markup syntax that would otherwise render blank.
                # No ID needed — these are never queried individually.
                container.mount(Checkbox(Content(s), value=(s in active)))

        self.call_after_refresh(_do_mount)

    # ── Saved config helpers ──────────────────────────────────────────────────

    def _refresh_saved_configs(self) -> None:
        from ..config import list_all_saved_configs
        all_configs = list_all_saved_configs()
        sel = self.query_one("#cfg-select", Select)
        options = [(f"{name}  [{ns}]", f"{ns}::{name}") for ns, name in all_configs]
        sel.set_options(options if options else [("(no saved configs)", "__none__")])

    def _apply_saved_config(self, ns: str, name: str) -> None:
        from ..config import load_session_config
        cfg = load_session_config(ns, name)
        if cfg is None:
            return

        # Set before triggering any deployment refresh, so whichever refresh
        # actually mounts the checkboxes (sync or async) picks up the saved
        # selection instead of defaulting every deployment to checked.
        self._pending_deployments = set(cfg.deployments)

        # Restore namespace. Setting the dropdown may also (asynchronously)
        # fire on_select_changed, which would call _refresh_deployments()
        # itself — but that handler skips redundant refreshes via
        # _last_refreshed_ns, so our explicit call below always wins.
        ns_sel = self.query_one("#ns-select", Select)
        if ns in self._known_namespaces:
            ns_sel.value = ns
            self.query_one("#ns-input", Input).value = ""
        else:
            # Unknown namespace — use manual input instead of the dropdown
            self.query_one("#ns-input", Input).value = ns
        self._refresh_deployments()

        self._populate_string_checks("filter-checks", self._saved_filters,    cfg.filters)
        self._populate_string_checks("hl-checks",     self._saved_highlights,  cfg.highlights)
        self._populate_string_checks("mon-checks",    self._saved_monitors,    cfg.monitors)

        buttons = list(self.query_one("#mode-radio", RadioSet).query(RadioButton))
        target = 1 if cfg.mode == LogMode.DUMP else 0
        if target < len(buttons):
            buttons[target].value = True

        if cfg.tail:
            self.query_one("#dump-tail", Input).value = str(cfg.tail)
        if cfg.since:
            self.query_one("#dump-since", Input).value = cfg.since
            self.query_one("#stream-since", Input).value = cfg.since

        self.query_one("#health-enable",  Checkbox).value = cfg.health.enabled
        self.query_one("#health-interval", Input).value   = str(cfg.health.interval_minutes)
        self.query_one("#color-full-line", Checkbox).value = cfg.color_full_line
        self.query_one("#line-wrap",       Checkbox).value = cfg.line_wrap
        self.query_one("#json-format",     Checkbox).value = cfg.json_format
        self.query_one("#filter-icase",   Checkbox).value = cfg.filters_ignore_case
        self.query_one("#hl-icase",       Checkbox).value = cfg.highlights_ignore_case
        self.query_one("#mon-icase",      Checkbox).value = cfg.monitors_ignore_case
        if cfg.name:
            self.query_one("#save-name", Input).value = cfg.name

    # ── Events ────────────────────────────────────────────────────────────────

    def _switch_tab(self, tab_id: str) -> None:
        from textual.widgets import Tab
        from textual.widgets._tabbed_content import ContentTab, ContentTabs
        content_tabs = self.query_one("#wizard-tabs", TabbedContent).query_one(ContentTabs)
        tab = content_tabs.query_one(f"#{ContentTab.add_prefix(tab_id)}", Tab)
        tab.post_message(Tab.Clicked(tab))

    def _open_patterns_file(self) -> None:
        import os
        import subprocess
        from pathlib import Path
        path = Path.home() / ".config" / "kube-orb" / "strings.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("filters: []\nhighlights: []\nmonitors: []\n")
        editor = os.environ.get("EDITOR", "")
        try:
            if editor:
                subprocess.Popen([editor, str(path)])
            elif os.uname().sysname == "Darwin":
                subprocess.Popen(["open", "-t", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            self.notify(f"Opened {path}", severity="information")
        except Exception as exc:
            self.notify(f"Could not open editor: {exc}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "edit-patterns-file":
                self._open_patterns_file()
            case "reload-patterns":
                self._load_saved_strings()
                self.notify("Saved patterns reloaded")
            case "dep-all":
                for cb in self.query("#dep-checks Checkbox"):
                    cb.value = True
            case "dep-clear":
                for cb in self.query("#dep-checks Checkbox"):
                    cb.value = False
            case "next-1":
                self._switch_tab("tab-strings")
            case "next-2":
                self._switch_tab("tab-options")
            case "back-2":
                self._switch_tab("tab-targets")
            case "back-3":
                self._switch_tab("tab-strings")
            case "launch":
                self._launch()
            case "cancel" | "cancel-1" | "cancel-2":
                self.action_cancel()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        is_dump = event.index == 1
        self.query_one("#dump-opts").display = is_dump
        self.query_one("#stream-opts").display = not is_dump
        self.query_one("#monitor-section").display = not is_dump
        self.query_one("#health-section").display = not is_dump

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "health-enable":
            self.query_one("#health-opts").display = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ns-input" and event.value.strip():
            self._refresh_deployments()
            self._refresh_saved_configs()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "ns-select":
            if self._initializing_ns:
                return
            self.query_one("#ns-input", Input).value = ""
            if self._active_namespace() == self._last_refreshed_ns:
                # _apply_saved_config already refreshed for this namespace
                # itself; this is a queued Select.Changed catching up. Skip
                # it so it doesn't remount checkboxes without the saved
                # deployment selection applied.
                return
            self._refresh_deployments()
            self._refresh_saved_configs()
        elif event.select.id == "cfg-select":
            value = event.value
            if value and value != "__none__" and value is not Select.BLANK:
                ns, _, name = str(value).partition("::")
                self._apply_saved_config(ns, name)

    # ── Launch ────────────────────────────────────────────────────────────────

    def _launch(self) -> None:
        from ..config import add_to_saved_strings, parse_string_input

        ns = self._active_namespace()
        if not ns:
            self.notify("Select or enter a namespace.", severity="warning")
            return

        deployments = [
            cb.label.plain.split("  (")[0]
            for cb in self.query("#dep-checks Checkbox")
            if cb.value
        ]
        if not deployments:
            self.notify("Select at least one service.", severity="warning")
            return

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
        else:
            since_raw = self.query_one("#stream-since", Input).value.strip()
            if since_raw:
                since = since_raw

        def collect(
            checks_id: str, saved: list[str], input_id: str, save_id: str
        ) -> list[str]:
            active = [
                s for cb, s in zip(self.query(f"#{checks_id} Checkbox"), saved)
                if cb.value
            ]
            raw = self.query_one(f"#{input_id}", Input).value.strip()
            new = parse_string_input(raw) if raw else []
            merged = active + [s for s in new if s not in active]
            if new and self.query_one(f"#{save_id}", Checkbox).value:
                truly_new = [s for s in new if s not in saved]
                if truly_new:
                    cat = save_id.split("-")[0]
                    cat_map = {"filter": "filters", "hl": "highlights", "mon": "monitors"}
                    add_to_saved_strings(cat_map[cat], truly_new)
            return merged

        filters    = collect("filter-checks", self._saved_filters,    "filter-input", "filter-save")
        highlights = collect("hl-checks",     self._saved_highlights,  "hl-input",     "hl-save")
        monitors: list[str] = []
        if not is_dump:
            monitors = collect("mon-checks", self._saved_monitors, "mon-input", "mon-save")

        filters_ignore_case    = self.query_one("#filter-icase", Checkbox).value
        highlights_ignore_case = self.query_one("#hl-icase",     Checkbox).value
        monitors_ignore_case   = self.query_one("#mon-icase",    Checkbox).value if not is_dump else False

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

        color_full_line = self.query_one("#color-full-line", Checkbox).value
        line_wrap       = self.query_one("#line-wrap",       Checkbox).value
        json_format     = self.query_one("#json-format",     Checkbox).value
        save_name = self.query_one("#save-name", Input).value.strip() or None

        config = SessionConfig(
            namespace=ns,
            deployments=deployments,
            mode=mode,
            tail=tail,
            since=since,
            filters=filters,
            highlights=highlights,
            monitors=monitors,
            filters_ignore_case=filters_ignore_case,
            highlights_ignore_case=highlights_ignore_case,
            monitors_ignore_case=monitors_ignore_case,
            health=health,
            color_full_line=color_full_line,
            line_wrap=line_wrap,
            json_format=json_format,
            name=save_name,
        )

        if save_name:
            from ..config import save_session_config
            save_session_config(config)

        self.dismiss(config)

    def action_cancel(self) -> None:
        self.dismiss(None)
