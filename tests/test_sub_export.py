from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ytsubs.core.app import App


class SubscriptionExportTests(unittest.TestCase):
    def test_default_export_is_written_to_configured_data_directory(self) -> None:
        app = App.__new__(App)
        app.store = MagicMock()
        app.store.list_subscriptions.return_value = [
            {
                "channel_id": "UC123",
                "display_name": "Channel",
                "url": "https://www.youtube.com/channel/UC123",
            }
        ]

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = Path(tempdir) / "data"
            with (
                patch("ytsubs.core.paths.DATA_DIR", data_dir),
                redirect_stdout(io.StringIO()),
            ):
                app.sub_export()

            output = data_dir / "ytsubs_subscriptions.opml"
            self.assertTrue(output.exists())
            self.assertIn("Channel", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
