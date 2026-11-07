"""Start League through Parasite Offline, the chat proxy that lets you appear offline.

Parasite Offline (parasite/offline, a rebranded Deceive) must start the Riot Client itself
so it can route chat through its proxy. Parasite does that when it starts: a Riot
Client idling in the background is closed and restarted through the proxy, an
open game is left alone (closing it would be worse than appearing online), and
nothing starts when Parasite itself was started with Windows.

After that a watcher covers League opened the usual way while Parasite runs: a Riot
Client starting for League without the proxy (the League shortcut), or a League
client just started from a Riot Client that was already open, is closed at once
and started again through Parasite Offline. Other games are never touched.
"""

from __future__ import annotations

import ctypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import psutil
import pystray
import requests

from utils.core.logging import get_logger
from utils.core.paths import get_assets_dir

log = get_logger()

# Parasite's autostart runs at logon; don't open League by itself then.
BOOT_GRACE_MS = 3 * 60 * 1000
GAME_PROCESSES = {
    "leagueclient.exe",
    "leagueclientux.exe",
    "league of legends.exe",
    "valorant-win64-shipping.exe",
    "lor.exe",
    "parasiteoffline.exe",
}
RIOT_CLIENT_PROCESSES = {"riotclientservices.exe", "riot client.exe", "riotclientux.exe"}
LEAGUE_CLIENT_PROCESSES = {"leagueclient.exe", "leagueclientux.exe"}
WATCH_INTERVAL_S = 1.0
# A League client younger than this is still starting up and safe to restart.
FRESH_CLIENT_S = 20
RESTART_COOLDOWN_S = 30


def _processes(names):
    found = []
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() in names:
            found.append(proc)
    return found


def _started_at_logon() -> bool:
    """Start with Windows runs Parasite from Task Scheduler, whose host is svchost.exe."""
    try:
        parent = psutil.Process().parent()
        return bool(parent) and (parent.name() or "").lower() == "svchost.exe"
    except psutil.Error:
        return False


def _exe():
    return get_assets_dir().parent / "injection" / "tools" / "ParasiteOffline.exe"


def _close(names):
    procs = _processes(names)
    for proc in procs:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    psutil.wait_procs(procs, timeout=5)
    if procs:
        time.sleep(2)  # the Riot Client takes a moment to release its ports


# Parasite Offline points the Riot Client's chat at this name, which public DNS answers with
# 127.0.0.1. Some ISPs and routers (DNS rebinding protection) refuse such answers, and
# Parasite Offline then stops with "failing to resolve some required domains". Parasite runs as
# administrator, so it puts the name in the hosts file instead of making the player do it.
LOCALHOST_DOMAIN = "deceive-localhost.molenzwiebel.xyz"
HOSTS_ENTRY = f"127.0.0.1 {LOCALHOST_DOMAIN}"


def _hosts_file() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"


def _hosts_has_entry(text: str) -> bool:
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and fields[0] == "127.0.0.1" and LOCALHOST_DOMAIN in (f.lower() for f in fields[1:]):
            return True
    return False


def _resolves_to_loopback() -> bool:
    try:
        infos = socket.getaddrinfo(LOCALHOST_DOMAIN, None, socket.AF_INET)
    except OSError:
        return False
    return any(info[4][0] == "127.0.0.1" for info in infos)


def ensure_localhost_resolution() -> bool:
    """Make LOCALHOST_DOMAIN resolve to 127.0.0.1, adding a hosts entry when DNS won't."""
    hosts = _hosts_file()
    try:
        text = hosts.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if _hosts_has_entry(text) or _resolves_to_loopback():
        return True
    log.info(f"[ParasiteOffline] {LOCALHOST_DOMAIN} does not resolve to 127.0.0.1; adding it to the hosts file")
    try:
        if hosts.exists():
            os.chmod(hosts, 0o666)  # clears a read-only flag
        with open(hosts, "a", encoding="utf-8") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            f.write(f"{HOSTS_ENTRY}  # Parasite Offline\n")
    except OSError as exc:
        log.warning(f"[ParasiteOffline] Could not add {LOCALHOST_DOMAIN} to the hosts file: {exc}")
        return False
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass
    return True


# Parasite Offline reads its startup status from this file ("chat" is online).
STARTUP_STATUS_FILE = Path(os.environ.get("APPDATA", "")) / "Parasite Offline" / "startupStatus"


def start_online() -> None:
    """League opens online every time; the player can go offline or mobile from Parasite after."""
    try:
        STARTUP_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STARTUP_STATUS_FILE.write_text("chat", encoding="utf-8")
    except OSError as exc:
        log.warning(f"[ParasiteOffline] Could not set the startup status: {exc}")


