"""
MainStreamPanel — primary log display.

Features:
  - Colored pod-name prefix per line
  - Highlight support (bold + color emphasis)
  - Auto-scroll to bottom unless paused
  - Pause triggered by: scroll-up, clicking a line, or line-select in other panels
  - PAUSED indicator in header showing buffered line count
  - Jump-to-line from search/monitor panels
  - Optional readable reformatting of detected JSON lines, with a detail
    modal (Enter, after clicking a line) showing the full pretty-printed JSON
  - Optional collapsing of consecutive identical lines from the same pod
    into a single "last line repeated N times" marker (journalctl-style)
"""
from __future__ import annotations

import re

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.widgets import RichLog, Static
from textual.containers import Vertical

from ...jsonlog import LEVEL_STYLES, ParsedJsonLine, parse_json_log_line
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


def _formatted_json_content(
    parsed: ParsedJsonLine,
    force_style: str | None,
    highlight_style: str | None,
) -> Text:
    """
    Build the readable one-line rendering of a parsed JSON line:
    `HH:MM:SS LEVEL  message  key=val key=val`.

    force_style: color-full-line mode passes the pod color here so it wins
    throughout instead of semantic level coloring.
    highlight_style: set when the line matched a highlight pattern — spans
    computed against the raw JSON text don't line up with this reformatted
    text, so a highlight match emphasizes the whole message instead of a
    precise span.
    """
    t = Text()
    dim_style = force_style or "dim"
    if parsed.timestamp:
        t.append(parsed.timestamp + "  ", style=dim_style)
    if parsed.level:
        level_style = highlight_style or force_style or LEVEL_STYLES.get(parsed.level.upper(), "bold")
        t.append(f"{parsed.level.upper():<5} ", style=level_style)
    t.append(parsed.message, style=highlight_style or force_style or "")
    if parsed.extras:
        t.append("  " + parsed.extras_text, style=dim_style)
    return t


