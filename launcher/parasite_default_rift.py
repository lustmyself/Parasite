#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The default Summoner's Rift during a seasonal map (Winter Rift...), built from the player's game.

The game picks Summoner's Rift's look (its map skin) from the server: "mapskin = Milkshake_SRS"
in the game's log during Winter Rift 2026. Each map skin links a map container
(map11.bin: MapSkin.mMapContainerLink), whose geometry and materials are
data/maps/mapgeometry/map11/<container>.mapgeo and .materials.bin in Map11.wad.client.

Pointing the map skin at the default container (Base_SRX) crashes the game while it loads
(it builds the lane paths of the seasonal container). Mod authors (TheKillerey's Default Rift)
instead ship the default map's files under the seasonal container's names: the game loads the
seasonal map and shows the default one. Their mod carries the files of the patch it was made
for, and a newer game fails on them. This builds the same files from the player's own game, so
they always match the patch (checked: from the 16.6 files it gives TheKillerey's 16.6 materials
byte for byte):

- <seasonal>.mapgeo: Base_SRX's mapgeo, as the game stores it;
- <seasonal>.materials.bin: Base_SRX's entries, in their order, but its MapContainer is the
  seasonal one, whose placeables map takes Base_SRX's values (and keeps the keys only the
  seasonal map has); then the seasonal materials and placeable containers Base_SRX has none of,
  their structures (turrets, inhibitors, nexus, shops) given the skins Base_SRX gives them.
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

from utils.core.logging import get_logger

log = get_logger()

CATALOG_ID = "default-rift"
NAME = "Varsayılan Sihirdar Vadisi"
DESCRIPTION = ("Sezonluk görünüm (Kış Vadisi gibi) yerine League'in varsayılan haritası. "
               "Parasite onu senin oyununun dosyalarından kurar; yeni yamadan sonra yeniden kur.")

MAP_WAD = "DATA/FINAL/Maps/Shipping/Map11.wad.client"
MAP_BIN = "data/maps/shipping/map11/map11.bin"
GEOMETRY = "data/maps/mapgeometry/map11/{}.mapgeo"
MATERIALS = "data/maps/mapgeometry/map11/{}.materials.bin"
DEFAULT_CONTAINER = "Maps/MapGeometry/Map11/Base_SRX"
MAP_SKIN = "Maps/Shipping/Map11/MapSkins/{}"
MAP_CONTAINER_TYPE = "MapContainer"
# The seasonal entries the default materials take along (TheKillerey's Default Rift: its
# materials and placeables, none of its effects or visibility controllers)
SEASONAL_TYPES = ("StaticMaterialDef", "MapPlaceableContainer")
MAPSKIN_LINE = re.compile(r"mapskin\s*=\s*([A-Za-z0-9_]+)")
# The map skins the game has shown Summoner's Rift with that are the default one
DEFAULT_SKINS = {"default", "base_srx", "sr_seasonal_map"}
# A WAD v3.4 with no files: the mod's WAD starts from it
EMPTY_WAD = b"RW\x03\x04" + bytes(264) + struct.pack("<I", 0)


class DefaultRiftError(RuntimeError):
    """The mod can't be built (the message is the player's, in Turkish)."""


# ---- where things are ----

def game_dir() -> Optional[Path]:
    from injection.config.config_manager import ConfigManager
    from injection.game.game_detector import GameDetector
    try:
        path = GameDetector(ConfigManager()).detect_game_dir()
    except Exception as e:  # noqa: BLE001
        log.debug(f"[DefaultRift] Could not find the game: {e}")
        return None
    return Path(path) if path else None


def last_map_skin(game: Path, logs: int = 30) -> Optional[str]:
    """The map skin of the newest game log naming a seasonal one (the game writes
    "mapskin = <name>" as it starts a game)."""
    folder = game.parent / "Logs" / "GameLogs"
    try:
        runs = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)[:logs]
    except OSError:
        return None
    for run in runs:
        for log_file in sorted(run.glob("*_r3dlog.txt")):
            try:
                with log_file.open("r", encoding="utf-8", errors="replace") as handle:
                    head = handle.read(256 * 1024)
            except OSError:
                continue
            match = MAPSKIN_LINE.search(head)
            if match and match.group(1).lower() not in DEFAULT_SKINS:
                return match.group(1)
    return None


# ---- bins ----

def _entries(data: bytes) -> Tuple[bytes, List[int], List[Tuple[int, int, int]], bytes]:
    """(header up to the type list, type hashes, (start, end, path hash) of each entry,
    the bytes after the entries)."""
    from injection.baseskin.propbin import Bin
    parsed = Bin(data)
    bounds = parsed._locate()
    types = list(parsed.types)
    head = data[:parsed._head_end - 4 * len(types) - 4]
    tail = data[bounds[-1][1]:] if bounds else data[parsed._head_end:]
    return head, types, [(s, e, struct.unpack_from("<I", data, s + 4)[0]) for s, e in bounds], tail


