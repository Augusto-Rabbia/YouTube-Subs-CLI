from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ytsubs.core.app import App
from ytsubs.core.models import ChannelCandidate
from ytsubs.core.prompts import SetupPrompts


class ConfigurationTransferTests(unittest.TestCase):
    def make_app(self, root: Path, filename: str) -> App:
        with (
            patch("ytsubs.core.app.db_path", return_value=root / filename),
            patch("ytsubs.core.addons.MODS_DIR", root / "mods"),
        ):
            return App()

    def test_full_configuration_export_and_import_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = self.make_app(root, "source.sqlite3")
            channel_id = "UCabcdefghijklmnopqrstuv"
            source.store.add_subscription(
                ChannelCandidate(channel_id, "Channel", "@channel", "https://youtube.test/channel")
            )
            source.store.add_channel_category(channel_id, "Study")
            source.store.set_config("core", "new_days", "14")
            source.store.set_config("download", "quality", "720p")
            with redirect_stdout(io.StringIO()):
                source.addons.addons["title-filter"].disable()
            source.store.set_config("title-filter", "filter_shorts", "on")
            export_path = root / "portable.json"
            with redirect_stdout(io.StringIO()):
                source.dispatch("config", ["export", str(export_path)])
            self.assertTrue(export_path.exists())

            target = self.make_app(root, "target.sqlite3")
            result = target.configuration.import_file(
                str(export_path),
                SetupPrompts(input_fn=lambda prompt: "n", print_fn=lambda message: None),
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.subscriptions_added, 1)
            self.assertEqual(target.store.list_subscriptions()[0]["handle"], "@channel")
            self.assertEqual(target.store.get_channel_categories(channel_id), ["Study"])
            self.assertEqual(target.store.get_config("core", "new_days"), "14")
            self.assertEqual(target.download.config().quality, "720p")
            self.assertFalse(target.addons.addons["title-filter"].enabled)
            self.assertEqual(target.store.get_config("title-filter", "filter_shorts"), "on")
            source.store.conn.close()
            target.store.conn.close()


if __name__ == "__main__":
    unittest.main()
