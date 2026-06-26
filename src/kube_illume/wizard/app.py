"""
Kube-illume setup wizard — single-page form.
Returns a SessionConfig on completion or None if the user cancels.
"""
from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from ..models import SessionConfig
from .screens import SinglePageWizard


class WizardApp(App[SessionConfig | None]):

    TITLE = "kube-illume setup"
    CSS_PATH = "wizard.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Cancel", show=True),
    ]

    def __init__(self, initial_namespace: str = "default") -> None:
        super().__init__()
        self._initial_namespace = initial_namespace

    def on_mount(self) -> None:
        self.push_screen(
            SinglePageWizard(initial_namespace=self._initial_namespace),
            self._on_done,
        )

    def _on_done(self, config: SessionConfig | None) -> None:
        self.exit(config)

    def action_quit(self) -> None:
        self.exit(None)
