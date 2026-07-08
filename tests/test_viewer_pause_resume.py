"""
Regression test: resuming from pause used to kill every live per-pod
streaming worker.

set_paused(False) flushes buffered lines via a worker started with
exclusive=True. Textual's run_worker() defaults to group="default" when no
group is given, and exclusive=True cancels every other worker in that same
group — which is also where the per-pod `stream_pod()` workers live. Without
an explicit group="flush-pending" on the flush worker, unpausing silently
cancelled the kubectl log-streaming tasks: the UI looked resumed (indicator
cleared, backlog flushed) but no further log lines would ever arrive.
"""
from datetime import datetime
from unittest.mock import patch

from kube_orb.models import Deployment, LogLine, LogMode, Pod, SessionConfig
from kube_orb.viewer.app import ViewerApp

DEPLOYMENT = Deployment(name="worker", namespace="ns", pod_count=1, selector={"app": "worker"})
POD = Pod(name="worker-abc123", namespace="ns", deployment="worker", phase="Running",
          restart_count=0, ready=True)


async def _never_ending_stream(*args, **kwargs):
    """Simulates `kubectl logs -f`: never returns until cancelled."""
    import asyncio
    if False:
        yield  # pragma: no cover - makes this an async generator
    await asyncio.Event().wait()


class TestPauseResumeDoesNotCancelStreamingWorkers:
    async def test_stream_worker_survives_pause_resume_cycle(self):
        cfg = SessionConfig(namespace="ns", deployments=["worker"], mode=LogMode.STREAM)

        with patch("kube_orb.kubectl.get_deployments", return_value=[DEPLOYMENT]), \
             patch("kube_orb.kubectl.get_pods_for_deployments", return_value=[POD]), \
             patch("kube_orb.kubectl.stream_logs", _never_ending_stream):

            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                await pilot.pause()

                stream_worker = next(
                    w for w in app.workers if w.name == f"stream-{POD.name}"
                )
                assert stream_worker.is_running

                app.set_paused(True)
                app._ingest(LogLine(pod_name=POD.name, content="buffered while paused",
                                     received_at=datetime.now()))
                assert app._pending_lines  # something is actually buffered

                app.set_paused(False)
                await pilot.pause()
                await pilot.pause()

                assert stream_worker.is_running, (
                    "resuming from pause cancelled the live kubectl log-streaming worker"
                )


class TestScrollbarDragPauses:
    """Dragging the scrollbar thumb posts a ScrollTo message (not the
    ScrollUp that track-clicks/wheel produce). Without _LogDisplay._on_scroll_to
    pausing, auto_scroll stayed on and each incoming line snapped the view
    back to the bottom, making the thumb impossible to drag in a live stream.
    """

    async def test_dragging_thumb_up_pauses_and_holds_position(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.STREAM)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app._color_map = {"pod-1": "#ffffff"}
                for i in range(5000):
                    app._ingest(LogLine(pod_name="pod-1", content=f"line {i}",
                                        received_at=datetime.now()))
                await pilot.pause()

                log = app.query_one("#stream-log")
                vsb = log.vertical_scrollbar
                assert app._paused is False

                # Grab the thumb (at the bottom) and drag it up.
                target_y = vsb.region.height - 2
                await pilot.mouse_down(vsb, offset=(0, target_y))
                await pilot.mouse_up(vsb, offset=(0, target_y - 15))
                await pilot.pause()

                assert app._paused is True
                assert log.auto_scroll is False
                held = log.scroll_y

                # New lines while paused must not snap the view back down.
                for i in range(5000, 5050):
                    app._ingest(LogLine(pod_name="pod-1", content=f"new {i}",
                                        received_at=datetime.now()))
                await pilot.pause()
                assert log.scroll_y == held
                assert len(app._pending_lines) == 50
