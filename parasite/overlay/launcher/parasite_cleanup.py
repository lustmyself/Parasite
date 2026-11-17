"""Clean up what older Parasite versions left behind, once Parasite runs.

- Update packages, their `.ready` marks and the staging folder in Parasite's updates folder,
  except a newer package still waiting to be installed.
- Parasite plugins a newer Parasite no longer ships (updates only copy the plugins they have, so
  a retired one stayed in the client).
- Uninstall entries left by older installers (Parasite once had Rose's AppId): an entry named
  Parasite whose folder is this install is only a duplicate, so the entry goes; a Parasite copy
  in another folder goes with its entry when that folder holds Parasite.exe and no Rose.exe.
  Only the files Parasite's installer puts there are removed (`INSTALL_FILES`, `_internal`,
  Inno Setup's unins000.*), never anything else in the folder: an old copy may sit in a
  shared folder such as D:\\Games, and Parasite runs as administrator. The folder itself goes
  only when nothing else is left in it, and drive roots, Windows, Program Files, ProgramData
  and user profile folders are never touched.

Old uninstallers are never run: they delete %LOCALAPPDATA%\\Parasite (custom skins, mods,
settings) and turn Pengu Loader off, which would break the Parasite that is running.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import winreg
from pathlib import Path

from utils.core.logging import get_logger

log = get_logger()

OLD_APP_IDS = ("{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1",)
RETIRED_PLUGINS = ("PARASITE-PartyMode",)
UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def _version(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def clean_updates(updates_dir: Path, current: str) -> int:
    """Remove update packages at or below the running version, and the staging folder."""
    removed = 0
    if not updates_dir.is_dir():
        return 0
    staging = updates_dir / "staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
        removed += 1
    for path in updates_dir.iterdir():
        match = re.match(r"update_package_([0-9.]+)\.zip(\.ready|\.part)?$", path.name)
        if match and _version(match.group(1)) <= _version(current):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def clean_retired_plugins(plugins_dir: Path) -> int:
    """Remove Parasite's own plugins that Parasite no longer ships."""
    removed = 0
    for name in RETIRED_PLUGINS:
        folder = plugins_dir / name
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            if not folder.exists():
                removed += 1
                log.info(f"[Cleanup] Removed the retired plugin {name}")
    return removed


def _entries():
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        for app_id in OLD_APP_IDS:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{UNINSTALL}\\{app_id}", 0,
                                    winreg.KEY_READ | view) as key:
                    values = {}
                    for name in ("DisplayName", "InstallLocation"):
                        try:
                            values[name] = str(winreg.QueryValueEx(key, name)[0])
                        except OSError:
                            values[name] = ""
                yield view, app_id, values
            except OSError:
                continue


def _delete_entry(view: int, app_id: str) -> None:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL, 0, winreg.KEY_ALL_ACCESS | view) as key:
        winreg.DeleteKey(key, app_id)


# What a Parasite install folder holds (installer.iss copies PyInstaller's dist\Parasite:
# Parasite.exe and _internal; Inno Setup adds unins000.exe/.dat; updates keep icon.ico, see
# PERSISTENT_ROOT_FILES in launcher/update/update_installer.py)
INSTALL_FILES = ("Parasite.exe", "icon.ico")
INSTALL_DIRS = ("_internal",)
UNINSTALLER_FILE = re.compile(r"unins\d{3}\.(exe|dat|msg)$", re.IGNORECASE)
# What Parasite writes under injection\ in its folder (installer.iss [UninstallDelete])
INJECTION_DIRS = ("overlay", "mods")


def _key(path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).rstrip("\\/")


def _protected_roots() -> tuple[set[str], list[str]]:
    """Folders never cleaned, and folders nothing inside of which is cleaned."""
    exact, inside = set(), []
    for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "ALLUSERSPROFILE",
                 "USERPROFILE", "PUBLIC", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE"):
        if os.environ.get(name):
            exact.add(_key(os.environ[name]))
    for literal in (r"C:\Program Files", r"C:\Program Files (x86)", r"C:\ProgramData", r"C:\Users"):
        exact.add(_key(literal))
    profile = os.environ.get("USERPROFILE")
    if profile:
        exact.add(_key(Path(profile).parent))  # C:\Users
    try:
        exact.add(_key(Path.home()))
    except RuntimeError:
        pass
    for name in ("SystemRoot", "windir"):
        if os.environ.get(name):
            inside.append(_key(os.environ[name]))
    inside.append(_key(r"C:\Windows"))
    return exact, inside


