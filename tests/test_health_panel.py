"""
Regression test: HealthPanel crashed on the second health update for the
same unhealthy pod (e.g. its restart count increments again on a later
poll). update_pod() takes the add_row path the first time a pod is seen,
then the _update_table_row path on subsequent updates — and that path
indexed DataTable.columns (a dict[ColumnKey, Column]) with a plain int,
raising KeyError. Fixed by iterating table.ordered_columns (the list form)
instead.
"""
from textual.app import App

from kube_orb.models import HealthConfig, PodStatus
from kube_orb.viewer.panels.health import HealthPanel


class _Harness(App):
    def compose(self):
        yield HealthPanel(config=HealthConfig(), id="health-panel")


class TestHealthPanelRepeatedUpdate:
    async def test_second_update_for_same_pod_does_not_crash(self):
        app = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            hp = app.query_one(HealthPanel)

            first = PodStatus(name="worker-x", deployment="worker", phase="Running",
                              restart_count=1, ready=True, age_seconds=100)
            hp.update_pod(first, restart_delta=1)
            await pilot.pause()

            # A later poll sees another restart on the same pod — this used
            # to raise KeyError(0) inside _update_table_row.
            second = PodStatus(name="worker-x", deployment="worker", phase="Running",
                               restart_count=2, ready=True, age_seconds=160)
            hp.update_pod(second, restart_delta=2)
            await pilot.pause()

            table = hp.query_one("#health-table")
            row = table.get_row("worker-x")
            assert row[0] == "worker-x"
            assert row[2] == "2 (+2)"
