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

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import RichLog, Static
from textual.containers import Vertical

from ...models import LogLine


class MainStreamPanel(Vertical):
    """Collapsible container wrapping the log display."""

    BINDINGS = [
        Binding("c", "toggle_collapse", "Collapse", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = False
        self._paused = False
        self._pending_count = 0
        self._color_full_line = False

    def set_color_mode(self, full_line: bool) -> None:
        self._color_full_line = full_line

    def compose(self):
        yield _StreamHeader(id="stream-header")
        yield _LogDisplay(id="stream-log", highlight=False, markup=False,
                          wrap=True, auto_scroll=True)

    def add_line(self, line: LogLine, color: str, is_highlight: bool) -> None:
        log = self.query_one(_LogDisplay)
        text = Text()
        if self._color_full_line:
            text.append(f"[{line.pod_name}] ", style=f"bold {color}")
            if is_highlight:
                text.append(line.content, style=f"bold {color} on #333300")
            else:
                text.append(line.content, style=color)
        else:
            text.append(f"[{line.pod_name}] ", style=color)
            if is_highlight:
                text.append(line.content, style="bold #ffff00")
            else:
                text.append(line.content)
        log.write(text)

    def clear(self) -> None:
        self.query_one(_LogDisplay).clear()

    def set_paused(self, paused: bool, pending: int = 0) -> None:
        self._paused = paused
        self._pending_count = pending
        log = self.query_one(_LogDisplay)
        log.auto_scroll = not paused
        self.query_one(_StreamHeader).update_pause(paused, pending)

    def jump_to_line(self, line: LogLine) -> None:
        """Scroll to and highlight a specific line in the buffer."""
        log = self.query_one(_LogDisplay)
        # Search backwards through the rich log for the matching line
        # Textual's RichLog doesn't expose line index directly,
        # so we scroll to bottom then use the line's position in the buffer.
        # For now we highlight by scrolling to end and marking paused.
        # A full implementation would require tracking line positions.
        log.scroll_end(animate=False)

    def toggle_collapsed(self) -> None:
        log = self.query_one(_LogDisplay)
        self._collapsed = not self._collapsed
        log.display = not self._collapsed
        self.query_one(_StreamHeader).update_collapsed(self._collapsed)

    def action_toggle_collapse(self) -> None:
        self.toggle_collapsed()


class _StreamHeader(Static):
    """Header bar showing title and pause status."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._paused = False
        self._pending = 0
        self._collapsed = False
        self._refresh()

    def update_pause(self, paused: bool, pending: int) -> None:
        self._paused = paused
        self._pending = pending
        self._refresh()

    def update_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._refresh()

    def _refresh(self) -> None:
        arrow = "▶" if self._collapsed else "▼"
        title = f"{arrow} Main Stream"
        if self._paused:
            if self._pending:
                title += f"  [PAUSED +{self._pending} lines — Space to resume]"
            else:
                title += "  [PAUSED — Space to resume]"
        self.update(title)

    def on_click(self) -> None:
        self.parent.toggle_collapsed()  # type: ignore[union-attr]


class _LogDisplay(RichLog):
    """The actual scrollable log widget. Pauses on scroll-up or click."""

    def on_scroll_up(self) -> None:
        # Bubble pause signal to the parent app
        app = self.app
        if hasattr(app, "set_paused"):
            app.set_paused(True)  # type: ignore[union-attr]

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "set_paused"):
            app.set_paused(True)  # type: ignore[union-attr]