def is_protected_folder(folder: Path) -> bool:
    """A drive or share root, Windows (or inside it), Program Files, ProgramData or a profile folder."""
    if not folder.is_absolute() or folder.parent == folder or len(folder.parts) <= 1:
        return True
    exact, inside = _protected_roots()
    key = _key(folder)
    if key in exact:
        return True
    return any(key == root or key.startswith((root + os.sep, root + "\\")) for root in inside)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(path)


def _remove_install_files(folder: Path) -> list[str]:
    """Remove only Parasite's own files from an old install folder; returns what is left there."""
    for name in INSTALL_FILES:
        path = folder / name
        if path.is_file() and not _is_link(path):
            path.unlink(missing_ok=True)
    for path in folder.iterdir():
        if UNINSTALLER_FILE.match(path.name) and path.is_file() and not _is_link(path):
            path.unlink(missing_ok=True)
    for name in INSTALL_DIRS:
        path = folder / name
        # PyInstaller's _internal of a Parasite (or Rose) build holds injection\
        if path.is_dir() and not _is_link(path) and (path / "injection").is_dir():
            shutil.rmtree(path, ignore_errors=True)
    injection = folder / "injection"
    if injection.is_dir() and not _is_link(injection):
        for name in INJECTION_DIRS:
            path = injection / name
            if path.is_dir() and not _is_link(path):
                shutil.rmtree(path, ignore_errors=True)
        try:
            injection.rmdir()  # only when empty
        except OSError:
            pass
    left = sorted(path.name for path in folder.iterdir())
    if not left:
        folder.rmdir()
    return left


def clean_old_installs(install_dir: Path) -> int:
    """Remove duplicate or stray installs left by Parasite's older installers. Returns how many."""
    removed = 0
    here = install_dir.resolve()
    for view, app_id, values in _entries():
        if values["DisplayName"].strip() != "Parasite":
            continue  # Rose's own entry, or something else: not ours
        folder = Path(values["InstallLocation"].strip().strip('"')) if values["InstallLocation"].strip() else None
        try:
            if folder and folder.exists() and folder.resolve() != here:
                folder = folder.resolve()
                if is_protected_folder(folder):
                    log.warning(f"[Cleanup] Left the old uninstall entry {app_id} alone: it points at {folder}")
                    continue
                if (folder / "Parasite.exe").is_file() and not (folder / "Rose.exe").exists():
                    left = _remove_install_files(folder)
                    if left:
                        log.info(f"[Cleanup] Removed an old Parasite copy's files in {folder}; "
                                 f"{len(left)} other item(s) stay there")
                    else:
                        log.info(f"[Cleanup] Removed an old Parasite copy in {folder}")
                else:
                    continue  # not plainly a Parasite copy: leave the folder and its entry alone
            _delete_entry(view, app_id)
            removed += 1
            log.info(f"[Cleanup] Removed the old uninstall entry {app_id}")
        except OSError as exc:
            log.warning(f"[Cleanup] Could not remove the old install {app_id}: {exc}")
    return removed


def run() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        from config import APP_VERSION, get_config_file_path
        removed = clean_updates(get_config_file_path().parent / "updates", APP_VERSION)
        install_dir = Path(sys.executable).resolve().parent
        from utils.core.paths import get_user_data_dir
        # The client loads plugins from the runtime copy in Parasite's data folder
        for plugins in (get_user_data_dir() / "Pengu Loader" / "plugins", install_dir / "Pengu Loader" / "plugins"):
            removed += clean_retired_plugins(plugins)
        removed += clean_old_installs(install_dir)
        if removed:
            log.info(f"[Cleanup] Removed {removed} leftover(s) of older Parasite versions")
    except Exception as exc:  # noqa: BLE001 - never in the way of Parasite
        log.warning(f"[Cleanup] Failed: {exc}")
