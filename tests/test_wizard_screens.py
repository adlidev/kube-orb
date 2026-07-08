"""
Regression tests for the wizard's saved-config restore flow.

_apply_saved_config() restores a saved SessionConfig's deployment checkboxes
via a pending-selection handoff to whichever checkbox mount actually runs
(sync or async) — see _refresh_deployments()/_mount_dep_checks() in
wizard/screens.py. These tests protect two races that used to silently wipe
the restored checkbox state:
  1. the saved config's namespace differs from the currently-selected one
  2. the initial (on-mount) checkbox mount is still in flight
"""
import asyncio

from unittest.mock import patch

from textual.widgets import Checkbox, Select

from kube_orb.models import SessionConfig
from kube_orb.wizard.app import WizardApp
from kube_orb.wizard import screens as screens_mod


class _FakeDeployment:
    def __init__(self, name: str, count: int = 2) -> None:
        self.name = name
        self.pod_count = count


DEPLOYMENTS = [_FakeDeployment("api-gateway"), _FakeDeployment("auth-service"), _FakeDeployment("worker")]


def _checkbox_states(screen) -> dict[str, bool]:
    return {cb.id: cb.value for cb in screen.query("#dep-checks Checkbox")}


class TestApplySavedConfigDeploymentRestore:
    async def test_restores_selection_across_namespaces(self, monkeypatch, tmp_path):
        monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
        monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
        monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")

        saved_cfg = SessionConfig(
            namespace="production",
            deployments=["api-gateway", "worker"],  # auth-service deliberately excluded
            name="myconfig",
        )

        with patch("kube_orb.kubectl.get_namespaces", return_value=["default", "production"]), \
             patch("kube_orb.kubectl.get_deployments", return_value=DEPLOYMENTS), \
             patch("kube_orb.config.load_session_config", return_value=saved_cfg), \
             patch("kube_orb.config.list_all_saved_configs", return_value=[("production", "myconfig")]):

            app = WizardApp(initial_namespace="default")
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.pause()

                app.screen._apply_saved_config("production", "myconfig")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

                states = _checkbox_states(app.screen)
                assert states == {
                    "dep-api-gateway": True,
                    "dep-auth-service": False,
                    "dep-worker": True,
                }

    async def test_survives_slow_initial_checkbox_mount(self, monkeypatch, tmp_path):
        monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
        monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
        monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")

        saved_cfg = SessionConfig(
            namespace="default",
            deployments=["api-gateway", "worker"],
            name="myconfig",
        )

        orig_mount = screens_mod.SinglePageWizard._mount_dep_checks

        async def slow_mount(self, names, counts, pending):
            await asyncio.sleep(0.2)
            await orig_mount(self, names, counts, pending)

        monkeypatch.setattr(screens_mod.SinglePageWizard, "_mount_dep_checks", slow_mount)

        with patch("kube_orb.kubectl.get_namespaces", return_value=["default"]), \
             patch("kube_orb.kubectl.get_deployments", return_value=DEPLOYMENTS), \
             patch("kube_orb.config.load_session_config", return_value=saved_cfg), \
             patch("kube_orb.config.list_all_saved_configs", return_value=[("default", "myconfig")]):

            app = WizardApp(initial_namespace="default")
            async with app.run_test(size=(120, 50)) as pilot:
                # Apply the saved config immediately, before the on-mount
                # checkbox-mount worker (deliberately slowed above) finishes.
                sel = app.screen.query_one("#cfg-select", Select)
                sel.value = "default::myconfig"
                await pilot.pause()
                await asyncio.sleep(0.4)
                await pilot.pause()

                states = _checkbox_states(app.screen)
                assert states == {
                    "dep-api-gateway": True,
                    "dep-auth-service": False,
                    "dep-worker": True,
                }
