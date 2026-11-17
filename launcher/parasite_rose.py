"""Rose installed next to Parasite: both register their Pengu Loader for League in the same
place, so with Rose running the client loads Rose's plugins too (its rose icon beside PARASITE).

While Parasite runs it keeps Rose out of the way without touching Rose's files or settings:
a running Rose is closed, and when the League hook runs Rose's Pengu Loader, Parasite puts
its own back. The desktop hub also offers Rose's own uninstaller, which opens visibly
and asks the player; Parasite never removes another program by itself.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import winreg
from pathlib import Path
from typing import Optional

import psutil

from utils.core.logging import get_logger

log = get_logger()

UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def _registry_entries() -> list[dict]:
    """Rose's entries in Windows' installed programs: their UninstallString and InstallLocation."""
    entries = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0, winreg.KEY_READ | view) as root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                            if winreg.QueryValueEx(key, "DisplayName")[0] != "Rose":
                                continue
                            values = {}
                            for name in ("UninstallString", "InstallLocation"):
                                try:
                                    values[name] = str(winreg.QueryValueEx(key, name)[0])
                                except OSError:
                                    values[name] = ""
                    except OSError:
                        continue
                    entries.append(values)
        except OSError:
            continue
    return entries


def _uninstaller_from_registry() -> Optional[Path]:
    for values in _registry_entries():
        command = values.get("UninstallString", "")
        if not command:
            continue
        path = Path(command.strip().strip('"'))
        if path.is_file():
            return path
    return None


def _folder() -> Optional[Path]:
    folder = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Rose"
    return folder if (folder / "Rose.exe").is_file() else None


def _rose_dirs() -> set[str]:
    """Folders Rose is installed in: from its uninstall entries, and Rose's default folder."""
    dirs = set()
    for values in _registry_entries():
        location = values.get("InstallLocation", "").strip().strip('"')
        if location:
            dirs.add(_key(location))
        command = values.get("UninstallString", "").strip().strip('"')
        if command:
            dirs.add(_key(Path(command).parent))
    for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        if os.environ.get(name):
            dirs.add(_key(Path(os.environ[name]) / "Rose"))
    dirs.add(_key(r"C:\Program Files\Rose"))
    dirs.discard("")
    return dirs


def _key(path) -> str:
    text = str(path).strip()
    return os.path.normcase(os.path.normpath(text)).rstrip("\\/") if text else ""


def _rose_processes() -> list:
    """Running Rose.exe processes started from a Rose install, not any program named rose.exe."""
    dirs = None
    found = []
    for proc in psutil.process_iter(["name", "exe"]):
        if (proc.info.get("name") or "").lower() != "rose.exe":
            continue
        exe = proc.info.get("exe") or ""
        if not exe:
            continue  # its path can't be read: not plainly Rose, leave it
        if dirs is None:
            dirs = _rose_dirs()
        if _key(Path(exe).parent) in dirs:
            found.append(proc)
    return found


def status() -> dict:
    running = bool(_rose_processes())
    uninstaller = _uninstaller_from_registry()
    folder = _folder()
    if not uninstaller and folder and (folder / "unins000.exe").is_file():
        uninstaller = folder / "unins000.exe"
    return {"installed": bool(uninstaller or folder), "running": running, "can_uninstall": bool(uninstaller)}


def uninstall() -> str:
    """Close Rose and open its own uninstaller. Returns the message for the hub."""
    current = status()
    if not current["installed"]:
        return "Rose kurulu değil"
    _close_rose()
    uninstaller = _uninstaller_from_registry()
    folder = _folder()
    if not uninstaller and folder and (folder / "unins000.exe").is_file():
        uninstaller = folder / "unins000.exe"
    if not uninstaller:
        return "Rose kapatıldı; kaldırmak için Windows Ayarlar > Uygulamalar'dan Rose'u kaldır"
    try:
        subprocess.Popen([str(uninstaller)], close_fds=True)
    except OSError as exc:
        log.warning(f"[Rose] Could not open Rose's uninstaller: {exc}")
        return "Rose'un kaldırıcısı açılamadı"
    log.info(f"[Rose] Opened Rose's uninstaller: {uninstaller}")
    return "Rose'un kaldırıcısı açıldı: onaylayınca Rose kaldırılır, sonra League'i yeniden başlat"


GUARD_INTERVAL_S = 30
_guard_started = False


def _close_rose() -> bool:
    """Close Rose: only a Rose.exe running from where Rose is installed (see `_rose_processes`)."""
    closed = False
    for proc in _rose_processes():
        try:
            proc.terminate()
            closed = True
        except psutil.Error:
            pass
    return closed


def _take_back_hook() -> bool:
    """The League hook runs Rose's Pengu Loader: put Parasite's back (used from the next client start)."""
    from utils.integration import pengu_loader
    other = pengu_loader._hook_of_another_loader()
    if other is None or "rose" not in {part.lower() for part in other.parts}:
        return False
    log.info(f"[Rose] The League hook ran Rose's loader ({other}); switching it back to Parasite's")
    return pengu_loader.activate()


def keep_rose_off() -> None:
    """Close Rose and keep the League hook Parasite's, while Parasite runs."""
    global _guard_started
    if _guard_started:
        return
    _guard_started = True

    def guard():
        told = False
        while True:
            try:
                from launcher.parasite_settings import enabled
                from launcher.parasite_perf import resting
                if not enabled("rose_guard") or resting():
                    time.sleep(GUARD_INTERVAL_S)
                    continue
                closed = _close_rose()
                took = _take_back_hook()
                if (closed or took) and not told:
                    told = True
                    log.info("[Rose] Rose was running next to Parasite; it was closed")
                    from launcher import parasite_hub
                    parasite_hub.toast("Rose kapatıldı: Parasite ile aynı anda çalışınca çakışıyor")
            except Exception as exc:  # noqa: BLE001
                log.debug(f"[Rose] Guard failed: {exc}")
            time.sleep(GUARD_INTERVAL_S)

    threading.Thread(target=guard, daemon=True, name="ParasiteRoseGuard").start()
