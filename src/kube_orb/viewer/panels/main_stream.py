"""
MainStreamPanel — primary log display.

Features:
  - Colored pod-name prefix per line
  - Highlight support (bold + color emphasis)
  - Auto-scroll to bottom unless paused
  - Pause triggered by: scroll-up, clicking a line, or line-select in other panels
  - PAUSED indicator in header showing buffered line count
  - Jump-to-line from search/monitor panels
"""
from __future__ import annotations

import re

from rich.text import Text
from textual.message import Message
from textual.widgets import RichLog, Static
from textual.containers import Vertical

from ...models import LogLine


def _append_with_highlights(
    text: Text,
    content: str,
    patterns: list[re.Pattern],
    base_style: str,
    hl_style: str,
) -> None:
    """Append content to text, highlighting only the matched spans."""
    # Collect all match spans, merge overlaps, sort
    spans: list[tuple[int, int]] = []
    for pat in patterns:
        for m in pat.finditer(content):
            if m.start() < m.end():
                spans.append((m.start(), m.end()))
    spans.sort()

    # Merge overlapping spans
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


class MainStreamPanel(Vertical):
    """Collapsible container wrapping the log display."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = False
        self._paused = False
        self._pending_count = 0
        self._color_full_line = False

    def set_color_mode(self, full_line: bool) -> None:
        self._color_full_line = full_line

    def set_wrap(self, wrap: bool) -> None:
        self.query_one(_LogDisplay).wrap = wrap

    def compose(self):
        yield _StreamHeader(id="stream-header")
        yield _LogDisplay(id="stream-log", highlight=False, markup=False,
                          wrap=True, auto_scroll=True)

    def add_line(
        self,
        line: LogLine,
        color: str,
        highlight_patterns: list[re.Pattern] | None = None,
        is_target: bool = False,
    ) -> None:
        log = self.query_one(_LogDisplay)
        text = Text()
        prefix = f"[{line.pod_name}] "
        content = line.content

        if is_target:
            text.append("▶ ", style="bold #ff8800")
            text.append(prefix, style=f"bold {color}")
            text.append(content, style="bold white on #2a2a00")
        elif self._color_full_line:
            text.append(prefix, style=f"bold {color}")
            if highlight_patterns:
                _append_with_highlights(text, content, highlight_patterns,
                                        base_style=color, hl_style=f"bold {color} on #333300")
            else:
                text.append(content, style=color)
        else:
            text.append(prefix, style=color)
            if highlight_patterns:
                _append_with_highlights(text, content, highlight_patterns,
                                        base_style="", hl_style="bold #ffff00")
            else:
                text.append(content)
        log.write(text)

    def clear(self) -> None:
        self.query_one(_LogDisplay).clear()

    def set_paused(self, paused: bool, pending: int = 0) -> None:
        self._paused = paused
        self._pending_count = pending
        log = self.query_one(_LogDisplay)
        log.auto_scroll = not paused
        self.query_one(_StreamHeader).update_pause(paused, pending)

    def scroll_to_end(self) -> None:
        self.query_one(_LogDisplay).scroll_end(animate=False)

    def toggle_collapsed(self) -> None:
        log = self.query_one(_LogDisplay)
        self._collapsed = not self._collapsed
        log.display = not self._collapsed
        self.query_one(_StreamHeader).update_collapsed(self._collapsed)


class _StreamHeader(Static):
    """Header bar showing title and pause status.

    When paused, the header adds a `-paused` class (styled as a bright,
    high-contrast bar in viewer.tcss) and flashes by toggling `-blink-off`
    on a timer, so a paused stream is impossible to miss.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._paused = False
        self._pending = 0
        self._collapsed = False
        self._blink_timer = None
        self._refresh()

    def update_pause(self, paused: bool, pending: int) -> None:
        self._paused = paused
        self._pending = pending
        self.set_class(paused, "-paused")
        if paused and self._blink_timer is None:
            self._blink_timer = self.set_interval(0.5, self._toggle_blink)
        elif not paused and self._blink_timer is not None:
            self._blink_timer.stop()
            self._blink_timer = None
            self.remove_class("-blink-off")
        self._refresh()

    def _toggle_blink(self) -> None:
        self.toggle_class("-blink-off")

    def update_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._refresh()

    def _refresh(self) -> None:
        arrow = "▶" if self._collapsed else "▼"
        title = f"{arrow} Main Stream"
        if self._paused:
            if self._pending:
                title += f"  ⏸ PAUSED  +{self._pending} lines — Space to resume"
            else:
                title += "  ⏸ PAUSED — Space to resume"
        self.update(title)

    def on_click(self) -> None:
        self.parent.toggle_collapsed()  # type: ignore[union-attr]


class _LogDisplay(RichLog):
    """The actual scrollable log widget. Pauses on scroll-up, click, or drag."""

    def on_scroll_up(self) -> None:
        # ScrollUp message = clicking the scrollbar track above the thumb.
        app = self.app
        if hasattr(app, "set_paused"):
            app.set_paused(True)  # type: ignore[union-attr]

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "set_paused"):
            app.set_paused(True)  # type: ignore[union-attr]

    def _on_scroll_to(self, message) -> None:
        # Dragging the scrollbar thumb posts ScrollTo but does NOT trigger
        # on_scroll_up (that fires for track-clicks / the wheel), so without
        # this the app never pauses on a drag: auto_scroll stays on and the
        # next incoming line snaps the view back to the bottom, making the
        # thumb impossible to drag in a live stream. Pause while dragging;
        # if the drag lands at the bottom, resume live-follow.
        super()._on_scroll_to(message)
        app = self.app
        if hasattr(app, "set_paused") and message.y is not None:
            want_paused = message.y < self.max_scroll_y - 1
            # Only toggle when the state actually changes (auto_scroll is the
            # inverse of paused), to avoid redundant header re-renders and
            # repeated flush-worker spawns during a drag.
            if self.auto_scroll == want_paused:
                app.set_paused(want_paused)  # type: ignore[union-attr]
