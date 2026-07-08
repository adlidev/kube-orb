"""
Implements the scenarios documented in tests/features/wizard.feature (see
that file for why these are plain async tests rather than pytest-bdd steps).

Each test name matches its Gherkin scenario name 1:1 for traceability.
"""
from unittest.mock import patch

from textual.widgets import Checkbox, Input

from kube_orb.config import save_saved_strings
from kube_orb.models import SavedStrings
from kube_orb.wizard.app import WizardApp


class _FakeDeployment:
    def __init__(self, name: str, count: int = 1) -> None:
        self.name = name
        self.pod_count = count


def _isolate_config(monkeypatch, tmp_path):
    monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
    monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
    monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")


def _filter_checkbox(screen, label: str) -> Checkbox:
    return next(
        cb for cb in screen.query("#filter-checks Checkbox") if cb.label.plain == label
    )


async def _launch_and_capture(app, pilot):
    """Drive the wizard's Launch action (where filters are actually computed
    and merged — see the `collect()` closure in _launch()) and capture the
    SessionConfig it dismisses with."""
    captured = {}
    orig_dismiss = app.screen.dismiss

    def fake_dismiss(result=None):
        captured["result"] = result
        return orig_dismiss(result)

    app.screen.dismiss = fake_dismiss
    app.screen._launch()
    await pilot.pause()
    return captured["result"]


class TestWizardStringConfiguration:
    """Background: the saved strings file contains filters ["DEBUG", "health"]."""

    async def test_user_loads_saved_filters_and_adds_a_new_one(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        save_saved_strings(SavedStrings(filters=["DEBUG", "health"]))

        with patch("kube_orb.kubectl.get_namespaces", return_value=["default"]), \
             patch("kube_orb.kubectl.get_deployments", return_value=[_FakeDeployment("worker")]):
            app = WizardApp(initial_namespace="default")
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen

                # I check "DEBUG" from the saved list
                _filter_checkbox(screen, "DEBUG").value = True
                # (and "health" stays unchecked)

                # I enter "timeout" in the new strings input
                screen.query_one("#filter-input", Input).value = "timeout"

                # I click Next
                cfg = await _launch_and_capture(app, pilot)

                assert cfg.filters == ["DEBUG", "timeout"]

    async def test_user_adds_a_new_regex_filter(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        save_saved_strings(SavedStrings(filters=["DEBUG", "health"]))

        with patch("kube_orb.kubectl.get_namespaces", return_value=["default"]), \
             patch("kube_orb.kubectl.get_deployments", return_value=[_FakeDeployment("worker")]):
            app = WizardApp(initial_namespace="default")
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen

                # (DEBUG / health both left unchecked — only the new regex is active)
                for cb in screen.query("#filter-checks Checkbox"):
                    cb.value = False

                screen.query_one("#filter-input", Input).value = "/5[0-9]{2}/"

                cfg = await _launch_and_capture(app, pilot)

                assert cfg.filters == ["/5[0-9]{2}/"]

    async def test_user_opts_to_save_new_strings_to_the_global_list(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        save_saved_strings(SavedStrings(filters=["DEBUG", "health"]))

        with patch("kube_orb.kubectl.get_namespaces", return_value=["default"]), \
             patch("kube_orb.kubectl.get_deployments", return_value=[_FakeDeployment("worker")]):
            app = WizardApp(initial_namespace="default")
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen

                screen.query_one("#filter-input", Input).value = "ERROR"
                screen.query_one("#filter-save", Checkbox).value = True

                await _launch_and_capture(app, pilot)

                from kube_orb.config import load_saved_strings
                assert "ERROR" in load_saved_strings().filters

    async def test_user_opts_not_to_save_new_strings(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        save_saved_strings(SavedStrings(filters=["DEBUG", "health"]))

        with patch("kube_orb.kubectl.get_namespaces", return_value=["default"]), \
             patch("kube_orb.kubectl.get_deployments", return_value=[_FakeDeployment("worker")]):
            app = WizardApp(initial_namespace="default")
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen

                for cb in screen.query("#filter-checks Checkbox"):
                    cb.value = False
                screen.query_one("#filter-input", Input).value = "ERROR"
                screen.query_one("#filter-save", Checkbox).value = False

                cfg = await _launch_and_capture(app, pilot)

                from kube_orb.config import load_saved_strings
                assert "ERROR" not in load_saved_strings().filters
                assert cfg.filters == ["ERROR"]

    async def test_user_clears_all_saved_string_selections(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        save_saved_strings(SavedStrings(filters=["DEBUG", "health"]))

        with patch("kube_orb.kubectl.get_namespaces", return_value=["default"]), \
             patch("kube_orb.kubectl.get_deployments", return_value=[_FakeDeployment("worker")]):
            app = WizardApp(initial_namespace="default")
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen

                # No "Clear all" affordance exists for the Patterns tab in the
                # current wizard (only deployments have one) — uncheck
                # everything directly to express the same intent.
                for cb in screen.query("#filter-checks Checkbox"):
                    cb.value = False

                cfg = await _launch_and_capture(app, pilot)

                assert cfg.filters == []
