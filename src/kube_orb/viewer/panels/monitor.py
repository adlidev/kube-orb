"""
MonitorPanel — passive accumulation of monitor-string hits.

Lines matching monitor patterns are copied here without interrupting the main stream.
Clicking a line pauses the main stream and jumps to it.
Stream mode only.
"""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static

from ...models import LogLine


class MonitorPanel(Vertical):
    """Collapsible monitor accumulation panel."""

    DEFAULT_HEIGHT = "20%"

    BINDINGS = [
        Binding("c", "toggle_collapse", "Collapse", show=False),
    ]

    class LineSelected(Message):
        """Posted when user selects a monitor hit."""
        def __init__(self, line: LogLine) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = False
        self._lines: list[LogLine] = []

    def compose(self) -> ComposeResult:
        yield _MonitorHeader(id="monitor-header")
        yield ListView(id="monitor-list")

    def add_line(self, line: LogLine, color: str) -> None:
        self._lines.append(line)
        lv = self.query_one("#monitor-list", ListView)
        text = Text()
        text.append(f"[{line.pod_name}] ", style=color)
        text.append(line.content)
        lv.append(ListItem(Label(text)))
        self.query_one(_MonitorHeader).update_count(len(self._lines))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and idx < len(self._lines):
            self.post_message(self.LineSelected(self._lines[idx]))

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.query_one("#monitor-list").display = not self._collapsed
        self.query_one(_MonitorHeader).update_collapsed(self._collapsed)

    def action_toggle_collapse(self) -> None:
        self.toggle_collapsed()


class _MonitorHeader(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
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
        suffix = f" ({self._count} hits)" if self._count else ""
        self.update(f"{arrow} Monitor{suffix}")

    def on_click(self) -> None:
        self.parent.toggle_collapsed()  # type: ignore[union-attr]
