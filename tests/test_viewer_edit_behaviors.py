"""
Tests for live-edit behaviors in the viewer:

  - Editing monitors recomputes the hit list from the buffer, so unchecking
    a pattern drops its accumulated hits.
  - Closing any F/H/M edit modal re-engages live-follow (unpauses), and does
    so without double-delivering the lines buffered while paused.
"""
import re
from datetime import datetime
from unittest.mock import patch

from kube_orb.models import LogLine, LogMode, SavedStrings, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.main_stream import _StreamHeader
from kube_orb.viewer.panels.monitor import MonitorPanel


def _ingest_many(app, contents):
    for c in contents:
        app._ingest(LogLine(pod_name="pod-1", content=c, received_at=datetime.now()))


class TestMonitorRefilterOnEdit:
    async def test_unchecking_a_monitor_drops_its_hits(self):
        cfg = SessionConfig(
            namespace="ns", deployments=[], mode=LogMode.STREAM,
            monitors=["error", "timeout"],
        )
        saved = SavedStrings(monitors=["error", "timeout"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]), \
             patch("kube_orb.config.load_saved_strings", return_value=saved):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                _ingest_many(app, [f"error {i}" for i in range(15)])
                _ingest_many(app, [f"timeout {i}" for i in range(15)])
                _ingest_many(app, [f"ordinary {i}" for i in range(15)])
                await pilot.pause()

                mp = app.query_one(MonitorPanel)
                assert len(mp._lines) == 30

                # Simulate closing the monitors modal with only "error" checked.
                app._on_monitors_edited((["error"], False))
                await pilot.pause()

                assert len(mp._lines) == 15
                assert all("error" in line.content for line in mp._lines)

    async def test_rechecking_backfills_hits_from_buffer(self):
        cfg = SessionConfig(
            namespace="ns", deployments=[], mode=LogMode.STREAM, monitors=["error"],
        )
        saved = SavedStrings(monitors=["error", "timeout"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]), \
             patch("kube_orb.config.load_saved_strings", return_value=saved):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                _ingest_many(app, [f"error {i}" for i in range(10)])
                _ingest_many(app, [f"timeout {i}" for i in range(10)])
                await pilot.pause()

                mp = app.query_one(MonitorPanel)
                assert len(mp._lines) == 10  # only errors monitored initially

                # Now enable "timeout" too — historical timeout lines in the
                # buffer should be back-filled.
                app._on_monitors_edited((["error", "timeout"], False))
                await pilot.pause()

                assert len(mp._lines) == 20


class TestEditModalResumesStreaming:
    async def test_cancel_resumes_and_does_not_duplicate_lines(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        saved = SavedStrings()
        with patch("kube_orb.kubectl.get_deployments", return_value=[]), \
             patch("kube_orb.config.load_saved_strings", return_value=saved):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                _ingest_many(app, [f"line {i}" for i in range(10)])
                await pilot.pause()

                app.set_paused(True)
                _ingest_many(app, [f"line {i}" for i in range(10, 15)])
                assert len(app._pending_lines) == 5

                app._on_filters_edited(None)  # cancel the modal
                await pilot.pause()

                assert app._paused is False
                assert app._pending_lines == []

                log = app.query_one("#stream-log")
                joined = "\n".join(str(s) for s in log.lines)
                for i in range(15):
                    assert len(re.findall(rf"line {i}\b", joined)) == 1

    async def test_apply_resumes_streaming(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        saved = SavedStrings()
        with patch("kube_orb.kubectl.get_deployments", return_value=[]), \
             patch("kube_orb.config.load_saved_strings", return_value=saved):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                _ingest_many(app, [f"line {i}" for i in range(10)])
                await pilot.pause()
                app.set_paused(True)
                assert app._paused is True

                app._on_highlights_edited((["error"], False))  # apply
                await pilot.pause()

                assert app._paused is False


class TestPausedHeaderFlashes:
    async def test_header_flashes_while_paused_and_stops_on_resume(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                hdr = app.query_one(_StreamHeader)
                assert hdr._blink_timer is None

                app.set_paused(True)
                await pilot.pause()
                assert hdr.has_class("-paused")
                assert hdr._blink_timer is not None

                app.set_paused(False)
                await pilot.pause()
                assert not hdr.has_class("-paused")
                assert not hdr.has_class("-blink-off")
                assert hdr._blink_timer is None
