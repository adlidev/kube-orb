"""
Tests for backfill interleaving. When stream mode is launched with `since`
set, each pod's history streams in concurrently and isn't guaranteed to
arrive in chronological order — ViewerApp holds the initial burst and sorts
it by real log_timestamp before display (see ViewerApp._handle_backfill_line
/ _flush_backfill / _backfill_watchdog_fire), instead of showing one pod's
whole backlog before the next pod's.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from kube_orb.models import LogLine, LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp


def _ts(seconds: int) -> datetime:
    return datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def _line(pod: str, content: str, ts: datetime | None) -> LogLine:
    return LogLine(pod_name=pod, content=content, log_timestamp=ts)


class TestBackfillInterleaving:
    async def test_no_since_means_no_backfill_buffering(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, since=None)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                assert app._backfill_pending is None

                app._ingest(_line("pod-a", "line 1", None))
                await pilot.pause()
                assert [l.content for l in app._buffer] == ["line 1"]

    async def test_lines_held_and_sorted_until_all_pods_catch_up(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, since="1h")
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()

                app._backfill_pending = {"pod-a", "pod-b"}
                app._backfill_cutoff = _ts(100)
                app._backfill_watchdog = app.set_timer(60, app._backfill_watchdog_fire)

                # pod-a's backlog arrives out of order relative to pod-b's.
                app._ingest(_line("pod-a", "a-2", _ts(20)))
                app._ingest(_line("pod-a", "a-1", _ts(10)))
                app._ingest(_line("pod-b", "b-1", _ts(15)))
                await pilot.pause()

                assert app._buffer == []
                assert app._backfill_pending == {"pod-a", "pod-b"}

                # pod-a catches up to live (timestamp past cutoff) -- still
                # held, since pod-b hasn't caught up yet.
                app._ingest(_line("pod-a", "a-live", _ts(150)))
                await pilot.pause()
                assert app._backfill_pending == {"pod-b"}
                assert app._buffer == []

                # pod-b catches up too -- everything flushes now, sorted by
                # real timestamp rather than arrival order.
                app._ingest(_line("pod-b", "b-live", _ts(160)))
                await pilot.pause()

                assert app._backfill_pending is None
                assert [l.content for l in app._buffer] == ["a-1", "b-1", "a-2", "a-live", "b-live"]

    async def test_watchdog_force_flushes_a_stalled_pod(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, since="1h")
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()

                app._backfill_pending = {"pod-a", "pod-quiet"}
                app._backfill_cutoff = _ts(100)
                app._backfill_watchdog = app.set_timer(0.05, app._backfill_watchdog_fire)

                app._ingest(_line("pod-a", "a-1", _ts(10)))
                await pilot.pause()
                assert app._buffer == []

                await asyncio.sleep(0.15)
                await pilot.pause()

                assert app._backfill_pending is None
                assert [l.content for l in app._buffer] == ["a-1"]

    async def test_filters_apply_before_backfill_buffering(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, since="1h",
                            filters=["secret"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()

                app._backfill_pending = {"pod-a"}
                app._backfill_cutoff = _ts(100)
                app._backfill_watchdog = app.set_timer(60, app._backfill_watchdog_fire)

                app._ingest(_line("pod-a", "this has secret in it", _ts(10)))
                app._ingest(_line("pod-a", "past cutoff", _ts(150)))
                await pilot.pause()

                assert [l.content for l in app._buffer] == ["past cutoff"]

    async def test_missing_timestamp_treated_as_caught_up(self):
        """A line whose timestamp failed to parse is conservatively treated
        as 'this pod has caught up' rather than held indefinitely — an
        unparseable line shouldn't be able to stall the backfill forever."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, since="1h")
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()

                app._backfill_pending = {"pod-a"}
                app._backfill_cutoff = _ts(100)
                app._backfill_watchdog = app.set_timer(60, app._backfill_watchdog_fire)

                app._ingest(_line("pod-a", "no-timestamp", None))
                await pilot.pause()

                # pod-a was the only pending pod, so this immediately flushes.
                assert app._backfill_pending is None
                assert [l.content for l in app._buffer] == ["no-timestamp"]

    async def test_buffer_cap_force_flushes_even_with_pods_still_pending(self):
        """A pathologically large backfill burst (e.g. an accidental full-
        history dump) must not grow the hold buffer unboundedly and freeze
        the UI -- BACKFILL_BUFFER_CAP forces a flush once it's reached, even
        though some pods haven't caught up to the cutoff yet."""
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM, since="1h")
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()

                app._backfill_pending = {"pod-a", "pod-b"}
                app._backfill_cutoff = _ts(100)
                app._backfill_watchdog = app.set_timer(60, app._backfill_watchdog_fire)

                # Every line is well before the cutoff, so neither pod is
                # ever marked caught-up -- only the cap can force the flush.
                # pod-b never sends a line at all.
                for i in range(app.BACKFILL_BUFFER_CAP - 1):
                    app._ingest(_line("pod-a", f"a-{i}", _ts(1)))
                await pilot.pause()

                assert app._buffer == []
                assert app._backfill_pending == {"pod-a", "pod-b"}

                app._ingest(_line("pod-a", "a-last", _ts(1)))
                await pilot.pause()

                assert app._backfill_pending is None
                assert len(app._buffer) == app.BACKFILL_BUFFER_CAP