class MainStreamPanel(Vertical):
    """Collapsible container wrapping the log display."""

    # When collapse-repeats is on and a run of identical lines never breaks
    # (e.g. a crash loop logging the exact same line forever), flush a
    # "still repeating" marker every this-many repeats rather than holding
    # it indefinitely — otherwise the display would look frozen even though
    # lines are still arriving.
    REPEAT_CHECKPOINT = 500

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = False
        self._pre_collapse_height = None
        self._paused = False
        self._pending_count = 0
        self._color_full_line = False
        self._json_format = False
        self._json_lines: dict[int, ParsedJsonLine] = {}
        self._next_line_idx = 0
        self._collapse_repeats = False
        # (line, color) of the most recently WRITTEN line, while collapsing
        # is on — used to recognize the next line as a repeat of it.
        self._pending_repeat: tuple[LogLine, str] | None = None
        self._repeat_count = 0

    def set_color_mode(self, full_line: bool) -> None:
        self._color_full_line = full_line

    def set_wrap(self, wrap: bool) -> None:
        self.query_one(_LogDisplay).wrap = wrap

    def set_json_format(self, enabled: bool) -> None:
        self._json_format = enabled

    def set_collapse_repeats(self, enabled: bool) -> None:
        self._collapse_repeats = enabled

    def get_parsed_json(self, idx: int) -> ParsedJsonLine | None:
        return self._json_lines.get(idx)

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
        # is_target lines (the jump-to-context / JSON-context views) are
        # always their own one-off render — never folded into a repeat run.
        if self._collapse_repeats and not is_target and self._is_repeat(line):
            self._repeat_count += 1
            if self._repeat_count % self.REPEAT_CHECKPOINT == 0:
                orig_line, orig_color = self._pending_repeat
                self._write_repeat_marker(orig_line, orig_color, self._repeat_count, ongoing=True)
                self._repeat_count = 0
            return

        self._flush_pending_repeat()
        self._write_line(line, color, highlight_patterns, is_target)
        if self._collapse_repeats and not is_target:
            self._pending_repeat = (line, color)
            self._repeat_count = 0
        else:
            self._pending_repeat = None

    def _is_repeat(self, line: LogLine) -> bool:
        if self._pending_repeat is None:
            return False
        prev_line, _ = self._pending_repeat
        return prev_line.pod_name == line.pod_name and prev_line.content == line.content

    def _flush_pending_repeat(self) -> None:
        """Emit the "repeated N times" marker for a just-ended run, if any."""
        if self._repeat_count > 0 and self._pending_repeat is not None:
            orig_line, orig_color = self._pending_repeat
            self._write_repeat_marker(orig_line, orig_color, self._repeat_count, ongoing=False)
        self._pending_repeat = None
        self._repeat_count = 0

    def _write_repeat_marker(self, orig_line: LogLine, color: str, n: int, ongoing: bool) -> None:
        log = self.query_one(_LogDisplay)
        text = Text()
        text.append(f"[{orig_line.pod_name}] ", style=color)
        times = "time" if n == 1 else "times"
        msg = f"↻ last line repeated {n} {times}"
        if ongoing:
            msg += " so far — still repeating…"
        text.append(msg, style="dim italic")
        log.write(text)

    def _write_line(
        self,
        line: LogLine,
        color: str,
        highlight_patterns: list[re.Pattern] | None,
        is_target: bool,
    ) -> None:
        log = self.query_one(_LogDisplay)
        text = Text()
        prefix = f"[{line.pod_name}] "
        content = line.content

        # Detection always runs (cheap early-exit for non-JSON lines) so the
        # Enter-for-detail feature works even when display formatting is off.
        parsed = parse_json_log_line(content)
        use_formatted = parsed is not None and self._json_format

        if is_target:
            text.append("▶ ", style="bold #ff8800")
            text.append(prefix, style=f"bold {color}")
            if use_formatted:
                text.append_text(_formatted_json_content(
                    parsed, force_style="bold white on #2a2a00", highlight_style=None))
            else:
                text.append(content, style="bold white on #2a2a00")
        elif self._color_full_line:
            text.append(prefix, style=f"bold {color}")
            if use_formatted:
                hl = f"bold {color} on #333300" if highlight_patterns else None
                text.append_text(_formatted_json_content(parsed, force_style=color, highlight_style=hl))
            elif highlight_patterns:
                _append_with_highlights(text, content, highlight_patterns,
                                        base_style=color, hl_style=f"bold {color} on #333300")
            else:
                text.append(content, style=color)
        else:
            text.append(prefix, style=color)
            if use_formatted:
                hl = "bold #ffff00 on #333300" if highlight_patterns else None
                text.append_text(_formatted_json_content(parsed, force_style=None, highlight_style=hl))
            elif highlight_patterns:
                _append_with_highlights(text, content, highlight_patterns,
                                        base_style="", hl_style="bold #ffff00 on #333300")
            else:
                text.append(content)

        if parsed is not None:
            idx = self._next_line_idx
            self._next_line_idx += 1
            self._json_lines[idx] = parsed
            text.stylize(Style(meta={"line_idx": idx}), 0, len(text))

        log.write(text)

    def clear(self) -> None:
        self.query_one(_LogDisplay).clear()
        self._json_lines.clear()
        self._next_line_idx = 0
        self._pending_repeat = None
        self._repeat_count = 0

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
        if self._collapsed:
            self._pre_collapse_height = self.styles.height
            self.styles.height = "auto"
        else:
            self.styles.height = self._pre_collapse_height
        self.set_class(self._collapsed, "-collapsed")
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
    """The actual scrollable log widget. Pauses on scroll-up, click, or drag.

    Clicking a line also selects it (tagged via a "line_idx" style meta —
    see MainStreamPanel.add_line) so Enter can open its JSON detail view,
    if it was a detected JSON line.
    """

    BINDINGS = [
        Binding("enter", "show_json_detail", "JSON detail", show=True),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.selected_line_idx: int | None = None

    def on_scroll_up(self) -> None:
        # ScrollUp message = clicking the scrollbar track above the thumb.
        app = self.app
        if hasattr(app, "set_paused"):
            app.set_paused(True)  # type: ignore[union-attr]

    def on_click(self, event) -> None:
        style = self.get_style_at(event.x, event.y)
        self.selected_line_idx = style.meta.get("line_idx")
        self.refresh_bindings()  # footer's "JSON detail" visibility depends on the selection
        app = self.app
        if hasattr(app, "set_paused"):
            app.set_paused(True)  # type: ignore[union-attr]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "show_json_detail":
            # Hide the hotkey from the footer entirely unless the currently
            # selected line is actually a detected JSON line — otherwise
            # it's advertised even when pressing it would do nothing.
            return self.selected_line_idx is not None
        return super().check_action(action, parameters)

    def action_show_json_detail(self) -> None:
        app = self.app
        if hasattr(app, "show_json_detail"):
            app.show_json_detail(self.selected_line_idx)  # type: ignore[union-attr]

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
