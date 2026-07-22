"""
Tests for monitor-hit context (Enter on a clicked monitor row): shows lines
of surrounding same-pod buffer context around the hit, like `grep -C`, in
MonitorContextModal — since the monitor panel itself only ever shows the
single matching line, which is often not enough on its own. The context
window starts small and grows/shrinks live via +/-.
"""
from datetime import datetime
from unittest.mock import patch

from kube_orb.models import LogLine, LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.monitor import MonitorPanel
from kube_orb.viewer.widgets import MonitorContextModal


class TestMonitorContextModal:
    async def test_enter_on_focused_row_opens_context_modal(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                for i in range(10):
                    app._ingest(LogLine(pod_name="pod-1", content=f"line {i}", received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-1", content="error boom", received_at=datetime.now()))
                for i in range(10, 20):
                    app._ingest(LogLine(pod_name="pod-1", content=f"line {i}", received_at=datetime.now()))
                await pilot.pause()

                mp = app.query_one(MonitorPanel)
                row = mp.query("#monitor-list > _MonitorRow").first()
                assert row.line.content == "error boom"

                await pilot.click(row)
                await pilot.pause()
                assert row.has_focus

                await pilot.press("enter")
                await pilot.pause()

                assert isinstance(app.screen, MonitorContextModal)

    async def test_context_body_includes_surrounding_lines_and_marks_the_hit(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                for i in range(10):
                    app._ingest(LogLine(pod_name="pod-1", content=f"line {i}", received_at=datetime.now()))
                target = LogLine(pod_name="pod-1", content="error boom", received_at=datetime.now())
                app._ingest(target)
                for i in range(10, 20):
                    app._ingest(LogLine(pod_name="pod-1", content=f"line {i}", received_at=datetime.now()))
                await pilot.pause()

                app.show_monitor_context(target)
                await pilot.pause()

                modal = app.screen
                assert isinstance(modal, MonitorContextModal)
                plain = modal._build_body().plain
                # 3 lines of context on each side, plus the hit itself
                assert "line 7" in plain
                assert "line 8" in plain
                assert "line 9" in plain
                assert "error boom" in plain
                assert "line 10" in plain
                assert "line 11" in plain
                assert "line 12" in plain
                # further-away lines shouldn't be pulled in
                assert "line 6" not in plain
                assert "line 13" not in plain

    async def test_context_is_scoped_to_the_same_pod_not_the_interleaved_buffer(self):
        """Regression: context used to be sliced straight from the global,
        multi-pod-interleaved session buffer, so with several pods streaming
        at once the "context" was really just whatever unrelated line another
        pod happened to log around the same moment. It must instead be the
        target pod's own neighboring lines."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-a": "#ffffff", "pod-b": "#00ff00"}

                # Interleave pod-b noise around every pod-a line, mimicking
                # concurrent multi-pod streaming.
                target = LogLine(pod_name="pod-a", content="error boom", received_at=datetime.now())
                app._ingest(LogLine(pod_name="pod-a", content="a-before-3", received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-b", content="unrelated-1", received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-a", content="a-before-2", received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-b", content="unrelated-2", received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-a", content="a-before-1", received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-b", content="unrelated-3", received_at=datetime.now()))
                app._ingest(target)
                app._ingest(LogLine(pod_name="pod-b", content="unrelated-4", received_at=datetime.now()))
                app._ingest(LogLine(pod_name="pod-a", content="a-after-1", received_at=datetime.now()))
                await pilot.pause()

                app.show_monitor_context(target)
                await pilot.pause()

                modal = app.screen
                assert isinstance(modal, MonitorContextModal)
                assert modal._pod_name == "pod-a"
                plain = modal._build_body().plain
                assert "a-before-1" in plain
                assert "a-before-2" in plain
                assert "a-before-3" in plain
                assert "a-after-1" in plain
                assert "unrelated" not in plain

    async def test_plus_grows_and_minus_shrinks_the_context_window(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                for i in range(20):
                    app._ingest(LogLine(pod_name="pod-1", content=f"line {i}", received_at=datetime.now()))
                target = LogLine(pod_name="pod-1", content="error boom", received_at=datetime.now())
                app._ingest(target)
                for i in range(20, 40):
                    app._ingest(LogLine(pod_name="pod-1", content=f"line {i}", received_at=datetime.now()))
                await pilot.pause()

                app.show_monitor_context(target)
                await pilot.pause()

                modal = app.screen
                assert isinstance(modal, MonitorContextModal)
                assert modal._context_n == MonitorContextModal.DEFAULT_CONTEXT
                assert "line 16" not in modal._build_body().plain

                await pilot.press("+")
                await pilot.pause()
                assert modal._context_n == MonitorContextModal.DEFAULT_CONTEXT + MonitorContextModal.STEP
                plain = modal._build_body().plain
                assert "line 16" in plain
                assert "line 20" in plain

                # Two shrinks from 8 (3 + one STEP of 5): 8-5=3, then
                # max(0, 3-5) clamps at 0 rather than going negative.
                await pilot.press("-")
                await pilot.press("-")
                await pilot.pause()
                assert modal._context_n == 0

    async def test_evicted_line_shows_a_warning_instead_of_a_modal(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}

                stale = LogLine(pod_name="pod-1", content="long gone", received_at=datetime.now())
                app.show_monitor_context(stale)
                await pilot.pause()

                assert not isinstance(app.screen, MonitorContextModal)

    async def test_double_click_still_jumps_instead_of_opening_context(self):
        """Regression guard: adding click-to-focus for Enter/context must not
        interfere with the existing double-click-to-jump behavior."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content="error boom", received_at=datetime.now()))
                await pilot.pause()

                mp = app.query_one(MonitorPanel)
                row = mp.query("#monitor-list > _MonitorRow").first()

                await pilot.click(row)
                await pilot.click(row)
                await pilot.pause()

                assert app._paused is True
                assert not isinstance(app.screen, MonitorContextModal)
