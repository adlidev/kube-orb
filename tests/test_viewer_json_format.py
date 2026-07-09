"""
Tests for JSON log formatting in the viewer: the J toggle, readable
reformatting in the main stream, and the click-to-select + Enter detail
modal for a detected JSON line.
"""
from datetime import datetime
from unittest.mock import patch

from kube_orb.models import LogLine, LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.main_stream import MainStreamPanel
from kube_orb.viewer.widgets import JsonDetailModal

JSON_LINE = '{"timestamp": "2026-07-08T12:34:56+00:00", "level": "ERROR", "msg": "request failed", "status": 500}'
PLAIN_LINE = "plain text line, not json"


def _rendered_text(log) -> str:
    """Every rendered row's plain text joined — robust to the raw JSON line
    wrapping across multiple rows at typical test terminal widths."""
    return "".join(row.text for row in log.lines)


class TestJsonFormatToggle:
    async def test_json_format_off_shows_raw_text(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=False)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=JSON_LINE, received_at=datetime.now()))
                await pilot.pause()

                log = app.query_one("#stream-log")
                assert JSON_LINE in _rendered_text(log)

    async def test_json_format_on_shows_readable_line(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=JSON_LINE, received_at=datetime.now()))
                await pilot.pause()

                log = app.query_one("#stream-log")
                rendered = _rendered_text(log)
                assert "12:34:56" in rendered
                assert "ERROR" in rendered
                assert "request failed" in rendered
                assert "status=500" in rendered
                assert JSON_LINE not in rendered  # raw form shouldn't leak through

    async def test_j_toggles_and_rerenders_existing_buffer(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=False)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=JSON_LINE, received_at=datetime.now()))
                await pilot.pause()

                log = app.query_one("#stream-log")
                assert JSON_LINE in _rendered_text(log)

                await pilot.press("j")
                await pilot.pause()
                assert app._config.json_format is True
                assert "ERROR" in _rendered_text(log)
                assert JSON_LINE not in _rendered_text(log)

                await pilot.press("j")
                await pilot.pause()
                assert app._config.json_format is False
                assert JSON_LINE in _rendered_text(log)

    async def test_non_json_lines_unaffected_by_toggle(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=PLAIN_LINE, received_at=datetime.now()))
                await pilot.pause()

                log = app.query_one("#stream-log")
                assert PLAIN_LINE in _rendered_text(log)


class TestJsonDetailModal:
    async def test_click_json_line_then_enter_opens_detail(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=JSON_LINE, received_at=datetime.now()))
                await pilot.pause()

                await pilot.click("#stream-log", offset=(5, 0))
                await pilot.pause()
                log = app.query_one("#stream-log")
                assert log.selected_line_idx == 0

                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, JsonDetailModal)
                assert "ERROR" in app.screen._pretty
                assert "request failed" in app.screen._pretty

                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, JsonDetailModal)

    async def test_click_non_json_line_then_enter_does_nothing(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=PLAIN_LINE, received_at=datetime.now()))
                await pilot.pause()

                await pilot.click("#stream-log", offset=(5, 0))
                await pilot.pause()
                log = app.query_one("#stream-log")
                assert log.selected_line_idx is None

                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, JsonDetailModal)

    async def test_detail_works_even_when_display_format_is_off(self):
        """Detection/detail-lookup is independent of the raw/formatted toggle."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=False)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=JSON_LINE, received_at=datetime.now()))
                await pilot.pause()

                await pilot.click("#stream-log", offset=(5, 0))
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, JsonDetailModal)

    async def test_get_parsed_json_resets_on_clear(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, json_format=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(LogLine(pod_name="pod-1", content=JSON_LINE, received_at=datetime.now()))
                await pilot.pause()

                panel = app.query_one(MainStreamPanel)
                assert panel.get_parsed_json(0) is not None

                panel.clear()
                assert panel.get_parsed_json(0) is None
