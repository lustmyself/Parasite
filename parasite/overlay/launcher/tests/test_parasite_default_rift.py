import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from injection.baseskin.propbin import Bin, Entry, Field, Value, build, fnv1a_lower
from injection.baseskin.wad import GameWad, ModWad
from launcher import parasite_default_rift as rift

NAME_FIELD = fnv1a_lower("name")
SEASONAL = "Maps/MapGeometry/Map11/Milkshake_SRS"


def _container(path: str) -> Entry:
    return Entry(fnv1a_lower("MapContainer"), fnv1a_lower(path), [Field(NAME_FIELD, Value.string(path))])


def _material(path: str, text: str) -> Entry:
    return Entry(fnv1a_lower("StaticMaterialDef"), fnv1a_lower(path), [Field(NAME_FIELD, Value.string(text))])


def _entries(data: bytes) -> dict:
    parsed = Bin(data)
    found = {}
    for type_hash, (start, end) in zip(parsed.types, parsed._locate()):
        entry = rift._parse_entry(data, type_hash, start, end)
        found[entry.path_hash] = entry.fields[0].value.as_string()
    return found


BASE = build([_container(rift.DEFAULT_CONTAINER), _material("Maps/Grass", "base grass")])
WINTER = build([_container(SEASONAL), _material("Maps/Grass", "snowy grass"), _material("Maps/Snow", "snow")])


class MaterialsTest(unittest.TestCase):
    def test_the_default_materials_take_the_seasonal_name(self):
        merged = _entries(rift.merged_materials(BASE, WINTER, SEASONAL))
        self.assertEqual(merged[fnv1a_lower(SEASONAL)], SEASONAL)
        self.assertNotIn(fnv1a_lower(rift.DEFAULT_CONTAINER), merged)
        self.assertEqual(merged[fnv1a_lower("Maps/Grass")], "base grass")  # the default look wins
        self.assertEqual(merged[fnv1a_lower("Maps/Snow")], "snow")  # seasonal-only entries are kept
        self.assertEqual(len(merged), 3)

    def test_materials_without_the_default_container_are_refused(self):
        with self.assertRaises(rift.DefaultRiftError):
            rift.merged_materials(WINTER, WINTER, SEASONAL)


class GameTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.game = self.root / "Game"
        self.game.mkdir()

    def _log(self, run: str, skin: str):
        folder = self.root / "Logs" / "GameLogs" / run
        folder.mkdir(parents=True)
        (folder / f"{run}_r3dlog.txt").write_text(f"000.1| ALWAYS| mapskin = {skin}\n", encoding="utf-8")

    def test_the_newest_seasonal_map_skin_is_read_from_the_logs(self):
        self._log("2026-11-17T10-00-00", "Milkshake_Swiftplay")
        self._log("2026-11-18T10-00-00", "Milkshake_SRS")
        self._log("2026-11-18T11-00-00", "Default")
        self.assertEqual(rift.last_map_skin(self.game), "Milkshake_SRS")

    def test_no_logs_no_map_skin(self):
        self.assertIsNone(rift.last_map_skin(self.game))

    def _wad(self):
        skin = Entry(fnv1a_lower("MapSkin"), fnv1a_lower(rift.MAP_SKIN.format("Milkshake_SRS")),
                     [Field(fnv1a_lower("mMapContainerLink"), Value.string(SEASONAL))])
        wad = ModWad(rift.EMPTY_WAD)
        wad.put_path(rift.MAP_BIN, build([skin]))
        wad.put_path(rift.GEOMETRY.format("base_srx"), b"default geometry")
        wad.put_path(rift.GEOMETRY.format("milkshake_srs"), b"winter geometry")
        wad.put_path(rift.MATERIALS.format("base_srx"), BASE)
        wad.put_path(rift.MATERIALS.format("milkshake_srs"), WINTER)
        path = self.game / rift.MAP_WAD
        path.parent.mkdir(parents=True)
        path.write_bytes(wad.to_bytes())

    def test_the_mod_carries_the_default_map_under_the_seasonal_names(self):
        self._wad()
        target = rift.build(self.game, "Milkshake_SRS", self.root / "out" / "Default Rift.fantome")
        with zipfile.ZipFile(target) as archive:
            self.assertIn("META/info.json", archive.namelist())
            inner = self.root / "inner.wad.client"
            inner.write_bytes(archive.read("WAD/Map11.wad.client"))
        mod = GameWad(inner)
        self.assertEqual(mod.read_path(rift.GEOMETRY.format("milkshake_srs")), b"default geometry")
        materials = _entries(mod.read_path(rift.MATERIALS.format("milkshake_srs")))
        self.assertEqual(materials[fnv1a_lower(SEASONAL)], SEASONAL)
        self.assertFalse(mod.has_path(rift.GEOMETRY.format("base_srx")))

    def test_the_default_map_skin_is_not_rebuilt(self):
        self._wad()
        with self.assertRaises(rift.DefaultRiftError):
            rift.build(self.game, "Base_SRX", self.root / "x.fantome")

    def test_a_game_without_the_map_file_is_refused(self):
        with self.assertRaises(rift.DefaultRiftError):
            rift.build(self.game, "Milkshake_SRS", self.root / "x.fantome")

if __name__ == "__main__":
    unittest.main()
