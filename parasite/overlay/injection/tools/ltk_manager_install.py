"""Find or install LTK Manager for the user.

Parasite applies skins through LTK Manager (LeagueToolkit, GPL-3.0). Parasite does
not ship it: when it is missing, Parasite downloads the official, signed installer
from LTK Manager's latest GitHub release, checks its signature and runs it. The
installer puts LTK Manager in Program Files, so Windows asks for administrator
rights once (UAC prompt).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from utils.core.logging import get_logger

log = get_logger()

# LTK Manager's release workflow uploads its installer under this fixed name to every
# stable release, so this always points at the newest one
INSTALLER_URL = (
    "https://github.com/LeagueToolkit/ltk-manager/releases/latest/download/LTK.Manager_x64-setup.exe"
)
MAX_INSTALLER_BYTES = 300 * 1024 * 1024
INSTALL_TIMEOUT_S = 600
CREATE_NO_WINDOW = 0x08000000
EXECUTABLES = ("ltk-manager.exe", "LTK Manager.exe")


def registered_ltk_manager() -> Optional[Path]:
    """LTK Manager's executable from Windows' installed programs list, wherever it was installed."""
    if sys.platform != "win32":
        return None
    import winreg

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in roots:
        try:
            uninstall = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with uninstall:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(uninstall, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(uninstall, name) as entry:
                        display = _reg_value(winreg, entry, "DisplayName")
                        if (display or "").strip().lower() != "ltk manager":
                            continue
                        dirs = [_reg_value(winreg, entry, "InstallLocation")]
                        icon = _reg_value(winreg, entry, "DisplayIcon")
                        uninstaller = _reg_value(winreg, entry, "UninstallString")
                        for value in (icon, uninstaller):
                            if value:
                                dirs.append(str(Path(value.split(",")[0].strip().strip('"')).parent))
                except OSError:
                    continue
                for directory in filter(None, dirs):
                    for exe in EXECUTABLES:
                        candidate = Path(directory.strip().strip('"')) / exe
                        if candidate.is_file():
                            return candidate
    return None


def _reg_value(winreg, key, name) -> Optional[str]:
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def download_installer(dest: Path, timeout: int = 60) -> bool:
    """Download LTK Manager's installer to *dest*."""
    import requests

    from config import APP_USER_AGENT

    size = 0
    with requests.get(INSTALLER_URL, stream=True, timeout=timeout,
                      headers={"User-Agent": APP_USER_AGENT}) as response:
        response.raise_for_status()
        with open(dest, "wb") as out:
            for chunk in response.iter_content(1 << 16):
                size += len(chunk)
                if size > MAX_INSTALLER_BYTES:
                    raise ValueError("the LTK Manager installer is larger than expected")
                out.write(chunk)
    return size > 0


def signature_is_valid(path: Path) -> bool:
    """Whether Windows reports a valid Authenticode signature on *path*."""
    script = "(Get-AuthenticodeSignature -LiteralPath $env:PARASITE_LTK_SETUP).Status.ToString()"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW,
            env={**os.environ, "PARASITE_LTK_SETUP": str(path)},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning(f"[LTK] Could not check the installer's signature: {exc}")
        return False
    status = (result.stdout or "").strip()
    if status != "Valid":
        log.warning(f"[LTK] The LTK Manager installer's signature is not valid: {status or result.stderr.strip()}")
        return False
    return True


def run_installer_elevated(path: Path) -> Optional[int]:
    """Run the installer silently as administrator and wait for it.

    Returns its exit code, or None when the user declined the UAC prompt or it could not start.
    """
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x40
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(path)
    info.lpParameters = "/S"
    info.nShow = 0
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        log.warning(f"[LTK] The LTK Manager installer did not start (error {ctypes.GetLastError()})")
        return None
    try:
        kernel32.WaitForSingleObject(info.hProcess, INSTALL_TIMEOUT_S * 1000)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def _running_manager_pids() -> set[int]:
    try:
        import psutil
    except ImportError:
        return set()
    names = {name.lower() for name in EXECUTABLES}
    pids = set()
    for proc in psutil.process_iter(["name", "pid"]):
        if (proc.info.get("name") or "").lower() in names:
            pids.add(proc.info["pid"])
    return pids


def _close_started_manager(before: set[int]) -> None:
    """Close an LTK Manager the installer opened: Parasite starts its own during champ select."""
    started = _running_manager_pids() - before
    if not started:
        return
    import psutil

    for pid in started:
        try:
            psutil.Process(pid).terminate()
            log.info(f"[LTK] Closed the LTK Manager the installer opened (pid {pid})")
        except psutil.Error:
            pass


def install_ltk_manager(detect: Callable[[], Optional[Path]]) -> Optional[Path]:
    """Download and install LTK Manager; returns where *detect* finds it afterwards, or None."""
    if sys.platform != "win32":
        return None
    workdir = Path(tempfile.mkdtemp(prefix="parasite-ltk-"))
    setup = workdir / "LTK.Manager_x64-setup.exe"
    try:
        log.info(f"[LTK] LTK Manager is missing - downloading it from {INSTALLER_URL}")
        try:
            if not download_installer(setup):
                return None
        except Exception as exc:
            log.warning(f"[LTK] Could not download LTK Manager: {exc}")
            return None
        if not signature_is_valid(setup):
            return None
        before = _running_manager_pids()
        code = run_installer_elevated(setup)
        if code is None:
            return None
        if code != 0:
            log.warning(f"[LTK] The LTK Manager installer ended with code {code}")
        deadline = time.monotonic() + 15
        found = None
        while time.monotonic() < deadline:
            found = detect() or registered_ltk_manager()
            if found is not None:
                break
            time.sleep(1)
        time.sleep(2)
        _close_started_manager(before)
        if found is None:
            log.warning("[LTK] LTK Manager was installed but Parasite can't find it")
        else:
            log.info(f"[LTK] LTK Manager installed at {found}")
        return found
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
