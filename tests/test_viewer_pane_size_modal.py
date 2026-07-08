"""
Tests for PaneSizeModal (L keybind) — the keyboard/click-driven alternative
to drag-resizing a pane, added because scrollbar-thumb / header-border
dragging is unreliable in some real terminals (works in headless Pilot
simulation, which injects mouse events directly rather than relying on the
terminal's own motion-tracking protocol, so it can't be trusted to reflect
real-world drag reliability).
"""
from unittest.mock import patch

from textual.widgets import Input

from kube_orb.models import LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.monitor import MonitorPanel
from kube_orb.viewer.panels.search import SearchPanel
from kube_orb.viewer.widgets import PaneSizeModal


class TestPaneSizeModal:
    async def test_opens_with_current_percentages_prefilled(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.press("l")
                await pilot.pause()

                assert isinstance(app.screen, PaneSizeModal)
                labels = [label for label, _pct in app.screen._entries]
                # Search is hidden by default in stream mode; Monitor is shown;
                # Health is hidden until an unhealthy pod appears.
                assert labels == ["Monitor"]

    async def test_hidden_and_collapsed_panels_excluded(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                search = app.query_one(SearchPanel)
                search.display = True
                await pilot.pause()

                await pilot.press("l")
                await pilot.pause()
                labels = {label for label, _pct in app.screen._entries}
                assert labels == {"Search", "Monitor"}
                await app.screen.dismiss(None)
                await pilot.pause()

                # Collapse Monitor — it should drop out of the list too.
                monitor = app.query_one(MonitorPanel)
                monitor.toggle_collapsed()
                await pilot.pause()

                await pilot.press("l")
                await pilot.pause()
                labels = {label for label, _pct in app.screen._entries}
                assert labels == {"Search"}

    async def test_apply_resizes_the_pane_trading_with_main_stream(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                monitor = app.query_one(MonitorPanel)
                main_panel = app.query_one("#main-stream")
                before_monitor = monitor.size.height
                before_main = main_panel.size.height

                await pilot.press("l")
                await pilot.pause()
                app.screen.query_one("#pane-size-monitor", Input).value = "30"
                app.screen.action_confirm()
                await pilot.pause()

                assert monitor.size.height > before_monitor
                assert main_panel.size.height < before_main
                # The two changes should offset each other exactly.
                assert (monitor.size.height - before_monitor) == (before_main - main_panel.size.height)

    async def test_rejects_sizes_that_would_violate_main_stream_minimum(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                monitor = app.query_one(MonitorPanel)
                main_panel = app.query_one("#main-stream")
                before = monitor.size.height

                await pilot.press("l")
                await pilot.pause()
                app.screen.query_one("#pane-size-monitor", Input).value = "95"
                app.screen.action_confirm()
                await pilot.pause()

                assert monitor.size.height == before
                assert main_panel.size.height >= app.MAIN_STREAM_MIN_HEIGHT

    async def test_cancel_leaves_sizes_unchanged(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                monitor = app.query_one(MonitorPanel)
                before = monitor.size.height

                await pilot.press("l")
                await pilot.pause()
                app.screen.query_one("#pane-size-monitor", Input).value = "50"
                app.screen.action_cancel()
                await pilot.pause()

                assert monitor.size.height == before

    async def test_invalid_input_rejected_without_closing_modal(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.press("l")
                await pilot.pause()

                app.screen.query_one("#pane-size-monitor", Input).value = "not-a-number"
                app.screen.action_confirm()
                await pilot.pause()
                assert isinstance(app.screen, PaneSizeModal)

                app.screen.query_one("#pane-size-monitor", Input).value = "150"
                app.screen.action_confirm()
                await pilot.pause()
                assert isinstance(app.screen, PaneSizeModal)

    async def test_no_visible_panes_shows_warning_not_empty_modal(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                # Dump mode: no Monitor/Health, and Search starts hidden.
                await pilot.press("l")
                await pilot.pause()
                assert not isinstance(app.screen, PaneSizeModal)
