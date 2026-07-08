"""
Enforces a minimum scrollbar thumb size, app-wide.

Textual's default ScrollBarRender lets the thumb shrink to a single cell for
very long content (e.g. the main log stream, which buffers up to 20,000
lines — see ViewerApp._buffer_cap). A 1-cell thumb is nearly impossible to
grab with a real mouse in a terminal: clicks land on the track instead,
which pages the view rather than dragging it, making click-drag scrolling
feel broken. Clamping the *visual* thumb size doesn't affect drag math
(ScrollBar._on_mouse_move scales purely from window_size/virtual_size, not
from how big the thumb is drawn), so this is purely a grabbability fix.

render_bar() below is a fork of textual.scrollbar.ScrollBarRender.render_bar
(textual==8.2.7) with a single change: the thumb-size floor is MIN_THUMB_SIZE
instead of 1. It can't be done by pre-inflating the `window_size` argument
and delegating to super().render_bar() — window_size also drives the thumb's
*position* ratio there, so inflating it shifts the thumb as well as
resizing it. The size floor has to be applied after position is derived from
the real window_size, which means owning the whole method body.

Call install() once, early, before any scrollable widgets are composed.
"""
from __future__ import annotations

from math import ceil

from rich.color import Color
from rich.segment import Segment
from rich.segment import Segments
from rich.style import Style

from textual.scrollbar import ScrollBar, ScrollBarRender

MIN_THUMB_SIZE = 3


class _MinThumbScrollBarRender(ScrollBarRender):
    @classmethod
    def render_bar(
        cls,
        size: int = 25,
        virtual_size: float = 50,
        window_size: float = 20,
        position: float = 0,
        thickness: int = 1,
        vertical: bool = True,
        back_color: Color = Color.parse("#555555"),
        bar_color: Color = Color.parse("bright_magenta"),
    ) -> Segments:
        if vertical:
            bars = cls.VERTICAL_BARS
        else:
            bars = cls.HORIZONTAL_BARS

        back = back_color
        bar = bar_color

        len_bars = len(bars)

        width_thickness = thickness if vertical else 1

        _Segment = Segment
        _Style = Style
        blank = cls.BLANK_GLYPH * width_thickness

        foreground_meta = {"@mouse.down": "grab"}
        if window_size and size and virtual_size and size != virtual_size:
            bar_ratio = virtual_size / size
            thumb_size = max(MIN_THUMB_SIZE, window_size / bar_ratio)

            position_ratio = position / (virtual_size - window_size)
            position = (size - thumb_size) * position_ratio

            start = int(position * len_bars)
            end = start + ceil(thumb_size * len_bars)

            start_index, start_bar = divmod(max(0, start), len_bars)
            end_index, end_bar = divmod(max(0, end), len_bars)

            upper = {"@mouse.down": "scroll_up"}
            lower = {"@mouse.down": "scroll_down"}

            upper_back_segment = Segment(blank, _Style(bgcolor=back, meta=upper))
            lower_back_segment = Segment(blank, _Style(bgcolor=back, meta=lower))

            segments = [upper_back_segment] * int(size)
            segments[end_index:] = [lower_back_segment] * (size - end_index)

            segments[start_index:end_index] = [
                _Segment(blank, _Style(color=bar, reverse=True, meta=foreground_meta))
            ] * (end_index - start_index)

            # Apply the smaller bar characters to head and tail of scrollbar for more "granularity"
            if start_index < len(segments):
                bar_character = bars[len_bars - 1 - start_bar]
                if bar_character != " ":
                    segments[start_index] = _Segment(
                        bar_character * width_thickness,
                        (
                            _Style(bgcolor=back, color=bar, meta=foreground_meta)
                            if vertical
                            else _Style(
                                bgcolor=back,
                                color=bar,
                                meta=foreground_meta,
                                reverse=True,
                            )
                        ),
                    )
            if end_index < len(segments):
                bar_character = bars[len_bars - 1 - end_bar]
                if bar_character != " ":
                    segments[end_index] = _Segment(
                        bar_character * width_thickness,
                        (
                            _Style(
                                bgcolor=back,
                                color=bar,
                                meta=foreground_meta,
                                reverse=True,
                            )
                            if vertical
                            else _Style(bgcolor=back, color=bar, meta=foreground_meta)
                        ),
                    )
        else:
            style = _Style(bgcolor=back)
            segments = [_Segment(blank, style=style)] * int(size)
        if vertical:
            return Segments(segments, new_lines=True)
        else:
            return Segments((segments + [_Segment.line()]) * thickness, new_lines=False)


def install() -> None:
    ScrollBar.renderer = _MinThumbScrollBarRender
