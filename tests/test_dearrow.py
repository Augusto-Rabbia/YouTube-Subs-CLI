from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ytsubs.addons.dearrow import DeArrowAddon, shift_caps_title
from ytsubs.core.models import Video, VideoListContext
from ytsubs.core.store import Store


class DeArrowAddonTests(unittest.TestCase):
    def test_shift_caps_title_capitalizes_words_without_changing_punctuation(self) -> None:
        self.assertEqual(
            shift_caps_title("THIS isn't a normal-title: déjà VU"),
            "This Isn't A Normal-Title: Déjà Vu",
        )

    def test_shift_caps_formats_replacement_and_original_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            addon = DeArrowAddon(store)
            video = Video(
                video_id="abcdefghijk",
                channel_id="channel",
                channel_name="Channel",
                title="ORIGINAL clickBAIT title",
                url="https://youtu.be/abcdefghijk",
                published_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
            )
            ctx = VideoListContext("new", "New:")
            store.set_config(addon.name, "casing", "shift-caps")

            with patch.object(addon, "get_replacement_title", return_value="better VIDEO title"):
                self.assertEqual(addon.render_title(ctx, video, video.title), "Better Video Title")
                store.set_config(addon.name, "mode", "both")
                self.assertEqual(
                    addon.render_title(ctx, video, video.title),
                    "Better Video Title [original: Original Clickbait Title]",
                )
                store.set_config(addon.name, "mode", "original")
                self.assertEqual(addon.render_title(ctx, video, video.title), "Original Clickbait Title")
            store.conn.close()

    def test_casing_configuration_is_addon_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            addon = DeArrowAddon(store)
            with redirect_stdout(io.StringIO()):
                addon.command(["cfg", "casing", "shift-caps"])
            self.assertEqual(addon.casing(), "shift-caps")
            self.assertEqual(store.get_config(addon.name, "casing"), "shift-caps")
            store.conn.close()


if __name__ == "__main__":
    unittest.main()
