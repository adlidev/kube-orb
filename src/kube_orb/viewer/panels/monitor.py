"""
MonitorPanel — passive accumulation of monitor-string hits.

Lines matching monitor patterns are copied here without interrupting the main stream.
A single click selects a hit (Enter then shows ± context lines from the buffer,
like `grep -C`); double-clicking pauses the main stream and jumps to it.
Stream mode only.
"""
from __future__ import annotations

import re
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.widgets import Label

from ...config import matches
from ...models import LogLine
from ..widgets import DragResizeHeader

# Cap the number of rendered rows to avoid layout slowdown with large hit counts.
# _lines tracks the true total; only the most recent MAX_ROWS are shown.
_MAX_ROWS = 500

# Two clicks on the same row within this window count as a double-click.
_DOUBLE_CLICK_SECONDS = 0.5


class MonitorPanel(Vertical):
    """Collapsible monitor accumulation panel."""

    DEFAULT_HEIGHT = "20%"

    class LineSelected(Message):
        """Posted when the user double-clicks a monitor hit."""
        def __init__(self, line: LogLine) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = False
        self._pre_collapse_height = None
        self._lines: list[LogLine] = []
        self._color_map: dict[str, str] = {}
        self._color_full_line = False
        self._patterns: list[re.Pattern] = []

    def compose(self) -> ComposeResult:
        yield _MonitorHeader(id="monitor-header")
        with ScrollableContainer(id="monitor-scroll"):
            yield Vertical(id="monitor-list")

    def set_color_map(self, color_map: dict[str, str]) -> None:
        self._color_map = color_map

    def set_color_mode(self, full_line: bool) -> None:
        self._color_full_line = full_line

    def set_patterns(self, patterns: list[re.Pattern]) -> None:
        self._patterns = patterns

    def set_wrap(self, wrap: bool) -> None:
        sc = self.query_one("#monitor-scroll", ScrollableContainer)
        sc.set_class(wrap, "wrap-on")
        sc.set_class(not wrap, "wrap-off")

    def add_line(self, line: LogLine, color: str) -> None:
        self._lines.append(line)
        scroll = self.query_one("#monitor-scroll", ScrollableContainer)
        inner = self.query_one("#monitor-list", Vertical)

        at_top = scroll.scroll_y <= 1

        text = _build_text(line, color, self._patterns, self._color_full_line)
        # Prepend — newest hit at the top. mount(before=0) on Vertical is reliable.
        inner.mount(_MonitorRow(text, line), before=0)

        # Evict the oldest rendered row when we exceed the cap
        if len(inner.children) > _MAX_ROWS:
            inner.children[-1].remove()

        if at_top:
            scroll.scroll_home(animate=False)

        self.query_one(_MonitorHeader).update_count(len(self._lines))

    def rebuild(self, buffer: list[LogLine]) -> None:
        """
        Recompute the entire hit list from the full log buffer through the
        current monitor patterns. Called when monitors are edited live so
        unchecking a pattern drops its accumulated hits (and checking a new
        one back-fills matches already in the buffer).
        """
        inner = self.query_one("#monitor-list", Vertical)
        inner.remove_children()

        matched = (
            [line for line in buffer if matches(line.content, self._patterns)]
            if self._patterns
            else []
        )
        self._lines = matched

        # Render only the most recent _MAX_ROWS, prepending in order so the
        # newest hit ends up on top (matching add_line's ordering).
        for line in matched[-_MAX_ROWS:]:
            color = self._color_map.get(line.pod_name, "#ffffff")
            inner.mount(_MonitorRow(_build_text(line, color, self._patterns, self._color_full_line), line), before=0)

        self.query_one(_MonitorHeader).update_count(len(self._lines))

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.query_one("#monitor-scroll").display = not self._collapsed
        if self._collapsed:
            self._pre_collapse_height = self.styles.height
            self.styles.height = None
        else:
            self.styles.height = self._pre_collapse_height
        self.set_class(self._collapsed, "-collapsed")
        self.query_one(_MonitorHeader).update_collapsed(self._collapsed)


class _MonitorRow(Label):
    """
    A single monitor hit. Click selects (and focuses) it — Enter then opens
    a modal with ± context lines from the buffer around it. Double-click
    instead posts MonitorPanel.LineSelected, pausing and jumping to it in
    the main stream.
    """

    can_focus = True

    BINDINGS = [
        Binding("enter", "show_context", "Context", show=True),
    ]

    def __init__(self, text: Text, line: LogLine, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self.line = line
        self._last_click = 0.0

    def on_click(self) -> None:
        self.focus()
        now = time.monotonic()
        if now - self._last_click < _DOUBLE_CLICK_SECONDS:
            self.post_message(MonitorPanel.LineSelected(self.line))
            self._last_click = 0.0  # require two fresh clicks for the next jump
        else:
            self._last_click = now

    def action_show_context(self) -> None:
        app = self.app
        if hasattr(app, "show_monitor_context"):
            app.show_monitor_context(self.line)  # type: ignore[union-attr]


def _build_text(
    line: LogLine,
    color: str,
    patterns: list[re.Pattern],
    full_line: bool = False,
) -> Text:
    text = Text()
    if full_line:
        text.append(f"[{line.pod_name}] ", style=f"bold {color}")
        if patterns:
            _append_highlighted(text, line.content, patterns,
                                base_style=color, hl_style=f"bold {color} on #333300")
        else:
            text.append(line.content, style=color)
    else:
        text.append(f"[{line.pod_name}] ", style=color)
        if patterns:
            _append_highlighted(text, line.content, patterns)
        else:
            text.append(line.content)
    return text


def _append_highlighted(
    text: Text,
    content: str,
    patterns: list[re.Pattern],
    base_style: str = "",
    hl_style: str = "bold #ffff00",
) -> None:
    spans: list[tuple[int, int]] = []
    for pat in patterns:
        for m in pat.finditer(content):
            if m.start() < m.end():
                spans.append((m.start(), m.end()))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    cursor = 0
    for start, end in merged:
        if cursor < start:
            text.append(content[cursor:start], style=base_style)
        text.append(content[start:end], style=hl_style)
        cursor = end
    if cursor < len(content):
        text.append(content[cursor:], style=base_style)


class _MonitorHeader(DragResizeHeader):
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
