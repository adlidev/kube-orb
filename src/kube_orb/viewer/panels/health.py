"""
HealthPanel — pod health alerts.

Hidden when all pods are healthy.
Appears when any watched pod is not Running or has new restarts.
Rows persist until the user double-clicks to dismiss.
R = delete pod (with confirmation), Shift+R = rollout restart deployment.
Stream mode only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Label, Static

from ...models import HealthConfig, PodStatus


@dataclass
class _HealthRow:
    status: PodStatus
    restart_delta: int
    dismissed: bool = False


class HealthPanel(Vertical):
    """
    Collapsible health panel.
    Hidden when no unhealthy rows exist.
    """

    BINDINGS = [
        Binding("r",       "restart_pod",        "Restart pod",   show=True),
        Binding("shift+r", "rollout_restart",     "Rollout restart", show=True),
        Binding("c",       "toggle_collapse",     "Collapse",      show=False),
    ]

    def __init__(self, config: HealthConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config
        self._rows: dict[str, _HealthRow] = {}   # pod_name → row
        self._collapsed = False
        self.display = False   # hidden until first unhealthy pod

    def compose(self) -> ComposeResult:
        yield _HealthHeader(id="health-header")
        yield DataTable(id="health-table", show_cursor=True, zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Pod", "Status", "Restarts (Δ+total)", "Age")

    def update_pod(self, status: PodStatus, restart_delta: int) -> None:
        """Called by the health poller with fresh status for an unhealthy pod."""
        table = self.query_one(DataTable)

        row = self._rows.get(status.name)
        if row is None:
            # New unhealthy pod — add a row
            row = _HealthRow(status=status, restart_delta=restart_delta)
            self._rows[status.name] = row
            table.add_row(
                *self._format_row(row),
                key=status.name,
            )
        else:
            # Update existing row
            row.status = status
            row.restart_delta = restart_delta
            self._update_table_row(table, row)

        self._show_panel()

    def _format_row(self, row: _HealthRow) -> tuple[str, str, str, str]:
        s = row.status
        age = _fmt_age(s.age_seconds)
        restarts = f"{row.restart_delta} (+{s.restart_count})"
        status_style = s.phase if s.is_healthy else f"[red]{s.phase}[/red]"
        return s.name, status_style, restarts, age

    def _update_table_row(self, table: DataTable, row: _HealthRow) -> None:
        fmt = self._format_row(row)
        for col_idx, value in enumerate(fmt):
            table.update_cell(row.status.name, table.columns[col_idx].key, value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Single click — just focus, no action
        pass

    def on_data_table_cell_selected(self, event) -> None:
        pass

    def _dismiss_row(self, pod_name: str) -> None:
        table = self.query_one(DataTable)
        try:
            table.remove_row(pod_name)
        except Exception:
            pass
        self._rows.pop(pod_name, None)
        if not self._rows:
            self.display = False

    # Double-click to dismiss — Textual fires on_data_table_row_highlighted
    # on first click and on_data_table_row_selected on second.
    # We track click timestamps per row to detect double-click.
    _last_click: dict[str, float] = {}

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:  # type: ignore[override]
        import time
        key = str(event.row_key.value)
        now = time.monotonic()
        last = self._last_click.get(key, 0.0)
        if now - last < 0.5:
            self._dismiss_row(key)
        self._last_click[key] = now

    def action_restart_pod(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row < 0:
            return
        row_key = table.get_row_at(table.cursor_row)
        pod_name = str(table.get_row_index(table.cursor_row))
        # Get pod name from first cell
        pod_name = str(table.get_cell_at((table.cursor_row, 0)))
        self._confirm_restart(pod_name, rollout=False)

    def action_rollout_restart(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row < 0:
            return
        pod_name = str(table.get_cell_at((table.cursor_row, 0)))
        row = self._rows.get(pod_name)
        if row:
            self._confirm_restart(pod_name, rollout=True,
                                  deployment=row.status.deployment)

    def _confirm_restart(self, pod_name: str, rollout: bool,
                         deployment: str | None = None) -> None:
        from ..widgets import ConfirmDialog
        if rollout:
            msg = f"Rollout restart deployment/{deployment}? [y/N]"
        else:
            msg = f"Delete pod {pod_name} (will be recreated)? [y/N]"

        def _on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            from ... import kubectl as k
            if rollout and deployment:
                ok = k.rollout_restart(deployment, self.app._config.namespace)  # type: ignore
                action = f"rollout restart deployment/{deployment}"
            else:
                ok = k.delete_pod(pod_name, self.app._config.namespace)  # type: ignore
                action = f"delete pod {pod_name}"

            if ok:
                self.app.notify(f"✓ {action}", severity="information")
            else:
                self.app.notify(f"✗ {action} failed", severity="error")

        self.app.push_screen(ConfirmDialog(message=msg), _on_confirm)

    def _show_panel(self) -> None:
        self.display = True
        self.query_one(_HealthHeader).update_count(len(self._rows))

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.query_one("#health-table").display = not self._collapsed
        self.query_one(_HealthHeader).update_collapsed(self._collapsed)

    def action_toggle_collapse(self) -> None:
        self.toggle_collapsed()


class _HealthHeader(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._count = 0
        self._collapsed = False
        self._refresh()

    def update_count(self, count: int) -> None:
        self._count = count
        self._refresh()

    def update_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._refresh()

    def _refresh(self) -> None:
        arrow = "▶" if self._collapsed else "▼"
        suffix = f" ({self._count} unhealthy)" if self._count else ""
        self.update(f"{arrow} [red]Pod Health{suffix}[/red]")

    def on_click(self) -> None:
        self.parent.toggle_collapsed()  # type: ignore[union-attr]


def _fmt_age(seconds: float) -> str:
    td = timedelta(seconds=int(seconds))
    if td.days:
        return f"{td.days}d{td.seconds // 3600}h"
    h, rem = divmod(td.seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m}m"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"
