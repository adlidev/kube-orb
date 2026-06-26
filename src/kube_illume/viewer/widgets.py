"""
Shared viewer widgets:
  - StringEditBar  — inline editor for E/H/M keybinds
  - ConfirmDialog  — yes/no prompt for destructive actions
  - SaveDialog     — filename prompt for Ctrl+S
"""
from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from ..config import add_to_saved_strings, parse_string_input


# ─── Inline string editor (E / H / M) ────────────────────────────────────────

class StringEditBar(Static):
    """
    Docked at the bottom of the viewer.
    Opens when user presses E, H, or M.
    Shows current strings, lets user add/remove, optionally saves new ones.
    """

    DEFAULT_CSS = """
    StringEditBar {
        dock: bottom;
        height: auto;
        display: none;
        background: $panel;
        padding: 0 1;
        border-top: tall $accent;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._category: str = ""
        self._current: list[str] = []
        self._callback: Callable[[list[str], bool], None] | None = None

    def compose(self) -> ComposeResult:
        yield Label("", id="edit-bar-label")
        yield Horizontal(
            Input(id="edit-bar-input", placeholder="Add strings (comma-separated) …"),
            Checkbox("Save to list", id="edit-bar-save", value=True),
            Button("Apply", variant="primary", id="edit-bar-apply"),
            Button("Cancel", id="edit-bar-cancel"),
        )

    def open(
        self,
        category: str,
        current: list[str],
        callback: Callable[[list[str], bool], None],
    ) -> None:
        self._category = category
        self._current = list(current)
        self._callback = callback

        label = self.query_one("#edit-bar-label", Label)
        existing = ", ".join(current) if current else "(none)"
        label.update(
            f"[bold]{category.title()}[/bold] — current: {existing}"
            f"  [dim]Enter to apply · Esc to cancel[/dim]"
        )

        inp = self.query_one("#edit-bar-input", Input)
        inp.value = ""
        inp.focus()

        self.display = True

    def _close(self) -> None:
        self.display = False
        self._callback = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-bar-cancel":
            self._close()
            return

        if event.button.id == "edit-bar-apply":
            raw = self.query_one("#edit-bar-input", Input).value.strip()
            new_strings = parse_string_input(raw) if raw else []
            merged = self._current + [s for s in new_strings if s not in self._current]
            save = self.query_one("#edit-bar-save", Checkbox).value
            if self._callback:
                self._callback(merged, save and bool(new_strings))
            self._close()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self._close()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "edit-bar-input":
            self.query_one("#edit-bar-apply", Button).press()


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
