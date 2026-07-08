"""
Regression test: double-clicking a monitor hit stopped jumping to that line.

MonitorPanel used to render hits in a ListView (double-click detected via
on_list_view_selected + a per-index timestamp), but the rewrite to a plain
Vertical of Labels (needed for prepend-at-top ordering and row eviction —
see MonitorPanel.add_line) dropped that entirely, and there was never a
ViewerApp handler wired to MonitorPanel.LineSelected in the first place.
Fixed by giving each rendered hit (_MonitorRow) its own click-timing state
and wiring ViewerApp.on_monitor_panel_line_selected, mirroring the working
SearchPanel implementation.
"""
from datetime import datetime
from unittest.mock import patch

from kube_orb.models import LogLine, LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.monitor import MonitorPanel


class TestMonitorDoubleClickJumpsToLine:
    async def test_double_click_pauses_and_jumps(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                for i in range(5):
                    app._ingest(LogLine(pod_name="pod-1", content=f"error {i}", received_at=datetime.now()))
                    app._ingest(LogLine(pod_name="pod-1", content=f"ordinary {i}", received_at=datetime.now()))
                await pilot.pause()

                mp = app.query_one(MonitorPanel)
                row = mp.query("#monitor-list > _MonitorRow").first()
                assert app._paused is False

                await pilot.click(row)
                await pilot.pause()
                assert app._paused is False, "a single click must not trigger the jump"

                await pilot.click(row)
                await pilot.pause()
                assert app._paused is True

                log = app.query_one("#stream-log")
                visible_text = "\n".join(str(s) for s in log.lines)
                assert row.line.content in visible_text

    async def test_two_slow_clicks_do_not_count_as_a_double_click(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content="error 0", received_at=datetime.now()))
                await pilot.pause()

                mp = app.query_one(MonitorPanel)
                row = mp.query("#monitor-list > _MonitorRow").first()

                row.on_click()
                row._last_click -= 1.0  # simulate the first click having happened 1s ago
                row.on_click()
                await pilot.pause()

                assert app._paused is False
