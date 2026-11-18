import shutil
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from injection.baseskin.propbin import HASH, MAP, POINTER, Bin, Embed, Entry, Field, Value, build, fnv1a_lower
from injection.baseskin.wad import GameWad, ModWad
from launcher import parasite_default_rift as rift

NAME_FIELD = fnv1a_lower("name")
SEASONAL = "Maps/MapGeometry/Map11/Milkshake_SRS"


PLACED = fnv1a_lower("mPlaceables")


def _map(pairs) -> Value:
    return Value(MAP, [(Value(HASH, struct.pack("<I", k)), Value(HASH, struct.pack("<I", v))) for k, v in pairs],
                 HASH, HASH)


def _container(path: str, terrain: str, pairs) -> Entry:
    return Entry(fnv1a_lower("MapContainer"), fnv1a_lower(path),
                 [Field(NAME_FIELD, Value.string(path)), Field(TERRAIN_FIELD, Value.string(terrain)),
                  Field(PLACED, _map(pairs))])


def _material(path: str, text: str, kind: str = "StaticMaterialDef") -> Entry:
    return Entry(fnv1a_lower(kind), fnv1a_lower(path), [Field(NAME_FIELD, Value.string(text))])


def _placeables(path: str, objects) -> Entry:
    """A MapPlaceableContainer placing {key: skin} structures."""
    embed = fnv1a_lower("MapPlaceable")
    pairs = [(Value(HASH, struct.pack("<I", key)),
              Value(POINTER, Embed(embed, [Field(SKIN_FIELD, Value.string(skin))]))) for key, skin in objects]
    return Entry(fnv1a_lower("MapPlaceableContainer"), fnv1a_lower(path),
                 [Field(fnv1a_lower("items"), Value(MAP, pairs, HASH, POINTER))])


def _entries(data: bytes) -> dict:
    parsed = Bin(data)
    found = {}
    for type_hash, (start, end) in zip(parsed.types, parsed._locate()):
        entry = rift._parse_entry(data, type_hash, start, end)
        found[entry.path_hash] = entry
    return found


def _skins_of(entry) -> dict:
    return {struct.unpack("<I", k.v)[0]: v.v.fields[0].value.v for k, v in entry.fields[0].value.v}


TERRAIN_FIELD = fnv1a_lower("terrainPaint")
SKIN_FIELD = fnv1a_lower("skin")
BASE = build([
    _container(rift.DEFAULT_CONTAINER, "Base_SRX.tex", [(1, 10), (2, 20), (9, 90)]),
    _material("Maps/Grass", "base grass"),
    _placeables("Maps/Structures", [(100, "Characters/Turret/Skins/Skin0"), (101, "Characters/Turret/Skins/Skin3")]),
])
WINTER = build([
    _material("Maps/Grass", "snowy grass"),
    _material("Maps/Snow", "snow"),
    _material("Maps/SnowFx", "snow effect", "VfxSystemDefinitionData"),
    _placeables("Maps/WinterStructures", [(100, "Characters/Turret/Skins/Skin48"),
                                          (101, "Characters/Turret/Skins/Skin49"),
                                          (102, "Characters/Snowman/Skins/Skin1")]),
    _container(SEASONAL, "Milkshake_SRS.tex", [(5, 55), (1, 11), (2, 22)]),
])


class MaterialsTest(unittest.TestCase):
    def setUp(self):
        self.merged = _entries(rift.merged_materials(BASE, WINTER, SEASONAL))

    def test_the_seasonal_container_takes_the_default_placeables(self):
        container = self.merged[fnv1a_lower(SEASONAL)]
        self.assertNotIn(fnv1a_lower(rift.DEFAULT_CONTAINER), self.merged)
        fields = {f.name_hash: f.value for f in container.fields}
        self.assertEqual(fields[NAME_FIELD].v, SEASONAL)
        self.assertEqual(fields[TERRAIN_FIELD].v, "Milkshake_SRS.tex")
        pairs = [(struct.unpack("<I", k.v)[0], struct.unpack("<I", v.v)[0]) for k, v in fields[PLACED].v]
        # the seasonal keys in their order with the default values, then the default-only keys
        self.assertEqual(pairs, [(5, 55), (1, 10), (2, 20), (9, 90)])

    def test_the_default_entries_win_and_every_seasonal_only_entry_comes_along(self):
        self.assertEqual(self.merged[fnv1a_lower("Maps/Grass")].fields[0].value.v, "base grass")
        self.assertEqual(self.merged[fnv1a_lower("Maps/Snow")].fields[0].value.v, "snow")
        self.assertEqual(self.merged[fnv1a_lower("Maps/SnowFx")].fields[0].value.v, "snow effect")
        self.assertEqual(len(self.merged), 6)

    def test_seasonal_structures_get_the_default_skins(self):
        winter = _skins_of(self.merged[fnv1a_lower("Maps/WinterStructures")])
        self.assertEqual(winter, {100: "Characters/Turret/Skins/Skin0", 101: "Characters/Turret/Skins/Skin3",
                                  102: "Characters/Snowman/Skins/Skin1"})

    def test_the_order_is_the_default_one_then_the_seasonal_extras(self):
        parsed = Bin(rift.merged_materials(BASE, WINTER, SEASONAL))
        paths = [rift._parse_entry(parsed._data, t, s, e).path_hash for t, (s, e) in zip(parsed.types, parsed._locate())]
        self.assertEqual(paths, [fnv1a_lower(p) for p in (SEASONAL, "Maps/Grass", "Maps/Structures", "Maps/Snow",
                                                          "Maps/SnowFx", "Maps/WinterStructures")])

    def test_materials_without_either_container_are_refused(self):
        with self.assertRaises(rift.DefaultRiftError):
            rift.merged_materials(WINTER, WINTER, SEASONAL)
        with self.assertRaises(rift.DefaultRiftError):
            rift.merged_materials(BASE, BASE, SEASONAL)


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
        self.assertIn(fnv1a_lower(SEASONAL), materials)
        self.assertFalse(mod.has_path(rift.GEOMETRY.format("base_srx")))
        self.assertFalse(mod.has_path(rift.MAP_BIN))

    def test_the_default_map_skin_is_not_rebuilt(self):
        self._wad()
        with self.assertRaises(rift.DefaultRiftError):
            rift.build(self.game, "Base_SRX", self.root / "x.fantome")

    def test_a_game_without_the_map_file_is_refused(self):
        with self.assertRaises(rift.DefaultRiftError):
            rift.build(self.game, "Milkshake_SRS", self.root / "x.fantome")

if __name__ == "__main__":
    unittest.main()
