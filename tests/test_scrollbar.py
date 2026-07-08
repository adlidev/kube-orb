"""
Regression test: scrollbar thumbs must stay grabbable even for very long
content. Textual's default renderer lets the thumb shrink to 1 cell (e.g.
the main log stream can buffer up to 20,000 lines against a ~40-row
viewport), which is effectively impossible to click-drag with a real mouse.
_scrollbar.install() clamps the *visual* thumb size to a minimum without
touching the underlying drag math (verified below: dragging still lands
proportionally in the right place, not just "somewhere").
"""
from unittest.mock import patch

import pytest

from kube_orb import _scrollbar
from kube_orb.models import LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp


class TestMinimumScrollbarThumbSize:
    async def test_thumb_stays_grabbable_for_a_very_long_buffer(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                log = app.query_one("#stream-log")
                for i in range(5000):
                    log.write(f"line {i}")
                await pilot.pause()

                vsb = log.vertical_scrollbar
                assert vsb.renderer is _scrollbar._MinThumbScrollBarRender

                # With the real (unpatched) formula this thumb would round to
                # a single cell — confirm the scenario is actually exercising
                # the fix, not just a coincidentally-large thumb.
                ratio = vsb.window_virtual_size / vsb.region.height
                unpatched_thumb_size = max(1, vsb.window_size / ratio)
                assert round(unpatched_thumb_size) == 1

                # Content is auto-scrolled to the bottom, so the (enforced,
                # >=3-cell) thumb sits at the very bottom of the track. Grab
                # one row above the bottom edge — inside the enforced thumb,
                # but outside where a genuine 1-cell thumb would be.
                target_y = vsb.region.height - 2
                await pilot.mouse_down(vsb, offset=(0, target_y))
                await pilot.pause()
                assert vsb.grabbed is not None, "click one row above the bottom edge should grab the thumb"

                before = log.scroll_y
                await pilot.mouse_up(vsb, offset=(0, target_y - 15))
                await pilot.pause()

                # Dragging up 15 of the track's 44 rows should move scroll_y
                # by roughly that same fraction of the virtual size — not by
                # zero (didn't grab) and not by a single page (track click).
                expected_delta = 15 / vsb.region.height * vsb.window_virtual_size
                actual_delta = before - log.scroll_y
                assert actual_delta == pytest.approx(expected_delta, rel=0.15)
