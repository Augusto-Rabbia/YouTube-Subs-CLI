from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from ytsubs.cli import Shell
from ytsubs.core.addons import AddonManager
from ytsubs.core.store import Store


EXTERNAL_ADDON = """\
from ytsubs.core.addons import BaseAddon


class SoloAddon(BaseAddon):
    name = "solo"
    description = "A one-file external addon."
    default_enabled = False


def create_addon(store):
    return SoloAddon(store)
"""


class AddonContractTests(unittest.TestCase):
    def test_one_external_file_gets_setup_and_help_without_core_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            mods = root / "mods"
            mods.mkdir()
            (mods / "solo.py").write_text(EXTERNAL_ADDON, encoding="ascii")
            store = Store(root / "main.sqlite3")
            with (
                patch("ytsubs.core.addons.MODS_DIR", mods),
                patch("ytsubs.core.addons.DATA_DIR", root / "addon-data"),
            ):
                manager = AddonManager(store)

            self.assertIn("solo", manager.addons)
            self.assertNotIn("download", manager.addons)
            self.assertIn("solo", manager.registry.commands)
            output = io.StringIO()
            with redirect_stdout(output), patch("builtins.input", return_value="") as read_input:
                manager.registry.commands["solo"].handler(["setup"])
            read_input.assert_called_once_with("Enable `solo`? [y/N]: ")
            store.set_addon_enabled("solo", True)
            store.set_config("solo", "option", "stored")
            snapshot = manager.export_config_snapshot()
            self.assertEqual(snapshot["solo"]["config"], {"option": "stored"})

            app = SimpleNamespace(store=store, addons=manager, registry=manager.registry)
            shell = Shell(app)
            output = io.StringIO()
            with redirect_stdout(output):
                shell.do_help("")
                shell.do_help("solo")
            text = output.getvalue()
            self.assertIn("A one-file external addon.", text)
            self.assertIn("Usage:   solo setup", text)
            store.conn.close()
