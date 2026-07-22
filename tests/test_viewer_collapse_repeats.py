"""
Tests for collapse-repeats (the C toggle): consecutive identical lines from
the same pod fold into a single "last line repeated N times" marker,
journalctl-style, instead of flooding the main stream — most useful for a
crash-looping pod or a misconfigured service spamming the same error.
"""
from datetime import datetime
from unittest.mock import patch

from kube_orb.models import LogLine, LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.panels.main_stream import MainStreamPanel


def _rendered_text(log) -> str:
    """Every rendered row's plain text joined — robust to wrapping."""
    return "".join(row.text for row in log.lines)


def _line(pod: str, content: str) -> LogLine:
    return LogLine(pod_name=pod, content=content, received_at=datetime.now())


class TestCollapseRepeatsToggle:
    async def test_off_by_default_shows_every_line(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, collapse_repeats=False)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                for _ in range(4):
                    app._ingest(_line("pod-1", "boom"))
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                assert text.count("boom") == 4
                assert "repeated" not in text

    async def test_on_collapses_a_run_once_it_breaks(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, collapse_repeats=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "boom"))
                await pilot.pause()
                text = _rendered_text(app.query_one("#stream-log"))
                # The run hasn't broken yet -- only the first occurrence is
                # written, nothing is flushed until a different line arrives.
                assert text.count("boom") == 1
                assert "repeated" not in text

                app._ingest(_line("pod-1", "all clear"))
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                assert text.count("boom") == 1
                assert "repeated 3 times" in text
                assert "all clear" in text

    async def test_different_pod_breaks_the_run_even_with_identical_content(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, collapse_repeats=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-a": "#ffffff", "pod-b": "#00ff00"}
                app._ingest(_line("pod-a", "boom"))
                app._ingest(_line("pod-b", "boom"))
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                assert text.count("boom") == 2
                assert "repeated" not in text

    async def test_a_single_occurrence_never_gets_a_marker(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, collapse_repeats=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(_line("pod-1", "one-off"))
                app._ingest(_line("pod-1", "different"))
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                assert "repeated" not in text

    async def test_checkpoint_flushes_a_run_that_never_breaks(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, collapse_repeats=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                panel = app.query_one(MainStreamPanel)
                panel.REPEAT_CHECKPOINT = 5  # keep the test fast
                app._color_map = {"pod-1": "#ffffff"}

                app._ingest(_line("pod-1", "boom"))
                for _ in range(5):
                    app._ingest(_line("pod-1", "boom"))
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                assert "repeated 5 times so far" in text
                assert "still repeating" in text

                # The run continues past the checkpoint, then finally breaks --
                # only the count SINCE the checkpoint should appear now.
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "done"))
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                assert "repeated 2 times" in text
                assert "repeated 2 times so far" not in text

    async def test_toggling_off_mid_run_flushes_and_stops_collapsing(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, collapse_repeats=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "boom"))
                await pilot.pause()

                app.action_toggle_collapse()  # C hotkey -- also rerenders
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                # Off now, and the rerender replays the buffer with
                # collapsing disabled -- every occurrence should show.
                assert text.count("boom") == 3
                assert "repeated" not in text

                app._ingest(_line("pod-1", "boom"))
                await pilot.pause()
                text = _rendered_text(app.query_one("#stream-log"))
                assert text.count("boom") == 4

    async def test_rerender_after_filter_edit_still_collapses_correctly(self):
        """_rerender_main_stream() (triggered by F/H/M edits, T/W/J/C
        toggles) replays the whole buffer through add_line() again -- the
        panel's collapse state must reset cleanly each time, not carry over
        stale counts from the previous render."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, collapse_repeats=True)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "boom"))
                app._ingest(_line("pod-1", "all clear"))
                await pilot.pause()

                app._rerender_main_stream()
                await pilot.pause()

                text = _rendered_text(app.query_one("#stream-log"))
                assert text.count("boom") == 1
                assert "repeated 1 time" in text  # singular, not "1 times"
                assert "all clear" in text
