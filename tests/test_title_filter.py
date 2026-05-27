from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from ytsubs.addons.title_filter import TitleFilterAddon
from ytsubs.core.store import Store


class TitleFilterAddonTests(unittest.TestCase):
    def test_regex_storage_uses_namespaced_addon_config(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            store = Store(root / "main.sqlite3")
            addon = TitleFilterAddon(store)
            with redirect_stdout(io.StringIO()):
                addon.command(["add", "unboxing"])
            self.assertEqual(addon.list_title_filters()[0]["pattern"], "unboxing")
            self.assertEqual(store.get_config("title-filter", "patterns"), '["unboxing"]')

            central_table = store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'title_filters'"
            ).fetchone()
            self.assertIsNone(central_table)

            other_store = Store(root / "other.sqlite3")
            self.assertEqual(TitleFilterAddon(other_store).list_title_filters(), [])
            other_store.conn.close()
            store.conn.close()


if __name__ == "__main__":
    unittest.main()
