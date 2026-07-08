"""
Shared viewer widgets:
  - DragResizeHeader — mixin: click toggles collapse, vertical drag resizes
  - StringEditModal  — modal editor for F/H/M keybinds
  - ConfirmDialog    — yes/no prompt for destructive actions
  - SaveDialog       — filename prompt for Ctrl+S
  - PodSelectorModal — add/remove deployments from the live stream
  - PaneSizeModal    — set pane heights by percentage (L keybind)
"""
from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from ..config import parse_string_input


# ─── Draggable/collapsible panel header ──────────────────────────────────────

class DragResizeHeader(Static):
    """
    Mixin for panel header bars: a plain click still toggles collapse (as
    before); a vertical drag resizes the panel by calling
    `self.app.resize_panel(self.parent, delta)` for each row of movement.
    The app owns the actual size math (it needs visibility into every panel
    to enforce the main stream's minimum height), this widget just reports
    drag deltas.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._drag_start_y: int | None = None
        self._dragging = False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if getattr(self.parent, "_collapsed", False):
            return  # collapsed panels only respond to a plain click (expand)
        self._drag_start_y = event.screen_y
        self._dragging = False
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_start_y is None:
            return
        delta = event.screen_y - self._drag_start_y
        if delta == 0:
            return
        self._dragging = True
        app = self.app
        if hasattr(app, "resize_panel"):
            app.resize_panel(self.parent, delta)
        self._drag_start_y = event.screen_y

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_start_y is not None:
            self.release_mouse()
        was_dragging = self._dragging
        self._drag_start_y = None
        self._dragging = False
        if not was_dragging:
            self.parent.toggle_collapsed()  # type: ignore[union-attr]


# ─── String editor modal (F / H / M) ─────────────────────────────────────────

class StringEditModal(ModalScreen[tuple[list[str], bool] | None]):
    """
    Modal opened by F / H / M — edit filters, highlights, or monitors.
    Shows saved + currently-active strings as checkboxes (check to activate,
    uncheck to deactivate — same pattern as the wizard's Patterns tab), plus
    an input to add brand-new ones. Dismisses with (new_strings, save_to_settings),
    or None if cancelled.
    """

    DEFAULT_CSS = """
    StringEditModal {
        align: center middle;
    }
    #string-edit-dialog {
        background: $surface;
        border: thick $accent;
        padding: 1 2;
        width: 70;
        height: auto;
        max-height: 80%;
    }
    #string-edit-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #string-edit-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    #string-edit-checks-scroll {
        height: auto;
        max-height: 14;
        border: tall $panel;
        margin-bottom: 1;
    }
    #string-edit-checks {
        height: auto;
    }
    #string-edit-input {
        margin-bottom: 1;
    }
    #string-edit-save {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel",  "Cancel"),
        Binding("enter",  "confirm", "Confirm"),
    ]

    def __init__(self, category: str, current: list[str], saved: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._category = category
        self._active = set(current)
        # Saved list first (stable, familiar order), then any currently-active
        # strings that aren't saved (e.g. typed in ad-hoc without saving) so
        # nothing currently in effect silently disappears from the list.
        self._options = list(saved) + [s for s in current if s not in saved]

    def compose(self) -> ComposeResult:
        with Vertical(id="string-edit-dialog"):
            yield Static(f"Edit {self._category}", id="string-edit-title")
            yield Static(
                "[dim]Check to activate · Enter to apply · Esc to cancel[/dim]",
                id="string-edit-hint",
                markup=True,
            )
            yield ScrollableContainer(
                Vertical(id="string-edit-checks"),
                id="string-edit-checks-scroll",
            )
            yield Input(id="string-edit-input", placeholder="Add new (comma-separated) …")
            yield Checkbox("Save new to saved settings", id="string-edit-save", value=True)
            yield Horizontal(
                Button("Apply [Enter]", variant="primary", id="string-edit-apply"),
                Button("Cancel [Esc]", id="string-edit-cancel"),
            )

    def on_mount(self) -> None:
        container = self.query_one("#string-edit-checks", Vertical)
        if not self._options:
            container.mount(Label("[dim](none saved yet)[/dim]", markup=True))
        else:
            for s in self._options:
                # Content(s) (not the raw str) — Checkbox labels parse Textual
                # markup by default, and a pattern like "[debug]" is valid
                # (empty) markup syntax that would otherwise render blank.
                container.mount(
                    Checkbox(Content(s), value=(s in self._active), id=f"str-{abs(hash(s))}")
                )
        self.query_one("#string-edit-input", Input).focus()

    def _checked(self) -> list[str]:
        result = []
        for s in self._options:
            try:
                if self.query_one(f"#str-{abs(hash(s))}", Checkbox).value:
                    result.append(s)
            except Exception:
                pass
        return result

    def _apply(self) -> None:
        raw = self.query_one("#string-edit-input", Input).value.strip()
        new_strings = parse_string_input(raw) if raw else []
        checked = self._checked()
        merged = checked + [s for s in new_strings if s not in checked]
        save = self.query_one("#string-edit-save", Checkbox).value and bool(new_strings)
        self.dismiss((merged, save))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "string-edit-cancel":
            self.dismiss(None)
        elif event.button.id == "string-edit-apply":
            self._apply()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "string-edit-input":
            self._apply()

    def action_confirm(self) -> None:
        self._apply()

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── Confirm dialog ────────────────────────────────────────────────────────────

class ConfirmDialog(ModalScreen[bool]):
    """Simple yes/no modal for destructive actions."""

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel",  "No"),
        Binding("escape", "cancel", "No"),
    ]

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        yield Static(self._message, id="confirm-msg")
        yield Horizontal(
            Button("Yes [Y]", variant="error",   id="confirm-yes"),
            Button("No  [N]", variant="primary", id="confirm-no"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ─── Save dialog ──────────────────────────────────────────────────────────────

class SaveDialog(ModalScreen[str | None]):
    """Filename prompt for Ctrl+S log save."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, default_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._default = default_name

    def compose(self) -> ComposeResult:
        yield Static("Save log buffer to file:  [dim]Enter to save · Esc to cancel[/dim]", id="save-label", markup=True)
        yield Input(value=self._default, id="save-input")
        yield Horizontal(
            Button("Save [Enter]", variant="primary", id="save-go"),
            Button("Cancel [Esc]", id="save-cancel"),
        )

    def on_mount(self) -> None:
        inp = self.query_one("#save-input", Input)
        inp.focus()
        inp.cursor_position = len(self._default)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-cancel":
            self.dismiss(None)
        elif event.button.id == "save-go":
            path = self.query_one("#save-input", Input).value.strip()
            self.dismiss(path or None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = event.value.strip()
        self.dismiss(path or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── Pod selector modal (P keybind) ──────────────────────────────────────────

class PodSelectorModal(ModalScreen[list[str] | None]):
    """
    Modal for adding/removing deployments from the live log stream.
    Returns the new list of selected deployment names, or None if cancelled.
    """

    DEFAULT_CSS = """
    PodSelectorModal {
        align: center middle;
    }
    #pod-selector-dialog {
        background: $surface;
        border: thick $accent;
        padding: 1 2;
        width: 60;
        height: auto;
        max-height: 80%;
    }
    #pod-selector-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #pod-selector-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    #pod-checks-scroll {
        height: auto;
        max-height: 20;
        border: tall $panel;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter",  "confirm", "Confirm"),
    ]

    def __init__(
        self,
        namespace: str,
        active_deployments: list[str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._namespace = namespace
        self._active = set(active_deployments)
        self._all_deployments: list[tuple[str, int]] = []  # (name, pod_count)

    def compose(self) -> ComposeResult:
        with Vertical(id="pod-selector-dialog"):
            yield Static("Manage log streams", id="pod-selector-title")
            yield Static(
                "[dim]Check deployments to stream · Esc to cancel · Enter to apply[/dim]",
                id="pod-selector-hint",
                markup=True,
            )
            yield ScrollableContainer(
                Vertical(id="pod-checks"),
                id="pod-checks-scroll",
            )
            yield Horizontal(
                Button("Apply [Enter]", variant="primary", id="pod-sel-apply"),
                Button("Cancel [Esc]", id="pod-sel-cancel"),
            )

    def on_mount(self) -> None:
        from .. import kubectl as k
        try:
            deps = k.get_deployments(self._namespace)
            self._all_deployments = [(d.name, d.pod_count) for d in deps]
        except Exception:
            self._all_deployments = [(name, 0) for name in self._active]

        container = self.query_one("#pod-checks", Vertical)
        for name, count in self._all_deployments:
            label = f"{name}  ({count} pod{'s' if count != 1 else ''})"
            container.mount(
                Checkbox(label, value=(name in self._active), id=f"pdep-{name}")
            )

    def _selected(self) -> list[str]:
        result = []
        for name, _ in self._all_deployments:
            try:
                cb = self.query_one(f"#pdep-{name}", Checkbox)
                if cb.value:
                    result.append(name)
            except Exception:
                pass
        return result

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pod-sel-apply":
            self.dismiss(self._selected())
        elif event.button.id == "pod-sel-cancel":
            self.dismiss(None)

    def action_confirm(self) -> None:
        self.dismiss(self._selected())

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── Pane size modal (L keybind) ──────────────────────────────────────────────

class PaneSizeModal(ModalScreen[dict[str, int] | None]):
    """
    Keyboard/click-driven alternative to dragging a panel's header border —
    set each currently-visible, non-collapsed side panel's height as a
    percentage of the viewer. Returns {label: percent} on Apply, or None if
    cancelled. The app validates and applies the result (it owns the
    MainStreamPanel-minimum-height math already used by drag-resize).
    """

    DEFAULT_CSS = """
    PaneSizeModal {
        align: center middle;
    }
    #pane-size-dialog {
        background: $surface;
        border: thick $accent;
        padding: 1 2;
        width: 50;
        height: auto;
    }
    #pane-size-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #pane-size-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    .pane-size-row {
        height: auto;
        margin-bottom: 1;
    }
    .pane-size-row Label {
        width: 14;
        padding-top: 1;
    }
    .pane-size-row Input {
        width: 10;
    }
    .pane-size-row Static {
        width: auto;
        padding: 1 0 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel",  "Cancel"),
        Binding("enter",  "confirm", "Confirm"),
    ]

    def __init__(self, entries: list[tuple[str, int]], **kwargs) -> None:
        """entries: (label, current_percent) for each visible, non-collapsed side panel."""
        super().__init__(**kwargs)
        self._entries = entries

    def compose(self) -> ComposeResult:
        with Vertical(id="pane-size-dialog"):
            yield Static("Pane sizes", id="pane-size-title")
            yield Static(
                "[dim]Percent of viewer height for each visible pane · "
                "the main stream takes whatever's left · "
                "Enter to apply · Esc to cancel[/dim]",
                id="pane-size-hint",
                markup=True,
            )
            for label, pct in self._entries:
                with Horizontal(classes="pane-size-row"):
                    yield Label(label)
                    yield Input(value=str(pct), id=f"pane-size-{label.lower()}", type="integer")
                    yield Static("%")
            yield Horizontal(
                Button("Apply [Enter]", variant="primary", id="pane-size-apply"),
                Button("Cancel [Esc]", id="pane-size-cancel"),
            )

    def on_mount(self) -> None:
        if self._entries:
            first_label = self._entries[0][0]
            self.query_one(f"#pane-size-{first_label.lower()}", Input).focus()

    def _collect(self) -> dict[str, int] | None:
        result: dict[str, int] = {}
        for label, _pct in self._entries:
            raw = self.query_one(f"#pane-size-{label.lower()}", Input).value.strip()
            try:
                pct = int(raw)
            except ValueError:
                self.notify(f"{label}: enter a whole number percentage.", severity="warning")
                return None
            if not (0 <= pct <= 100):
                self.notify(f"{label}: percentage must be between 0 and 100.", severity="warning")
                return None
            result[label] = pct
        return result

    def _apply(self) -> None:
        result = self._collect()
        if result is not None:
            self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pane-size-cancel":
            self.dismiss(None)
        elif event.button.id == "pane-size-apply":
            self._apply()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply()

    def action_confirm(self) -> None:
        self._apply()

    def action_cancel(self) -> None:
        self.dismiss(None)
