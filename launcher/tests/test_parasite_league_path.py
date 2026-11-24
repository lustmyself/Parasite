import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from launcher import parasite_default_rift as rift
from launcher import parasite_league_path as league


class LeaguePathTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.install = self.root / "D" / "Oyunlar" / "Riot Games" / "League of Legends"
        self.game = self.install / "Game"
        self.game.mkdir(parents=True)
        (self.game / "League of Legends.exe").write_bytes(b"")
        (self.install / "LeagueClient.exe").write_bytes(b"")

    def test_game_dir_of_any_part_of_the_install(self):
        for path in (self.install, self.game, self.install / "LeagueClient.exe",
                     self.game / "League of Legends.exe", f'"{self.install}"'):
            self.assertEqual(league.game_dir_of(path), self.game, path)
        self.assertIsNone(league.game_dir_of(self.root))
        self.assertIsNone(league.game_dir_of(""))
        self.assertIsNone(league.game_dir_of(self.root / "missing"))

    def test_riot_client_installs(self):
        path = self.root / "RiotClientInstalls.json"
        path.write_text(json.dumps({
            "associated_client": {f"{self.install.as_posix()}/": "C:/Riot Games/Riot Client/RiotClientServices.exe"},
            "rc_default": "C:/Riot Games/Riot Client/RiotClientServices.exe"}), encoding="utf-8")
        found = league.from_riot_installs(path)
        self.assertEqual(len(found), 1)
        self.assertEqual(league.game_dir_of(found[0]), self.game)
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(league.from_riot_installs(path), [])
        self.assertEqual(league.from_riot_installs(self.root / "none.json"), [])

    def test_product_settings(self):
        path = self.root / "league_of_legends.live.product_settings.yaml"
        path.write_text('auto_patching_enabled_by_player: false\n'
                        f'product_install_full_path: "{self.install.as_posix()}"\n'
                        'product_install_root: "D:/Oyunlar"\n', encoding="utf-8")
        self.assertEqual([league.game_dir_of(p) for p in league.from_product_settings(path)], [self.game])

    def test_drives(self):
        found = [league.game_dir_of(p) for p in league.from_drives([str(self.root / "D")])]
        self.assertIn(self.game, found)

    def test_find_saves_what_it_finds(self):
        with mock.patch.object(league, "_configured", return_value=None), \
             mock.patch.object(league, "candidates", return_value=iter([str(self.root), str(self.install)])), \
             mock.patch.object(league, "remember") as remember:
            self.assertEqual(league.find_game_dir(), self.game)
        remember.assert_called_once_with(self.game)
        with mock.patch.object(league, "_configured", return_value=None), \
             mock.patch.object(league, "candidates", return_value=iter([str(self.root)])):
            self.assertIsNone(league.find_game_dir())

    def test_ask(self):
        with mock.patch.object(league, "remember") as remember:
            self.assertEqual(league.ask(lambda: self.install / "LeagueClient.exe"), self.game)
            remember.assert_called_once_with(self.game)
            with self.assertRaises(league.NotPicked):
                league.ask(lambda: None)
            with self.assertRaises(league.NotPicked):
                league.ask(lambda: self.root / "D")

    def test_default_rift_asks_when_league_is_not_found(self):
        with mock.patch.object(rift, "game_dir", return_value=None), \
             mock.patch.object(league, "_pick_file", return_value=None):
            self.assertIn("klasör seçilmedi", rift.install())
        with mock.patch.object(rift, "game_dir", return_value=None), \
             mock.patch.object(league, "ask", return_value=self.game), \
             mock.patch.object(rift, "last_map_skin", return_value=None) as skin:
            self.assertIn("Sezonluk harita görülmedi", rift.install())
            skin.assert_called_once_with(self.game)


if __name__ == "__main__":
    unittest.main()
