#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where League of Legends is installed, for features that run while League is closed.

Rose's GameDetector reads leaguePath from cf.ini, else the running LeagueClient.exe. The
default Rift is built from the hub, often with League closed, and a fresh install has no
leaguePath yet. This also looks where the Riot Client records League (RiotClientInstalls.json,
the product settings in ProgramData, the uninstall entry in the registry), at a running game,
and in the usual folders of every fixed drive. When nothing turns it up the player picks
LeagueClient.exe or League of Legends.exe. What is found is saved as leaguePath and clientPath.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from utils.core.logging import get_logger

log = get_logger()

GAME_EXES = ("League of Legends.exe", "League of Legends (TM) Client.exe")
PRODUCT = "league_of_legends.live"
# Folders (under a drive) League is usually installed in
COMMON_FOLDERS = (
    "Riot Games/League of Legends",
    "Program Files/Riot Games/League of Legends",
    "Program Files (x86)/Riot Games/League of Legends",
    "Games/Riot Games/League of Legends",
    "Games/League of Legends",
    "Oyunlar/Riot Games/League of Legends",
    "Oyunlar/League of Legends",
    "League of Legends",
)
INSTALL_PATH_LINE = re.compile(r"""^\s*product_install_full_path\s*:\s*["']?(.+?)["']?\s*$""", re.MULTILINE)
PICK_TITLE = "Parasite - League'i seç (LeagueClient.exe)"


def _has_game(folder: Path) -> bool:
    return any((folder / name).is_file() for name in GAME_EXES)


def game_dir_of(path) -> Optional[Path]:
    """The Game folder (the one holding League of Legends.exe) of *path*: League's install
    folder, its Game folder, or a file in either (LeagueClient.exe, League of Legends.exe)."""
    if not path:
        return None
    try:
        folder = Path(str(path).strip().strip('"'))
        if folder.is_file():
            folder = folder.parent
        for candidate in (folder, folder / "Game", folder.parent / "Game"):
            if _has_game(candidate):
                return candidate
    except (OSError, ValueError):
        pass
    return None


# ---- where the Riot Client says League is ----

def _program_data() -> Path:
    return Path(os.environ.get("ProgramData") or r"C:\ProgramData")


def from_riot_installs(path: Optional[Path] = None) -> List[str]:
    """The install folders RiotClientInstalls.json links to a game (League's among them)."""
    path = path or _program_data() / "Riot Games" / "RiotClientInstalls.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    found = []
    clients = data.get("associated_client") if isinstance(data, dict) else None
    if isinstance(clients, dict):
        found += [key for key in clients if isinstance(key, str)]
    return found


def from_product_settings(path: Optional[Path] = None) -> List[str]:
    """product_install_full_path of League's product settings (Riot Client metadata)."""
    path = path or (_program_data() / "Riot Games" / "Metadata" / PRODUCT / f"{PRODUCT}.product_settings.yaml")
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return [m.group(1) for m in INSTALL_PATH_LINE.finditer(text)]


def from_registry() -> List[str]:
    """InstallLocation of League's uninstall entry."""
    if sys.platform != "win32":
        return []
    import winreg
    found = []
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game {PRODUCT}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    value, _kind = winreg.QueryValueEx(key, "InstallLocation")
                    if isinstance(value, str) and value:
                        found.append(value)
            except OSError:
                continue
    return found


def from_processes() -> List[str]:
    """The folders of a running LeagueClient or game."""
    try:
        import psutil
    except ImportError:
        return []
    wanted = {"leagueclient.exe", "leagueclientux.exe"} | {name.lower() for name in GAME_EXES}
    found = []
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            if (proc.info.get("name") or "").lower() in wanted and proc.info.get("exe"):
                found.append(proc.info["exe"])
        except (psutil.Error, OSError):
            continue
    return found


def fixed_drives() -> List[str]:
    """The roots of the computer's local disks (C:\\, D:\\...), not network or removable ones."""
    if sys.platform != "win32":
        return []
    import ctypes
    import string
    drives = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for index, letter in enumerate(string.ascii_uppercase):
        root = f"{letter}:\\"
        if mask & (1 << index) and ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
            drives.append(root)
    return drives


def from_drives(drives: Optional[Iterable[str]] = None) -> List[str]:
    return [str(Path(root, *folder.split("/"))) for root in (fixed_drives() if drives is None else drives)
            for folder in COMMON_FOLDERS]


