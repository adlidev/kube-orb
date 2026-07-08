"""
Tests for StringEditModal — the F/H/M checkbox editor.

Shows the union of saved + currently-active strings as checkboxes (checked
state mirrors what's currently active), plus an input for brand-new ones.
"""
from textual.app import App
from textual.widgets import Checkbox, Input

from kube_orb.viewer.widgets import StringEditModal


class _Harness(App):
    """Minimal app so StringEditModal can be pushed/tested in isolation."""


class TestStringEditModal:
    async def test_shows_union_of_saved_and_active_with_correct_check_state(self):
        app = _Harness()
        async with app.run_test() as pilot:
            modal = StringEditModal("filters", current=["foo", "adhoc-only"], saved=["foo", "bar", "baz"])
            app.push_screen(modal)
            await pilot.pause()

            # Saved list first, then any active-only extras appended.
            assert modal._options == ["foo", "bar", "baz", "adhoc-only"]

            states = {
                s: app.screen.query_one(f"#str-{abs(hash(s))}", Checkbox).value
                for s in modal._options
            }
            assert states == {"foo": True, "bar": False, "baz": False, "adhoc-only": True}

    async def test_bracketed_pattern_renders_as_literal_text_not_markup(self):
        """'[debug]' is valid (empty) Textual markup and must not render blank."""
        app = _Harness()
        async with app.run_test() as pilot:
            modal = StringEditModal("filters", current=["[debug]"], saved=["[debug]"])
            app.push_screen(modal)
            await pilot.pause()

            cb = app.screen.query_one(f"#str-{abs(hash('[debug]'))}", Checkbox)
            assert cb.label.plain == "[debug]"

    async def test_apply_merges_checked_and_new_strings(self):
        app = _Harness()
        async with app.run_test() as pilot:
            modal = StringEditModal("filters", current=["foo"], saved=["foo", "bar"])
            app.push_screen(modal)
            await pilot.pause()

            app.screen.query_one(f"#str-{abs(hash('foo'))}", Checkbox).value = False
            app.screen.query_one("#string-edit-input", Input).value = "new-pattern"

            captured = {}
            orig_dismiss = app.screen.dismiss

            def fake_dismiss(result=None):
                captured["result"] = result
                return orig_dismiss(result)

            app.screen.dismiss = fake_dismiss
            app.screen.action_confirm()
            await pilot.pause()

            new_strings, save = captured["result"]
            assert new_strings == ["new-pattern"]
            assert save is True

    async def test_cancel_returns_none(self):
        app = _Harness()
        async with app.run_test() as pilot:
            modal = StringEditModal("filters", current=["foo"], saved=["foo"])
            app.push_screen(modal)
            await pilot.pause()

            captured = {}
            orig_dismiss = app.screen.dismiss

            def fake_dismiss(result=None):
                captured["result"] = result
                return orig_dismiss(result)

            app.screen.dismiss = fake_dismiss
            app.screen.action_cancel()
            await pilot.pause()

            assert captured["result"] is None