def _start_unelevated(args) -> bool:
    """Start *args* as the desktop user, not as administrator.

    Parasite runs as administrator, and whatever it starts would too: the Riot Client
    and League would then run as administrator, and LTK Manager, which runs as the
    user, can't apply skins to that game. The process is created with the Windows
    shell (explorer.exe) as its parent, so it gets the shell's token, as LTF does
    for LTK Manager.
    """
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetShellWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_void_p, ctypes.c_void_p]
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
        ]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
        wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW),
        ctypes.POINTER(PROCESS_INFORMATION)]

    PROCESS_CREATE_PROCESS = 0x0080
    PROC_THREAD_ATTRIBUTE_PARENT_PROCESS = 0x00020000
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000

    shell = user32.GetShellWindow()
    pid = wintypes.DWORD()
    if not shell or not user32.GetWindowThreadProcessId(shell, ctypes.byref(pid)) or not pid.value:
        log.warning("[ParasiteOffline] No Windows shell to start Parasite Offline from")
        return False
    parent = kernel32.OpenProcess(PROCESS_CREATE_PROCESS, False, pid.value)
    if not parent:
        log.warning(f"[ParasiteOffline] Could not open the Windows shell (error {ctypes.get_last_error()})")
        return False
    try:
        size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = (ctypes.c_byte * size.value)()
        if not kernel32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
            return False
        try:
            parent_handle = wintypes.HANDLE(parent)
            if not kernel32.UpdateProcThreadAttribute(
                    attributes, 0, PROC_THREAD_ATTRIBUTE_PARENT_PROCESS, ctypes.byref(parent_handle),
                    ctypes.sizeof(parent_handle), None, None):
                return False
            info = STARTUPINFOEXW()
            info.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            info.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            process = PROCESS_INFORMATION()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(a) for a in args]))
            flags = (EXTENDED_STARTUPINFO_PRESENT | subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP)
            if not kernel32.CreateProcessW(None, command, None, None, False, flags, None,
                                           str(Path(args[0]).parent), ctypes.byref(info),
                                           ctypes.byref(process)):
                log.warning(f"[ParasiteOffline] Could not start Parasite Offline as the user "
                            f"(error {ctypes.get_last_error()})")
                return False
            kernel32.CloseHandle(process.hThread)
            kernel32.CloseHandle(process.hProcess)
            return True
        finally:
            kernel32.DeleteProcThreadAttributeList(attributes)
    finally:
        kernel32.CloseHandle(parent)


