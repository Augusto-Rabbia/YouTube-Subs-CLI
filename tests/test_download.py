from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stdout
import io
import tempfile
import unittest
from unittest.mock import patch

from ytsubs.core.app import App
from ytsubs.core.commands import CommandRegistry
from ytsubs.core.download import DownloadConfig, DownloadService, build_yt_dlp_command
from ytsubs.core.store import Store


class DownloadServiceTests(unittest.TestCase):
    def test_download_command_does_not_create_info_json_sidecar(self) -> None:
        config = DownloadConfig(
            directory=Path("/tmp/videos"),
            quality="1080p",
            container="mkv",
            auto_watch=True,
            sb_actions={},
        )

        command = build_yt_dlp_command("https://youtu.be/abcdefghijk", config)

        self.assertNotIn("--write-info-json", command)
        self.assertIn("home:/tmp/videos", command)

    def test_download_directory_can_be_configured_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            store = Store(root / "data" / "test.sqlite3")
            service = DownloadService(store)
            with patch("ytsubs.core.download.PROJECT_ROOT", root):
                with redirect_stdout(io.StringIO()):
                    self.assertTrue(service.set_directory("media/videos"))
                self.assertEqual(service.config().directory, root / "media" / "videos")
                self.assertTrue((root / "media" / "videos").is_dir())
            store.conn.close()

    def test_download_declares_only_media_actions_as_access_controlled(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = Store(Path(tempdir) / "test.sqlite3")
            service = DownloadService(store)
            registry = CommandRegistry()
            service.register_commands(registry)
            spec = registry.commands["download"]
            self.assertIsNone(spec.addon_name)
            self.assertTrue(spec.requires_access(["1"]))
            self.assertFalse(spec.requires_access(["cfg", "quality", "720p"]))
            self.assertFalse(spec.requires_access(["setup"]))
            store.conn.close()

    def test_core_download_service_owns_its_setup_command(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            store = Store(root / "data" / "test.sqlite3")
            service = DownloadService(store)
            responses = ["downloads/selected", "720p", "mp4", "n", "n"]
            with (
                patch("ytsubs.core.download.PROJECT_ROOT", root),
                patch("builtins.input", side_effect=responses),
                redirect_stdout(io.StringIO()),
            ):
                service.command(["setup"])
                config = service.config()
                self.assertEqual(config.directory, root / "downloads" / "selected")
            self.assertEqual(config.quality, "720p")
            self.assertEqual(config.container, "mp4")
            self.assertFalse(config.auto_watch)
            store.conn.close()

    def test_app_registers_download_as_core_functionality(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            with (
                patch("ytsubs.core.app.db_path", return_value=root / "test.sqlite3"),
                patch("ytsubs.core.addons.MODS_DIR", root / "mods"),
            ):
                app = App()
            self.assertIn("download", app.registry.commands)
            self.assertIsNone(app.registry.commands["download"].addon_name)
            self.assertNotIn("download", app.addons.addons)
            app.store.conn.close()


if __name__ == "__main__":
    unittest.main()
