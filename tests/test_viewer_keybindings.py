"""
Regression test: footer hotkeys used to disappear after using F/H/M or '/'.

Textual's Footer hides any app-level hotkey the *focused* widget's
check_consume_key claims (Input claims every printable character). The old
code left an Input focused after the F/H/M modal or the search panel closed,
so most letter hotkeys silently vanished from the footer afterward. Both
close paths now explicitly refocus the main log display.
"""
from unittest.mock import patch

from kube_orb.models import LogMode, SessionConfig
from kube_orb.viewer.app import ViewerApp
from kube_orb.viewer.widgets import StringEditModal


class TestFooterKeybindingsSurviveModalAndSearchClose:
    async def test_bindings_unchanged_after_edit_modal_closes(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP, filters=["foo"])
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                before = sorted(app.screen.active_bindings.keys())

                await pilot.press("f")
                await pilot.pause()
                assert isinstance(app.screen, StringEditModal)

                await pilot.press("escape")
                await pilot.pause()

                after = sorted(app.screen.active_bindings.keys())
                assert after == before
                assert app.focused is not None
                assert app.focused.id == "stream-log"

    async def test_bindings_unchanged_after_search_closes(self):
        cfg = SessionConfig(namespace="ns", deployments=[], mode=LogMode.DUMP)
        with patch("kube_orb.kubectl.get_deployments", return_value=[]):
            app = ViewerApp(cfg)
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                before = sorted(app.screen.active_bindings.keys())

                await pilot.press("slash")
                await pilot.pause()
                assert app.query_one("#search-input").has_focus

                await pilot.press("escape")
                await pilot.pause()

                after = sorted(app.screen.active_bindings.keys())
                assert after == before
                assert app.focused is not None
                assert app.focused.id == "stream-log"