def _elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _launch(exe) -> bool:
    ensure_localhost_resolution()
    start_online()
    # League must not run as administrator: LTK Manager can't apply skins to it then
    if _elevated():
        try:
            if _start_unelevated([str(exe), "lol"]):
                log.info("[ParasiteOffline] Parasite Offline started as the user")
                return True
        except Exception as exc:  # noqa: BLE001
            log.warning(f"[ParasiteOffline] Could not start Parasite Offline as the user: {exc}")
        # Still open League (the watcher has just closed it), even if skins can't apply then
        log.warning("[ParasiteOffline] Starting Parasite Offline as administrator: League will "
                    "run as administrator, and LTK Manager can't apply skins to it then")
    try:
        subprocess.Popen(
            [str(exe), "lol"],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        return True
    except OSError as exc:
        log.warning(f"[ParasiteOffline] Could not start Parasite Offline: {exc}")
        return False


def league_without_proxy() -> bool:
    """League is starting through a Riot Client that doesn't route chat through Parasite Offline."""
    if _processes({"parasiteoffline.exe", "league of legends.exe"}):
        return False
    services = _processes({"riotclientservices.exe"})
    if not services:
        return False
    for proc in services:
        try:
            args = " ".join(proc.cmdline())
        except psutil.Error:
            continue
        if "--client-config-url" in args:
            return False
        if "--launch-product=league_of_legends" in args:
            return True
    # Play pressed in a Riot Client that was already open
    now = time.time()
    for proc in _processes(LEAGUE_CLIENT_PROCESSES):
        try:
            if now - proc.create_time() < FRESH_CLIENT_S:
                return True
        except psutil.Error:
            continue
    return False


def _watch(exe) -> None:
    while True:
        try:
            if league_without_proxy():
                log.info("[ParasiteOffline] League opened without Parasite Offline; restarting it through Parasite Offline")
                _close(LEAGUE_CLIENT_PROCESSES | RIOT_CLIENT_PROCESSES)
                if _launch(exe):
                    time.sleep(RESTART_COOLDOWN_S)
        except Exception as exc:  # keep watching whatever happens
            log.debug(f"[ParasiteOffline] Watch failed: {exc}")
        # Performance mode: during a match nobody opens League a second time, so look less often
        from launcher.parasite_perf import resting
        time.sleep(WATCH_INTERVAL_S * 5 if resting() else WATCH_INTERVAL_S)


# ---- Status (Parasite's tray menu) ----

# Parasite Offline takes commands as chat messages to its "Parasite Active!" friend and keeps
# the status it applies in this file ("chat" is online).
STATUS_FILE = Path(os.environ.get("APPDATA", "")) / "Parasite Offline" / "status"
PARASITE_OFFLINE_FRIEND = "41c322a1-b328-495b-a004-5ccd3e45eae8@eu1.pvp.net"
STATUSES = [("online", "Online"), ("offline", "Offline"), ("mobile", "Mobile")]


def parasite_offline_running() -> bool:
    return bool(_processes({"parasiteoffline.exe"}))


def _status_from_chat() -> str:
    """The status Parasite Offline last confirmed in its chat ("You are now appearing offline")."""
    creds = _lcu_credentials()
    if not creds:
        return ""
    port, token = creds
    url = f"https://127.0.0.1:{port}/lol-chat/v1/conversations/{quote(PARASITE_OFFLINE_FRIEND, safe='')}/messages"
    try:
        messages = requests.get(url, auth=("riot", token), verify=False, timeout=2,
                                proxies={"http": None, "https": None}).json()
    except (requests.RequestException, ValueError):
        return ""
    for message in reversed(messages if isinstance(messages, list) else []):
        match = re.search(r"appearing (online|offline|mobile)", str(message.get("body", "")), re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


def current_status() -> str:
    # Parasite Offline writes its status file only now and then, so its chat comes first
    status = _status_from_chat()
    if status:
        return status
    try:
        status = STATUS_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return "online" if status == "chat" else status


def _lcu_credentials():
    """App port and token from the League client's command line. Never log the token."""
    for proc in _processes({"leagueclientux.exe"}):
        try:
            args = proc.cmdline()
        except psutil.Error:
            continue
        options = dict(arg.split("=", 1) for arg in args if arg.startswith("--") and "=" in arg)
        port, token = options.get("--app-port", ""), options.get("--remoting-auth-token", "")
        if port.isdecimal() and token:
            return int(port), token
    return None


def set_status(command: str) -> bool:
    creds = _lcu_credentials()
    if not creds:
        return False
    port, token = creds
    url = f"https://127.0.0.1:{port}/lol-chat/v1/conversations/{quote(PARASITE_OFFLINE_FRIEND, safe='')}/messages"
    try:
        response = requests.post(url, json={"body": command, "type": "chat"}, auth=("riot", token),
                                 verify=False, timeout=3, proxies={"http": None, "https": None})
        return response.ok
    except requests.RequestException as exc:
        log.warning(f"[ParasiteOffline] Could not change status: {exc}")
        return False


def tray_status_menu() -> pystray.Menu:
    """Online / Offline / Mobile for Parasite's tray icon (Parasite Offline's own is hidden)."""
    def item(command, label):
        return pystray.MenuItem(
            label,
            lambda icon, menu_item: set_status(command),
            checked=lambda menu_item: parasite_offline_running() and current_status() == command,
            radio=True,
            enabled=lambda menu_item: parasite_offline_running(),
        )

    return pystray.Menu(
        *(item(command, label) for command, label in STATUSES),
        pystray.MenuItem(
            "League wasn't started through Parasite",
            None,
            enabled=False,
            visible=lambda menu_item: not parasite_offline_running(),
        ),
    )


def start_league_through_parasite_offline() -> None:
    if sys.platform != "win32":
        return
    exe = _exe()
    if not exe.exists():
        log.warning(f"[ParasiteOffline] {exe} is missing; League is not started")
        return
    threading.Thread(target=_watch, args=(exe,), daemon=True, name="ParasiteOfflineWatch").start()

    uptime = ctypes.windll.kernel32.GetTickCount64
    uptime.restype = ctypes.c_ulonglong
    if uptime() < BOOT_GRACE_MS or _started_at_logon():
        log.info("[ParasiteOffline] Started with Windows; leaving League closed")
        return
    from launcher.parasite_settings import enabled
    if not enabled("launch_league"):
        log.info("[ParasiteOffline] Opening League with Parasite is off in the hub's settings")
        return
    games = _processes(GAME_PROCESSES)
    if games:
        log.info(f"[ParasiteOffline] {games[0].info['name']} is already running; not restarting it")
        return
    _close(RIOT_CLIENT_PROCESSES)
    if _launch(exe):
        log.info("[ParasiteOffline] Started League through Parasite Offline")