def _parse_entry(data: bytes, type_hash: int, start: int, end: int):
    from injection.baseskin.propbin import Entry, _Reader
    reader = _Reader(data[start + 4:end])
    path_hash = reader.u32()
    return Entry(type_hash, path_hash, reader.fields(type_hash))


def map_container(map_bin: bytes, skin: str) -> str:
    """The container a map skin links (map11.bin); the skin's own name when it can't be read."""
    from injection.baseskin.propbin import fnv1a_lower
    fallback = f"Maps/MapGeometry/Map11/{skin}"
    try:
        _head, types, entries, _tail = _entries(map_bin)
        wanted = fnv1a_lower(MAP_SKIN.format(skin))
        for type_hash, (start, end, path_hash) in zip(types, entries):
            if path_hash != wanted:
                continue
            entry = _parse_entry(map_bin, type_hash, start, end)
            field = entry.find_field(fnv1a_lower("mMapContainerLink"))
            text = field.value.as_string() if field is not None else None
            if text:
                return text
            break  # a link stored as a hash, not text
    except Exception as e:  # noqa: BLE001
        log.debug(f"[DefaultRift] Could not read {skin} in map11.bin: {e}")
    return fallback


def _rebuilt(head: bytes, types: List[int], blobs: List[bytes], tail: bytes) -> bytes:
    out = bytearray(head)
    out += struct.pack("<I", len(types))
    out += struct.pack(f"<{len(types)}I", *types)
    for blob in blobs:
        out += blob
    out += tail
    return bytes(out)


def _skins(value, found: list) -> None:
    """The skin paths (Characters/<name>/Skins/Skin<n>) under *value*, in order."""
    text = value.as_string()
    if text is not None:
        if "/Skins/" in text:
            found.append(value)
        return
    inner = value.v
    if isinstance(inner, list):
        for item in inner:
            for part in (item if isinstance(item, tuple) else (item,)):
                if hasattr(part, "ty"):
                    _skins(part, found)
    elif hasattr(inner, "fields"):
        for field in inner.fields:
            _skins(field.value, found)
    elif hasattr(inner, "ty"):
        _skins(inner, found)


def _placed(entry):
    """(key, value) of each object a placeable container places (its map fields)."""
    from injection.baseskin.propbin import MAP
    for field in entry.fields:
        if field.value.ty == MAP:
            yield from field.value.v


def _merged_container(base_entry, seasonal_entry):
    """The seasonal MapContainer whose maps take Base_SRX's values (keys only the seasonal one
    has stay, Base_SRX's other keys come after them)."""
    from injection.baseskin.propbin import MAP
    base_maps = {f.name_hash: f.value for f in base_entry.fields if f.value.ty == MAP}
    for field in seasonal_entry.fields:
        base = base_maps.get(field.name_hash)
        if field.value.ty != MAP or base is None:
            continue
        values = {key.v: value for key, value in base.v}
        seen = set()
        pairs = []
        for key, value in field.value.v:
            seen.add(key.v)
            pairs.append((key, values.get(key.v, value)))
        pairs += [(key, value) for key, value in base.v if key.v not in seen]
        field.value.v = pairs
    return seasonal_entry


def merged_materials(base: bytes, seasonal: bytes, container: str) -> bytes:
    """The seasonal container's materials showing the default map (see the module's notes)."""
    from injection.baseskin.propbin import _entry_bytes, fnv1a_lower
    container_type = fnv1a_lower(MAP_CONTAINER_TYPE)
    placeables_type = fnv1a_lower("MapPlaceableContainer")
    taken = {fnv1a_lower(name) for name in SEASONAL_TYPES}
    default_hash, seasonal_hash = fnv1a_lower(DEFAULT_CONTAINER), fnv1a_lower(container)
    base_head, base_types, base_entries, base_tail = _entries(base)
    _head, seasonal_types, seasonal_entries, _tail = _entries(seasonal)
    seasonal_container = next(((t, s, e) for t, (s, e, h) in zip(seasonal_types, seasonal_entries)
                               if t == container_type and h == seasonal_hash), None)
    if seasonal_container is None:
        raise DefaultRiftError("Sezonluk haritanın ayarları bulunamadı")

    # The skins Base_SRX gives each object it places
    default_skins = {}
    for type_hash, (start, end, _path) in zip(base_types, base_entries):
        if type_hash == placeables_type:
            for key, value in _placed(_parse_entry(base, type_hash, start, end)):
                found = []
                _skins(value, found)
                if found:
                    default_skins[key.v] = [v.v for v in found]

    types, blobs, seen = [], [], set()
    replaced = False
    for type_hash, (start, end, path_hash) in zip(base_types, base_entries):
        raw = base[start:end]
        if type_hash == container_type and path_hash == default_hash:
            merged = _merged_container(_parse_entry(base, type_hash, start, end),
                                       _parse_entry(seasonal, *seasonal_container))
            raw, path_hash, replaced = _entry_bytes(merged), seasonal_hash, True
        types.append(type_hash)
        blobs.append(raw)
        seen.add(path_hash)
    if not replaced:
        raise DefaultRiftError("Varsayılan haritanın ayarları bulunamadı (Base_SRX)")
    for type_hash, (start, end, path_hash) in zip(seasonal_types, seasonal_entries):
        if path_hash in seen or type_hash not in taken:
            continue
        raw = seasonal[start:end]
        if type_hash == placeables_type:
            entry = _parse_entry(seasonal, type_hash, start, end)
            changed = False
            for key, value in _placed(entry):
                found = []
                _skins(value, found)
                wanted = default_skins.get(key.v)
                if found and wanted and len(wanted) == len(found):
                    for skin, text in zip(found, wanted):
                        changed |= skin.v != text
                        skin.v = text
            if changed:
                raw = _entry_bytes(entry)
        types.append(type_hash)
        blobs.append(raw)
        seen.add(path_hash)
    return _rebuilt(base_head, types, blobs, base_tail)


