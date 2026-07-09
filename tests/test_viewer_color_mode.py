"""
Tests for color mode (T keybind) applying to Search and Monitor panels, not
just the main stream. Also covers the JSON-detail footer-hotkey visibility
(check_action) added alongside this.
"""
from datetime import datetime
from unittest.mock import patch

from kube_orb.models import LogLine, LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.monitor import MonitorPanel
from kube_orb.viewer.panels.search import SearchPanel


class TestColorModeAppliesToAllPanels:
    async def test_toggle_color_updates_search_panel_mode(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                search = app.query_one(SearchPanel)
                assert search._color_full_line is False

                await pilot.press("t")
                await pilot.pause()
                assert search._color_full_line is True

    async def test_toggle_color_updates_monitor_panel_mode(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                monitor = app.query_one(MonitorPanel)
                assert monitor._color_full_line is False

                await pilot.press("t")
                await pilot.pause()
                assert monitor._color_full_line is True

    async def test_search_panel_rebuild_called_on_toggle(self):
        """action_toggle_color must re-render already-shown search results
        (not just flip the flag for future searches)."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content="boom happened", received_at=datetime.now()))
                await pilot.pause()

                search = app.query_one(SearchPanel)
                calls = []
                orig_search = search.search
                def traced_search(*args, **kwargs):
                    calls.append(args)
                    return orig_search(*args, **kwargs)
                search.search = traced_search
                search.query_one("#search-input").value = "boom"

                await pilot.press("t")
                await pilot.pause()

                assert calls, "toggling color mode should re-run the active search"
                assert calls[0][1] == "boom"

    async def test_monitor_panel_rebuild_called_on_toggle(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                monitor = app.query_one(MonitorPanel)
                calls = []
                orig_rebuild = monitor.rebuild
                def traced_rebuild(*args, **kwargs):
                    calls.append(args)
                    return orig_rebuild(*args, **kwargs)
                monitor.rebuild = traced_rebuild

                await pilot.press("t")
                await pilot.pause()

                assert calls, "toggling color mode should rebuild monitor hits"


class TestMonitorBuildTextColorMode:
    """Direct unit test of the rendering function itself — more reliable
    than inspecting styles through the full Pilot render pipeline."""

    def test_name_only_mode_leaves_message_unstyled(self):
        from kube_orb.viewer.panels.monitor import _build_text
        line = LogLine(pod_name="pod-1", content="hello", received_at=datetime.now())
        text = _build_text(line, "#ffffff", [], full_line=False)
        assert not any(
            s.style == "#ffffff" and text.plain[s.start:s.end] == "hello"
            for s in text.spans
        )

    def test_full_line_mode_colors_the_message_too(self):
        from kube_orb.viewer.panels.monitor import _build_text
        line = LogLine(pod_name="pod-1", content="hello", received_at=datetime.now())
        text = _build_text(line, "#ffffff", [], full_line=True)
        assert any(
            s.style == "#ffffff" and text.plain[s.start:s.end] == "hello"
            for s in text.spans
        )


class TestJsonDetailHotkeyVisibility:
    async def test_hidden_when_nothing_selected(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                assert "enter" not in app.screen.active_bindings

    async def test_visible_after_selecting_a_json_line(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content='{"level": "INFO", "msg": "hi"}',
                                    received_at=datetime.now()))
                await pilot.pause()

                await pilot.click("#stream-log", offset=(5, 0))
                await pilot.pause()
                assert "enter" in app.screen.active_bindings

    async def test_hidden_again_after_selecting_a_non_json_line(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content='{"level": "INFO", "msg": "hi"}',
                                    received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-1", content="plain text line",
                                    received_at=datetime.now()))
                await pilot.pause()

                await pilot.click("#stream-log", offset=(5, 0))
                await pilot.pause()
                assert "enter" in app.screen.active_bindings

                await pilot.click("#stream-log", offset=(5, 1))
                await pilot.pause()
                assert "enter" not in app.screen.active_bindings
