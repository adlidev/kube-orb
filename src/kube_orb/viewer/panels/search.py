"""
SearchPanel — live search across the log buffer.

Filters the main stream buffer in real time as the user types.
Double-clicking a result pauses the main stream and jumps to that line.
"""
from __future__ import annotations

import asyncio
import re
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, Label, ListItem, ListView

from ...models import LogLine
from ..widgets import DragResizeHeader


class SearchPanel(Vertical):
    """Collapsible search panel."""

    DEFAULT_HEIGHT = "20%"

    BINDINGS = [
        Binding("escape", "close", "Close search", show=False),
    ]

    class LineSelected(Message):
        """Posted when user double-clicks a search result."""
        def __init__(self, line: LogLine) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = False
        self._pre_collapse_height = None
        self._results: list[LogLine] = []
        self._color_map: dict[str, str] = {}
        self._color_full_line = False
        self._pattern: re.Pattern | None = None
        self._debounce_task: asyncio.Task | None = None
        self._last_click: dict[int, float] = {}

    def compose(self) -> ComposeResult:
        yield _SearchHeader(id="search-header")
        yield Input(placeholder="Search logs …", id="search-input")
        yield ListView(id="search-results")

    def set_color_map(self, color_map: dict[str, str]) -> None:
        self._color_map = color_map

    def set_color_mode(self, full_line: bool) -> None:
        self._color_full_line = full_line

    def set_wrap(self, wrap: bool) -> None:
        lv = self.query_one("#search-results", ListView)
        lv.set_class(wrap, "wrap-on")
        lv.set_class(not wrap, "wrap-off")

    def search(self, buffer: list[LogLine], query: str) -> None:
        lv = self.query_one("#search-results", ListView)
        lv.clear()
        self._results = []
        self._pattern = None
        self._last_click.clear()

        if not query:
            self.query_one(_SearchHeader).update_count(0)
            return

        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        self._pattern = pattern
        matched = [line for line in buffer if pattern.search(line.content)]
        self._results = matched

        for line in matched[-500:]:
            color = self._color_map.get(line.pod_name, "#ffffff")
            text = Text()
            if self._color_full_line:
                text.append(f"[{line.pod_name}] ", style=f"bold {color}")
                _append_highlighted(text, line.content, pattern,
                                    base_style=color, hl_style=f"bold {color} on #333300")
            else:
                text.append(f"[{line.pod_name}] ", style=color)
                _append_highlighted(text, line.content, pattern)
            lv.append(ListItem(Label(text)))

        self.query_one(_SearchHeader).update_count(len(matched))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None:
            return
        now = time.monotonic()
        last = self._last_click.get(idx, 0.0)
        self._last_click[idx] = now
        if now - last < 0.5:
            # Double-click
            if idx < len(self._results):
                self.post_message(self.LineSelected(self._results[idx]))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            if self._debounce_task is not None:
                self._debounce_task.cancel()
            self._debounce_task = asyncio.get_event_loop().create_task(
                self._debounced_search(event.value)
            )

    async def _debounced_search(self, query: str) -> None:
        await asyncio.sleep(0.3)
        app = self.app
        if hasattr(app, "_buffer"):
            self.search(app._buffer, query)  # type: ignore[union-attr]

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        for widget in self.query("#search-input, #search-results"):
            widget.display = not self._collapsed
        if self._collapsed:
            self._pre_collapse_height = self.styles.height
            self.styles.height = "auto"
        else:
            self.styles.height = self._pre_collapse_height
        self.set_class(self._collapsed, "-collapsed")
        self.query_one(_SearchHeader).update_collapsed(self._collapsed)

    def action_close(self) -> None:
        self.display = False
        try:
            self.app.query_one("#stream-log").focus()
        except Exception:
            pass


def _append_highlighted(
    text: Text,
    content: str,
    pattern: re.Pattern,
    base_style: str = "",
    hl_style: str = "bold #ffff00 on #333300",
) -> None:
    cursor = 0
    for m in pattern.finditer(content):
        if m.start() > cursor:
            text.append(content[cursor:m.start()], style=base_style)
        text.append(content[m.start():m.end()], style=hl_style)
        cursor = m.end()
    if cursor < len(content):
        text.append(content[cursor:], style=base_style)


class _SearchHeader(DragResizeHeader):
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
