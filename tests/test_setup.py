from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest

from ytsubs.core.models import ChannelCandidate
from ytsubs.core.setup import SetupWizard
from ytsubs.core.store import Store


class _FakeYoutube:
    def __init__(self, started: threading.Event, finish: threading.Event) -> None:
        self.started = started
        self.finish = finish

    def resolve_channel(self, spec: str) -> ChannelCandidate:
        self.started.set()
        self.finish.wait(timeout=2)
        if spec == "@second":
            return ChannelCandidate("UCabcdefghijklmnopqrstu2", "Second", "@second", "https://example.test/2")
        return ChannelCandidate("UCabcdefghijklmnopqrstuv", "Channel", "@channel", "https://example.test")


class _FakeApp:
    def __init__(self, store: Store, yt) -> None:
        self.store = store
        self.yt = yt
        self.download = SimpleNamespace(setup=lambda ui: None)
        self.configuration = SimpleNamespace(import_file=lambda path, ui: None)
        self.addons = SimpleNamespace(addons={}, installed=lambda: [])
        self.refreshed = False

    def refresh_silent(self, *, force: bool = False) -> None:
        self.refreshed = force


class _AmbiguousYoutube:
    def search_channels(self, spec: str, limit: int) -> list[ChannelCandidate]:
        return [
            ChannelCandidate("UCabcdefghijklmnopqrstuv", "One", "@one", "https://example.test/1"),
            ChannelCandidate("UCabcdefghijklmnopqrstu2", "Two", "@two", "https://example.test/2"),
        ]


class _RecordingAddon:
    name = "custom"
    description = "A custom addon."

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def setup(self, ui) -> None:
        self.events.append("addon_setup")


class SetupWizardTests(unittest.TestCase):
    def test_channel_lookup_runs_while_remaining_configuration_continues(self) -> None:
        started = threading.Event()
        finish = threading.Event()
        events: list[str] = []
        answers = iter(["n", "@channel, @second"])

        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            app = _FakeApp(store, _FakeYoutube(started, finish))

            class RecordingWizard(SetupWizard):
                def configure_addons(self) -> None:
                    self.assert_lookup_started()
                    events.append("configure_addons")
                    finish.set()

                def assert_lookup_started(self) -> None:
                    if not started.wait(timeout=2):
                        raise AssertionError("channel lookup did not begin before addon setup")

            wizard = RecordingWizard(
                app,
                input_fn=lambda prompt: next(answers),
                print_fn=lambda message: None,
            )
            self.assertTrue(wizard.run())
            self.assertEqual(events, ["configure_addons"])
            self.assertEqual(len(store.list_subscriptions()), 2)
            self.assertTrue(app.refreshed)
            self.assertEqual(store.get_config("core", "setup_complete"), "on")
            store.conn.close()

    def test_manual_setup_requires_ok_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            app = _FakeApp(store, None)
            wizard = SetupWizard(app, input_fn=lambda prompt: "no", print_fn=lambda message: None)
            self.assertFalse(wizard.run(require_confirmation=True))
            self.assertNotEqual(store.get_config("core", "setup_complete"), "on")
            store.conn.close()

    def test_addon_setup_finishes_before_ambiguous_channel_selection(self) -> None:
        events: list[str] = []
        output: list[str] = []
        answers = iter(["n", "ambiguous channel", "2"])

        def read_input(prompt: str) -> str:
            if prompt.startswith("Choose a number"):
                events.append("channel_choice")
            return next(answers)

        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            app = _FakeApp(store, _AmbiguousYoutube())
            app.addons = SimpleNamespace(
                addons={},
                installed=lambda: [_RecordingAddon(events)],
            )
            app.download = SimpleNamespace(setup=lambda ui: events.append("download_setup"))
            wizard = SetupWizard(app, input_fn=read_input, print_fn=output.append)

            self.assertTrue(wizard.run())
            self.assertLess(events.index("download_setup"), events.index("addon_setup"))
            self.assertLess(events.index("addon_setup"), events.index("channel_choice"))
            self.assertTrue(any("Almost done." in message for message in output))
            self.assertTrue(any("multiple matches" in message for message in output))
            subscriptions = store.list_subscriptions()
            self.assertEqual(len(subscriptions), 1)
            self.assertEqual(subscriptions[0]["handle"], "@two")
            store.conn.close()

    def test_imported_configuration_completes_setup_without_manual_questions(self) -> None:
        output: list[str] = []
        answers = iter(["y", "data/portable.json"])

        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            app = _FakeApp(store, None)
            app.configuration = SimpleNamespace(
                import_file=lambda path, ui: SimpleNamespace(subscriptions_added=0)
            )
            app.download = SimpleNamespace(setup=lambda ui: self.fail("download setup should be skipped"))
            wizard = SetupWizard(app, input_fn=lambda prompt: next(answers), print_fn=output.append)

            self.assertTrue(wizard.run())
            self.assertEqual(store.get_config("core", "setup_complete"), "on")
            self.assertTrue(any("Setup complete." in message for message in output))
            store.conn.close()


if __name__ == "__main__":
    unittest.main()
