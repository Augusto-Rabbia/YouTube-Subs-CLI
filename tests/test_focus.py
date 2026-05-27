from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ytsubs.addons.focus import FocusAddon, parse_days, parse_ranges
from ytsubs.core.addons import SetupPrompts
from ytsubs.core.app import App
from ytsubs.core.models import Video, VideoListContext
from ytsubs.core.store import Store


class FocusAddonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tempdir.name) / "test.sqlite3")
        self.addon = FocusAddon(self.store)

    def tearDown(self) -> None:
        self.store.conn.close()
        self.tempdir.cleanup()

    def test_schedule_parsing_supports_day_groups_and_access_windows(self) -> None:
        self.assertEqual(parse_days("mon-thu"), ["mon", "tue", "wed", "thu"])
        self.assertEqual(parse_days("weekends"), ["sat", "sun"])
        self.assertEqual(parse_ranges("16:00-18:00,20:00-21:00"), ["16:00-18:00", "20:00-21:00"])

    def test_allow_schedule_blocks_protected_actions_outside_windows(self) -> None:
        self.store.set_addon_enabled(self.addon.name, True)
        self.addon.write_schedule(
            {"mon": {"mode": "allow", "ranges": ["16:00-18:00", "20:00-21:00"]}}
        )
        blocked_time = datetime(2026, 5, 25, 15, 0)
        allowed_time = datetime(2026, 5, 25, 16, 0)
        with redirect_stdout(io.StringIO()):
            self.assertFalse(self.addon.command_allowed("latest", ["5"], True, blocked_time))
            self.assertFalse(self.addon.command_allowed("download", ["1"], True, blocked_time))
            self.assertFalse(self.addon.command_allowed("setup", [], True, blocked_time))
        self.assertTrue(self.addon.command_allowed("latest", ["5"], True, allowed_time))
        self.assertTrue(self.addon.command_allowed("download", ["cfg"], False, blocked_time))
        self.assertTrue(self.addon.command_allowed("new", ["default"], False, blocked_time))

    def test_invincible_defers_changes_and_shutdown_until_effective_time(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.addon.enable_invincible(["confirm"])
        warning = output.getvalue()
        self.assertIn("WARNING: Invincible mode", warning)
        self.assertIn("05:00", warning)
        self.assertTrue(self.addon.enabled)
        self.assertTrue(self.addon.invincible_enabled())

        with redirect_stdout(io.StringIO()):
            self.addon.command_schedule(["set", "mon-thu", "allow", "16:00-18:00"])
            self.addon.command_schedule(["clear", "mon"])
            self.addon.command_schedule(["set", "fri", "block", "09:00-17:00"])
        self.assertEqual(self.addon.schedule(), {})
        pending = self.addon.pending()
        effective_at = datetime.strptime(str(pending["schedule"]["effective_at"]), "%Y-%m-%d %H:%M")

        self.addon.apply_pending(effective_at - timedelta(minutes=1))
        self.assertEqual(self.addon.schedule(), {})
        self.addon.apply_pending(effective_at)
        self.assertNotIn("mon", self.addon.schedule())
        self.assertIn("tue", self.addon.schedule())
        self.assertIn("fri", self.addon.schedule())

        with redirect_stdout(io.StringIO()):
            self.addon.disable()
        self.assertTrue(self.addon.enabled)
        shutdown_at = datetime.strptime(
            str(self.addon.pending()["invincible"]["effective_at"]), "%Y-%m-%d %H:%M"
        )
        self.addon.apply_pending(shutdown_at)
        self.assertFalse(self.addon.invincible_enabled())
        self.assertFalse(self.addon.enabled)

    def test_invincible_restores_focus_enablement_before_access_checks(self) -> None:
        self.store.set_config(self.addon.name, "invincible", "on")
        self.store.set_addon_enabled(self.addon.name, False)
        self.assertTrue(self.addon.command_allowed("latest", ["5"], True, datetime(2026, 5, 25, 12, 0)))
        self.assertTrue(self.addon.enabled)

    def test_import_warns_before_restoring_invincible_mode(self) -> None:
        output: list[str] = []
        payload = {
            "enabled": True,
            "config": {"invincible": "on", "pending": '{"seconds":{"value":"0"}}'},
        }
        self.addon.write_pending({"seconds": {"value": "60", "effective_at": "2026-05-28 05:00"}})
        ui = SetupPrompts(input_fn=lambda prompt: "n", print_fn=output.append)
        self.addon.import_config_snapshot(payload, ui)

        self.assertFalse(self.addon.invincible_enabled())
        self.assertIsNone(self.store.get_config(self.addon.name, "pending"))
        self.assertIn("WARNING: Invincible mode", "\n".join(output))
        self.assertIn("  Invincible mode was not restored.", output)

    def test_key_press_cancels_delay_hook(self) -> None:
        self.store.set_config(self.addon.name, "seconds", "3")
        video = Video(
            video_id="abcdefghijk",
            channel_id="channel",
            channel_name="Channel",
            title="Title",
            url="https://youtu.be/abcdefghijk",
            published_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        )
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("ytsubs.addons.focus.wait_for_key_or_timeout", return_value=False),
        ):
            allowed = self.addon.before_video_list(VideoListContext("new", "New:"), [video])
        self.assertFalse(allowed)

    def test_cancelled_list_does_not_replace_previous_list_cache(self) -> None:
        old_video = Video(
            video_id="oldvideo001",
            channel_id="channel",
            channel_name="Channel",
            title="Old",
            url="https://youtu.be/oldvideo001",
            published_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
        )
        new_video = Video(
            video_id="newvideo001",
            channel_id="channel",
            channel_name="Channel",
            title="New",
            url="https://youtu.be/newvideo001",
            published_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        )
        app = App.__new__(App)
        app.last_videos = [old_video]
        app.store = MagicMock()
        app.metadata = MagicMock()
        app.metadata.with_durations.return_value = [new_video]
        app.download = MagicMock()
        app.addons = MagicMock()
        app.addons.apply_filters.return_value = [new_video]
        app.addons.before_video_list.return_value = False

        with redirect_stdout(io.StringIO()):
            app._print_video_list(VideoListContext("new", "New:"), [new_video], empty_message="No videos.")

        self.assertEqual(app.last_videos, [old_video])
        app.download.cache_video_list.assert_not_called()
        app.store.delete_cache_prefix.assert_not_called()
        app.store.set_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