def _configured() -> Optional[Path]:
    """leaguePath / the running client, as Rose finds them."""
    try:
        from injection.config.config_manager import ConfigManager
        from injection.game.game_detector import GameDetector
        found = GameDetector(ConfigManager()).detect_game_dir()
    except Exception as e:  # noqa: BLE001
        log.debug(f"[LeaguePath] Rose's detector failed: {e}")
        return None
    return game_dir_of(found)


def candidates() -> Iterator[str]:
    for source in (from_processes, from_riot_installs, from_product_settings, from_registry, from_drives):
        try:
            yield from source()
        except Exception as e:  # noqa: BLE001
            log.debug(f"[LeaguePath] {source.__name__} failed: {e}")


def remember(game: Path) -> None:
    """Save *game* as leaguePath (and its client folder as clientPath) in cf.ini."""
    try:
        from injection.config.config_manager import ConfigManager
        manager = ConfigManager()
        client = manager.infer_client_path_from_league_path(str(game))
        if client:
            manager.save_paths(str(game), client)
        else:
            manager.save_league_path(str(game))
    except Exception as e:  # noqa: BLE001
        log.debug(f"[LeaguePath] Could not save {game}: {e}")


def find_game_dir() -> Optional[Path]:
    """League's Game folder: from cf.ini or the running client, else from where the Riot Client
    records it or the usual folders (then saved for next time)."""
    game = _configured()
    if game is not None:
        return game
    for candidate in candidates():
        game = game_dir_of(candidate)
        if game is not None:
            log.info(f"[LeaguePath] Found League at {game}")
            remember(game)
            return game
    log.info("[LeaguePath] League not found")
    return None


# ---- the player picks it ----

def _bring_to_front(title: str, timeout: float = 5.0) -> None:
    """Put the picker above the hub (it opens from a background thread, often behind it)."""
    import ctypes
    user32 = ctypes.windll.user32
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hwnd = user32.FindWindowW("#32770", title)
        if hwnd:
            # HWND_TOPMOST, SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetForegroundWindow(hwnd)
            return
        time.sleep(0.05)


def _pick_file() -> Optional[Path]:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR), ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD), ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR), ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR), ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR), ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD), ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM), ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR), ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD),
        ]

    file_filter = ctypes.create_unicode_buffer(
        "League of Legends (LeagueClient.exe, League of Legends.exe)\0"
        "LeagueClient.exe;League of Legends.exe\0Programlar (*.exe)\0*.exe\0\0")
    file_buffer = ctypes.create_unicode_buffer(1024)
    title = ctypes.create_unicode_buffer(PICK_TITLE)
    drives = fixed_drives()
    dialog = OpenFileName(
        lStructSize=ctypes.sizeof(OpenFileName),
        lpstrFilter=ctypes.cast(file_filter, wintypes.LPCWSTR),
        nFilterIndex=1,
        lpstrFile=ctypes.cast(file_buffer, wintypes.LPWSTR),
        nMaxFile=len(file_buffer),
        lpstrInitialDir=drives[0] if drives else None,
        lpstrTitle=ctypes.cast(title, wintypes.LPCWSTR),
        # OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER | OFN_DONTADDTORECENT
        Flags=0x1000 | 0x0800 | 0x0008 | 0x00080000 | 0x02000000,
    )
    initialized = ctypes.windll.ole32.CoInitializeEx(None, 0x2) in (0, 1)  # COINIT_APARTMENTTHREADED
    threading.Thread(target=_bring_to_front, args=(PICK_TITLE,), daemon=True).start()
    try:
        picked = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog))
    except (AttributeError, OSError, ctypes.ArgumentError) as e:
        log.warning(f"[LeaguePath] Could not open the file picker: {e}")
        return None
    finally:
        if initialized:
            ctypes.windll.ole32.CoUninitialize()
    return Path(file_buffer.value) if picked and file_buffer.value else None


class NotPicked(Exception):
    """The player closed the picker (the message is theirs, in Turkish)."""


def ask(picker=None) -> Path:
    """League's Game folder from the file the player picks (saved for next time)."""
    picked = (picker or _pick_file)()
    if picked is None:
        raise NotPicked("League bulunamadı ve klasör seçilmedi. Tekrar Kur'a bas ve "
                        "League of Legends klasöründeki LeagueClient.exe dosyasını seç.")
    game = game_dir_of(picked)
    if game is None:
        raise NotPicked(f"Seçtiğin yerde League yok ({picked}). League of Legends klasöründeki "
                        "LeagueClient.exe dosyasını seç.")
    log.info(f"[LeaguePath] The player picked League at {game}")
    remember(game)
    return game
