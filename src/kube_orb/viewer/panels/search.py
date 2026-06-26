"""
SearchPanel — live search across the log buffer.

Filters the main stream buffer in real time as the user types.
Clicking a result pauses the main stream and jumps to that line.
"""
from __future__ import annotations

import re

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, Label, ListItem, ListView, Static

from ...models import LogLine


class SearchPanel(Vertical):
    """Collapsible search panel."""

    DEFAULT_HEIGHT = "20%"

    BINDINGS = [
        Binding("c",      "toggle_collapse", "Collapse", show=False),
        Binding("escape", "close",           "Close search", show=False),
    ]

    class LineSelected(Message):
        """Posted when user selects a search result."""
        def __init__(self, line: LogLine) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = False
        self._results: list[LogLine] = []
        self._color_map: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield _SearchHeader(id="search-header")
        yield Input(placeholder="Search logs …", id="search-input")
        yield ListView(id="search-results")

    def set_color_map(self, color_map: dict[str, str]) -> None:
        self._color_map = color_map

    def search(self, buffer: list[LogLine], query: str) -> None:
        """Run a search against the full log buffer and update results."""
        lv = self.query_one("#search-results", ListView)
        lv.clear()
        self._results = []

        if not query:
            return

        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        matches = [line for line in buffer if pattern.search(line.content)]
        self._results = matches

        for line in matches[-500:]:   # cap display at 500 results
            color = self._color_map.get(line.pod_name, "#ffffff")
            text = Text()
            text.append(f"[{line.pod_name}] ", style=color)
            text.append(line.content)
            lv.append(ListItem(Label(text)))

        self.query_one(_SearchHeader).update_count(len(matches))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            # Delegate to app which owns the buffer
            app = self.app
            if hasattr(app, "_buffer"):
                self.search(app._buffer, event.value)  # type: ignore[union-attr]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and idx < len(self._results):
            self.post_message(self.LineSelected(self._results[idx]))

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        for widget in self.query("#search-input, #search-results"):
            widget.display = not self._collapsed
        self.query_one(_SearchHeader).update_collapsed(self._collapsed)

    def action_toggle_collapse(self) -> None:
        self.toggle_collapsed()

    def action_close(self) -> None:
        self.display = False


class _SearchHeader(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=True, **kwargs)
        self._count = 0
        self._collapsed = False
        self._refresh()

    def update_count(self, count: int) -> None:
        self._count = count
        self._refresh()

    def update_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._refresh()

    def _refresh(self) -> None:
        arrow = "▶" if self._collapsed else "▼"
        suffix = f" ({self._count} results)" if self._count else ""
        hint = "" if self._collapsed else "  [dim]/ or Esc to close[/dim]"
        self.update(f"{arrow} Search{suffix}{hint}")

    def on_click(self) -> None:
        self.parent.toggle_collapsed()  # type: ignore[union-attr]