# ---- the mod ----

def build(game: Path, skin: str, target: Path) -> Path:
    """Write the mod (.fantome) for map skin *skin* to *target*."""
    from injection.baseskin.wad import FileSource, GameWad, ModWad, path_hash
    wad_path = game / MAP_WAD
    if not wad_path.is_file():
        raise DefaultRiftError("Oyunun harita dosyası bulunamadı (Map11.wad.client)")
    wad = GameWad(wad_path)
    map_bin = wad.read_path(MAP_BIN)
    if map_bin is None:
        raise DefaultRiftError("Oyunun harita ayarları bulunamadı (map11.bin)")
    container = map_container(map_bin, skin)
    if container.lower() == DEFAULT_CONTAINER.lower():
        raise DefaultRiftError(f"{skin} zaten varsayılan harita")
    name = container.rsplit("/", 1)[-1].lower()
    base_name = DEFAULT_CONTAINER.rsplit("/", 1)[-1].lower()
    base_materials = wad.read_path(MATERIALS.format(base_name))
    seasonal_materials = wad.read_path(MATERIALS.format(name))
    if base_materials is None or not wad.has_path(GEOMETRY.format(base_name)):
        raise DefaultRiftError("Varsayılan haritanın dosyaları oyunda yok")
    if seasonal_materials is None or not wad.has_path(GEOMETRY.format(name)):
        raise DefaultRiftError(f"{skin} haritasının dosyaları oyunda yok")
    materials = merged_materials(base_materials, seasonal_materials, container)

    source = FileSource(wad_path)
    try:
        mod = ModWad(EMPTY_WAD)
        mod.add(wad.stored_file(GEOMETRY.format(base_name), source, name_hash=path_hash(GEOMETRY.format(name))))
        mod.put_path(MATERIALS.format(name), materials)
        info = {
            "Name": NAME,
            "Author": "Parasite (TheKillerey'in Default Rift yöntemiyle)",
            "Version": "1.2.0",
            "Description": f"{skin} yerine varsayılan Sihirdar Vadisi, oyunun kendi dosyalarından",
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("META/info.json", json.dumps(info, ensure_ascii=False))
            with archive.open("WAD/Map11.wad.client", "w", force_zip64=True) as handle:
                mod.write_to(handle)
    finally:
        source.close()
    log.info(f"[DefaultRift] Built the default Rift in place of {skin} ({container})")
    return target


def install() -> str:
    """Build the mod for the last seasonal map skin, add it to the maps (replacing an
    older build) and pick it for the next game."""
    game = game_dir()
    if game is None:
        return "League bulunamadı: Parasite'ın League klasörünü bildiğinden emin ol"
    skin = last_map_skin(game)
    if skin is None:
        return "Sezonluk harita görülmedi: önce bir Sihirdar Vadisi maçına (antrenman da olur) gir, sonra tekrar dene"
    work = Path(tempfile.mkdtemp(prefix="parasite-default-rift-"))
    try:
        target = build(game, skin, work / "Default Rift.fantome")
        from launcher import parasite_maps
        for old in parasite_maps.installed():
            if old["name"] == NAME:
                parasite_maps.delete(old["id"])
        parasite_maps.import_file(target, display_name=NAME)
        fresh = next((m for m in parasite_maps.installed() if m["name"] == NAME), None)
        if fresh is not None:
            parasite_maps.select(fresh["id"])
        return f"{NAME} kuruldu ve seçildi ({skin} yerine)"
    except DefaultRiftError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        log.warning(f"[DefaultRift] Could not build the default Rift: {e}")
        return "Varsayılan harita kurulamadı"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def catalog_item() -> dict:
    return {"id": CATALOG_ID, "name": NAME, "description": DESCRIPTION, "author": "Parasite",
            "preview": "", "build": True}
