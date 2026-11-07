import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from launcher import parasite_fonts

BUNDLED = Path(__file__).resolve().parents[2] / "assets" / "parasite_fonts" / parasite_fonts.DEFAULT_FILE


class FontTests(unittest.TestCase):
    def setUp(self):
        from injection.mods.storage import ModStorageService
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.storage = ModStorageService(self.root / "mods")
        self.saved = {}
        for target, kwargs in (
            ("launcher.parasite_fonts._storage", {"return_value": self.storage}),
            ("launcher.parasite_fonts._marker_path", {"return_value": self.root / "parasite_fonts.json"}),
            ("launcher.parasite_fonts._bundled", {"return_value": BUNDLED}),
            ("utils.core.mod_historic.get_historic_mod", {"side_effect": lambda kind: self.saved.get(kind)}),
            ("utils.core.mod_historic.write_historic_mod", {"side_effect": self.saved.__setitem__}),
            ("utils.core.mod_historic.clear_historic_mod", {"side_effect": lambda kind: self.saved.pop(kind, None)}),
        ):
            p = patch(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        self.state = SimpleNamespace(selected_font_mod={"mod_name": "old"})
        parasite_fonts.attach_state(self.state)
        self.addCleanup(parasite_fonts.attach_state, None)

    def _upload(self, name="Comic.fantome"):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr("WAD/Bootstrap.windows.wad.client", b"font")
        data = data.getvalue()
        return parasite_fonts.import_upload(name, io.BytesIO(data), len(data))

    def test_the_bundled_font_is_a_fantome(self):
        with zipfile.ZipFile(BUNDLED) as z:
            self.assertIn("WAD/Bootstrap.windows.wad.client", z.namelist())

    def test_korean_is_added_and_picked_on_a_fresh_install(self):
        listing = parasite_fonts.listing()
        self.assertEqual([f["name"] for f in listing["installed"]], [parasite_fonts.DEFAULT_NAME])
        self.assertTrue(listing["installed"][0]["parasite"])
        self.assertTrue(listing["installed"][0]["selected"])
        self.assertEqual(self.saved["font"], listing["selected"])

    def test_the_default_does_not_come_back_once_the_user_chose(self):
        parasite_fonts.ensure_default()
        parasite_fonts.select(None)
        self.assertIsNone(self.state.selected_font_mod)
        self.assertIsNone(parasite_fonts.listing()["selected"])
        parasite_fonts.delete(parasite_fonts.installed()[0]["id"])
        self.assertEqual(parasite_fonts.listing()["installed"], [])

    def test_an_existing_pick_is_kept(self):
        self._upload()
        mine = parasite_fonts.installed()[0]["id"]
        parasite_fonts.select(mine)
        parasite_fonts.ensure_default()
        self.assertEqual(self.saved["font"], mine)
        self.assertEqual(len(parasite_fonts.installed()), 2)

    def test_a_dropped_font_can_be_picked(self):
        parasite_fonts.ensure_default()
        self.assertIn("eklendi", self._upload())
        self.assertIn("Yalnızca", self._upload(name="font.ttf"))
        comic = next(f for f in parasite_fonts.installed() if not f["parasite"])
        self.assertIn("Comic", parasite_fonts.select(comic["id"]))
        self.assertEqual(self.saved["font"], comic["id"])


if __name__ == "__main__":
    unittest.main()
