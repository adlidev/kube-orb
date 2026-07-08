"""
Tests for ViewerApp.resize_panel() — draggable panel borders.

Dragging a side panel's header trades height with MainStreamPanel only
(never with a neighboring side panel), and must never let MainStreamPanel
shrink below MAIN_STREAM_MIN_HEIGHT.
"""
from unittest.mock import patch

from kube_orb.models import LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.search import SearchPanel


class TestResizePanel:
    async def test_growing_side_panel_shrinks_main_stream_by_the_same_amount(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                search = app.query_one(SearchPanel)
                search.display = True
                await pilot.pause()

                main_panel = app.query_one("#main-stream")
                before_search = search.size.height
                before_main = main_panel.size.height

                app.resize_panel(search, 5)
                await pilot.pause()

                assert search.size.height == before_search + 5
                assert main_panel.size.height == before_main - 5

    async def test_cannot_shrink_main_stream_below_minimum(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                search = app.query_one(SearchPanel)
                search.display = True
                await pilot.pause()

                main_panel = app.query_one("#main-stream")

                # Try to grow the side panel far beyond what's available.
                app.resize_panel(search, 1000)
                await pilot.pause()

                assert main_panel.size.height == app.MAIN_STREAM_MIN_HEIGHT

    async def test_hidden_panels_do_not_count_against_available_space(self):
        """A collapsed/hidden panel (e.g. SearchPanel before '/' is pressed)
        occupies zero rows and shouldn't limit another panel's growth."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                from kube_orb.viewer.panels.monitor import MonitorPanel

                search = app.query_one(SearchPanel)
                monitor = app.query_one(MonitorPanel)
                assert search.display is False  # hidden by default

                main_panel = app.query_one("#main-stream")
                before_main = main_panel.size.height

                app.resize_panel(monitor, 8)
                await pilot.pause()

                # The full 8 rows should have come out of MainStreamPanel,
                # not been capped by a phantom SearchPanel allocation.
                assert main_panel.size.height == before_main - 8
