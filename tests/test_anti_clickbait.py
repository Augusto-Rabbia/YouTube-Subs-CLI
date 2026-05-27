from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ytsubs.addons.anti_clickbait import AntiClickbaitAddon, shift_caps_title
from ytsubs.core.addons import AddonRegistry, SetupPrompts
from ytsubs.core.models import Video, VideoListContext
from ytsubs.core.store import Store


class AntiClickbaitAddonTests(unittest.TestCase):
    def test_command_is_registered_under_new_name_only(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            addon = AntiClickbaitAddon(store)
            registry = AddonRegistry()
            addon.register_commands(registry)
            self.assertIn("anti-clickbait", registry.commands)
            self.assertNotIn("dearrow", registry.commands)
            store.conn.close()

    def test_shift_caps_title_capitalizes_words_without_changing_punctuation(self) -> None:
        self.assertEqual(
            shift_caps_title("THIS isn't a normal-title: déjà VU"),
            "This Isn't A Normal-Title: Déjà Vu",
        )

    def test_shift_caps_formats_replacement_and_original_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            addon = AntiClickbaitAddon(store)
            video = Video(
                video_id="abcdefghijk",
                channel_id="channel",
                channel_name="Channel",
                title="ORIGINAL clickBAIT title",
                url="https://youtu.be/abcdefghijk",
                published_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
            )
            ctx = VideoListContext("new", "New:")
            store.set_config(addon.storage_namespace, "casing", "shift-caps")

            with patch.object(addon, "get_replacement_title", return_value="better VIDEO title"):
                self.assertEqual(addon.render_title(ctx, video, video.title), "Better Video Title")
                store.set_config(addon.storage_namespace, "mode", "both")
                self.assertEqual(
                    addon.render_title(ctx, video, video.title),
                    "Better Video Title [original: Original Clickbait Title]",
                )
                store.set_config(addon.storage_namespace, "mode", "original")
                self.assertEqual(addon.render_title(ctx, video, video.title), "Original Clickbait Title")
            store.conn.close()

    def test_casing_configuration_is_addon_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            addon = AntiClickbaitAddon(store)
            with redirect_stdout(io.StringIO()):
                addon.command(["cfg", "casing", "shift-caps"])
            self.assertEqual(addon.casing(), "shift-caps")
            self.assertEqual(store.get_config(addon.storage_namespace, "casing"), "shift-caps")
            store.conn.close()

    def test_rename_preserves_existing_dearrow_state_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            store.set_addon_enabled("dearrow", True)
            store.set_config("dearrow", "mode", "both")
            addon = AntiClickbaitAddon(store)
            self.assertTrue(addon.enabled)
            self.assertEqual(addon.mode(), "both")
            store.conn.close()

    def test_setup_discloses_dearrow_api_and_support_request_before_enablement(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            addon = AntiClickbaitAddon(store)
            output: list[str] = []
            ui = SetupPrompts(input_fn=lambda prompt: "n", print_fn=output.append)
            addon.setup(ui)
            text = "\n".join(output)
            self.assertIn("DeArrow API", text)
            self.assertIn("consider supporting the DeArrow project", text)
            store.conn.close()


if __name__ == "__main__":
    unittest.main()
