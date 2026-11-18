#!/usr/bin/env python3
"""
Rebuild the Parasite source tree from a Rose release.

    python parasite/sync.py <rose-git-ref>

Run from the repository root. Every tracked file outside .github/ and parasite/
is replaced by the Rose tree at <rose-git-ref>, then:

1. Rose -> Parasite in file contents and paths (real external service URLs kept)
2. Rose's GitHub repo links -> Parasite's repo (updates, installer, README)
3. the "Rose" labels inside the prebuilt Pengu Loader core.dll -> "Parasite"
4. parasite/overlay/ is copied on top (Kai'Sa icons, lobby reveal)
5. EDITS below are applied to Rose files Parasite changes
6. Turkish texts (parasite/turkish.py) replace the English ones players see

Any step that no longer fits Rose's code fails loudly instead of guessing.
"""

import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from turkish import LOCALE_TR, apply_turkish  # parasite/turkish.py: Parasite is Turkish only

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "parasite" / "overlay"
KEEP = {".github", "parasite"}  # Parasite's own; never taken from Rose

PARASITE_REPO = "lustmyself/Parasite"

# Real external services: renaming them would only produce dead links.
URL_RE = re.compile(r"https?://[^\s\"'<>)`\]]+")
LOCAL_URL_PREFIXES = ("http://127.0.0.1", "https://plugins/", "http://localhost")
# Indonesian "process" is not the brand; bare Discord invites (no https://) are real links
KEEP_WORDS = re.compile(r"\b(proses\w*|discord\.gg/[\w-]+|discord\.com/invite/[\w-]+)")
REPO_LINK_RE = re.compile(r"Alban1911/Rose(?![-A-Za-z])")
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".ttf", ".otf", ".woff", ".woff2",
    ".ogg", ".mp3", ".wav", ".exe", ".dll", ".pdb", ".zip", ".7z", ".bin", ".wad",
}
DLL_LABELS = [b'legend:"Rose"', b'>Rose</h3>', b'content:"Rose"']


def swap(s):
    return s.replace("ROSE", "PARASITE").replace("Rose", "Parasite").replace("rose", "parasite")


def rebrand_text(text):
    # Point repo links at Parasite first, so bare ones (no https://) keep the owner
    text = REPO_LINK_RE.sub(PARASITE_REPO, text)
    pieces, pos = [], 0
    for m in URL_RE.finditer(text):
        pieces.append((False, text[pos:m.start()]))
        url = m.group()
        pieces.append((True, swap(url) if url.startswith(LOCAL_URL_PREFIXES) else url))
        pos = m.end()
    pieces.append((False, text[pos:]))
    out = []
    for is_url, chunk in pieces:
        if is_url:
            out.append(chunk)
            continue
        parts = KEEP_WORDS.split(chunk)
        out.append("".join(p if i % 2 else swap(p) for i, p in enumerate(parts)))
    # core.dll reads %LOCALAPPDATA%\\Parasite\\cf.ini (see patch_core_dll)
    # The loading screen's name record must keep the game key's length
    # (game_character_displayname_), so Parasite's own key uses a 4-letter prefix
    # Rose's skin packs (Parasite downloads the same ones) list the game sound banks a skin
    # needs in META/rose_sounds.json: renamed, Parasite never found them and skins played silent
    return (REPO_LINK_RE.sub(PARASITE_REPO, "".join(out)).replace("config.ini", "cf.ini")
            .replace("parasite_character_displayname_", "prst_character_displayname_")
            .replace("parasite_sounds.json", "rose_sounds.json"))


def read_text(path):
    if path.suffix.lower() in BINARY_EXT:
        return None
    raw = path.read_bytes()
    if b"\0" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def write_text(path, text):
    path.write_bytes(text.encode("utf-8"))


def extract_rose(ref, dest):
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=ROOT,
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")


def rebrand_tree(tree):
    for path in tree.rglob("*"):
        if path.is_file() and path.name != "LICENSE":  # MIT: keep the copyright notice
            text = read_text(path)
            if text is not None:
                new = rebrand_text(text)
                if new != text:
                    write_text(path, new)
    # Rename deepest paths first so parents still exist
    for path in sorted(tree.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if re.search("rose", path.name, re.I):
            path.rename(path.with_name(swap(path.name)))


def _same_length(data, old, new, what, count=1):
    """Replace old with new (padded with spaces to old's length) exactly `count` times."""
    if len(new) > len(old):
        raise SystemExit(f"[sync] core.dll patch for {what} is longer than the original")
    new = new + (b" " if isinstance(new, bytes) else " ") * (len(old) - len(new))
    if data.count(old) != count:
        raise SystemExit(f"[sync] core.dll: {what} found {data.count(old)} times, expected {count}")
    return data.replace(old, new)


def _utf16(text):
    return text.encode("utf-16-le")


def patch_core_dll(tree):
    """Make Rose's prebuilt core.dll Parasite's. Every patch keeps the byte length.

    "Parasite" is twice as long as "Rose", so names can't simply be swapped:
    - %LOCALAPPDATA%\\Rose\\config.ini, where core.dll finds the plugins folder, becomes
      %LOCALAPPDATA%\\Parasite\\cf.ini (same 16 characters); Parasite keeps its settings in cf.ini
    - core.dll's own log folder %LOCALAPPDATA%\\Rose becomes %LOCALAPPDATA%\\Temp
    - the welcome popup ("Rose ... your League is now Unlocked!") is hidden entirely
    - the loading screen shows nothing (no rose icon, no name)
    """
    dll = tree / "Pengu Loader" / "core.dll"
    if not dll.exists():
        print("[sync] note: no prebuilt core.dll")
        return
    data = dll.read_bytes()
    # UTF-16: config path first, then the remaining log folder and version info
    data = _same_length(data, _utf16("\\Rose\\config.ini"), _utf16("\\Parasite\\cf.ini"), "the config.ini path")
    data = _same_length(data, _utf16("Rose Loader core module"), _utf16("Parasite core module"), "the file description")
    data = _same_length(data, _utf16("Rose Loader"), _utf16("Parasite"), "the product name")
    data = _same_length(data, _utf16("\\Rose"), _utf16("\\Temp"), "the log folder")
    data = _same_length(data, _utf16("ROSE"), _utf16("PRST"), "the company name")
    if _utf16("Rose") in data or _utf16("ROSE") in data:
        raise SystemExit("[sync] core.dll still has a UTF-16 Rose string")
    data = patch_loading_screen(data)
    data = patch_welcome_popup(data)
    # Command palette entry: "Parasite", opening Parasite's GitHub
    data = _same_length(
        data,
        b'legend:"Rose",perform:()=>window.open("https://github.com/Alban1911/Rose","_blank")',
        b'legend:"Parasite",perform:()=>window.open("https://github.com/lustmyself/Parasite")',
        "the command palette entry")
    data = _same_length(data, b">Rose</h3>", b"></h3>", "the popup title")
    data = _same_length(data, b"\\ROSE-Pengu\\", b"\\PRST-Pengu\\", "the debug path")
    dll.write_bytes(data)


# The client's loading screen: a round image (League's rose profile icon) over "ROSE"
LOADING_CSS = (
    b'div[id^=index_loading_div]:before{content:"";'
    b'background-image:url(/lol-game-data/assets/v1/profile-icons/7.jpg);'
    b'background-repeat:no-repeat;background-size:cover;width:144px;height:144px;border-radius:50%}'
    b'div[id^=index_loading_div]:after{margin-top:32px;content:"Rose";color:#e2e1e1;'
    b'font-family:Inter,sans-serif;font-size:1rem;text-transform:uppercase}'
)
# Nothing on it: no image and no text while the client loads (at login and after a match)
EMPTY_LOADING_CSS = b'div[id^=index_loading_div]:before,div[id^=index_loading_div]:after{display:none}'


def patch_loading_screen(data):
    if data.count(LOADING_CSS) != 1:
        raise SystemExit("[sync] the client loading screen CSS changed in core.dll")
    padding = len(LOADING_CSS) - len(EMPTY_LOADING_CSS)
    if padding < 0:
        raise SystemExit("[sync] the empty loading screen CSS is longer than the original")
    return data.replace(LOADING_CSS, EMPTY_LOADING_CSS + b" " * padding)


POPUP_ICON = ROOT / "parasite" / "assets" / "popup_icon.jpg"
POPUP_IMAGE_RE = re.compile(rb"data:image/jpeg;base64,([A-Za-z0-9+/]+=*)")
POPUP_BADGES = b'class="flex mt-5 space-x-1"'  # Discord / Ko-fi / GitHub badges
POPUP_ROOT = b'class="z-10 relative"'  # the welcome dialog and its dark backdrop


def jpeg_base64_of_length(jpeg, length):
    """Base64 of jpeg, padded with a JPEG comment segment to exactly `length` chars."""
    import base64
    target = length // 4 * 3  # bytes that encode to `length` chars without "="
    filler = target - len(jpeg) - 4  # COM marker + 2 length bytes
    if length % 4 or not 0 <= filler <= 65533:
        raise SystemExit(f"[sync] popup icon cannot be fitted into {length} base64 chars")
    comment = b"\xff\xfe" + (filler + 2).to_bytes(2, "big") + b" " * filler
    encoded = base64.b64encode(jpeg[:2] + comment + jpeg[2:])  # right after SOI
    assert len(encoded) == length
    return encoded


def patch_welcome_popup(data):
    """Kai'Sa instead of the rose in Pengu's welcome popup, without the badges.
    Every replacement keeps the byte length, so the DLL layout is untouched."""
    images = list(POPUP_IMAGE_RE.finditer(data))
    if len(images) != 1:
        raise SystemExit(f"[sync] expected one embedded JPEG in core.dll, found {len(images)}")
    start, end = images[0].span(1)
    data = data[:start] + jpeg_base64_of_length(POPUP_ICON.read_bytes(), end - start) + data[end:]

    if data.count(POPUP_BADGES) != 1:
        raise SystemExit("[sync] welcome popup badges not found in core.dll")
    hidden = b'style="display:none"'
    data = data.replace(POPUP_BADGES, hidden + b" " * (len(POPUP_BADGES) - len(hidden)))
    # Parasite has no Discord or Ko-fi: their links in the (hidden) popup lead nowhere
    data = _same_length(data, b"href=https://discord.gg/roseskins", b"href=#", "the popup's Discord link")
    data = _same_length(data, b"href=https://ko-fi.com/roseapp", b"href=#", "the popup's Ko-fi link")
    # Parasite: no welcome popup at all, its whole dialog stays hidden
    return _same_length(data, POPUP_ROOT, hidden, "the welcome popup")


OFFLINE_LICENSE = ROOT / "parasite" / "offline" / "src" / "LICENSE"


def copy_overlay(tree):
    for src in OVERLAY.rglob("*"):
        if src.is_file():
            dst = tree / src.relative_to(OVERLAY)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    # ParasiteOffline.exe is Deceive (GPL-3.0): its license ships next to it, with
    # ParasiteOffline-NOTICE.txt (overlay) saying where its source is
    if not OFFLINE_LICENSE.is_file():
        raise SystemExit("[sync] parasite/offline/src/LICENSE is missing (Parasite Offline is GPL-3.0)")
    shutil.copyfile(OFFLINE_LICENSE, tree / "injection" / "tools" / "ParasiteOffline-LICENSE.txt")


UI_JS = "Pengu Loader/plugins/PARASITE-UI/index.js"
NAV_CSS = r"""    /* The nav item shows the word PARASITE where Rose had its golden rose */
    lol-uikit-navigation-item.menu_item_Golden\\ Parasite .menu-item-icon-wrapper {
      width: auto;
      padding: 0 6px;
    }

    lol-uikit-navigation-item.menu_item_Golden\\ Parasite .parasite-nav-label {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100%;
      font-family: "Beaufort for LOL", serif;
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 1.5px;
      color: #c8aa6e;
      transition: color 0.15s, text-shadow 0.15s;
      cursor: pointer;
      user-select: none;
    }

    lol-uikit-navigation-item.menu_item_Golden\\ Parasite:hover .parasite-nav-label {
      color: #f0e6d2;
      text-shadow: 0 0 6px rgba(200, 170, 110, 0.8);
    }

"""
NAV_ACTIVE_ANCHOR = "    /* Prevent active state styling for Golden Parasite */\n"
UPDATE_URL = f'GITHUB_RELEASE_API = "https://api.github.com/repos/{PARASITE_REPO}/releases/latest"\n'
ANALYTICS_ANCHOR = "    # Initialize analytics thread\n"
SEND_ANCHOR = "    def _send_message(self, message: str) -> None:\n"

# (file, old, new): exact text in the rebranded Rose file -> Parasite's version
EDITS = [
    # Client nav bar: the word PARASITE instead of the golden rose mask
    (UI_JS, NAV_ACTIVE_ANCHOR, NAV_CSS + NAV_ACTIVE_ANCHOR),
    (UI_JS,
     "    // Check if Golden Parasite item already exists by checking for the golden_parasite.png image\n"
     "    const existingItem = rightNavMenu.querySelector(\n"
     "      'lol-uikit-navigation-item .menu-item-icon[style*=\"golden_parasite.png\"]'\n",
     "    // Check if Golden Parasite item already exists by checking for its PARASITE label\n"
     "    const existingItem = rightNavMenu.querySelector(\n"
     "      \"lol-uikit-navigation-item .parasite-nav-label\"\n"),
    (UI_JS,
     '    icon.className = "menu-item-icon";\n'
     "    icon.style.webkitMaskImage = `url(http://127.0.0.1:${window.__parasiteBridge ? window.__parasiteBridge.port : 50000}/asset/golden_parasite.png)`;\n",
     '    icon.className = "parasite-nav-label";\n'
     '    icon.textContent = "PARASITE";\n'),
    # Updates come from Parasite's releases
    ("launcher/update/github_client.py", UPDATE_URL,
     "# Parasite's own releases. Never point this at Rose's: its update would replace Parasite with Rose.\n"
     "# An empty value turns update checks off.\n" + UPDATE_URL),
    # Lobby reveal: thread, broadcast, packaging
    ("main/core/threads.py",
     "from threads import PhaseThread, WSEventThread, LCUMonitorThread\n",
     "from threads import PhaseThread, WSEventThread, LCUMonitorThread\n"
     "from threads.core.lobby_reveal_thread import LobbyRevealThread\n"),
    ("main/core/threads.py", ANALYTICS_ANCHOR,
     "    # Champ select teammate names + op.gg (PARASITE-LobbyReveal plugin)\n"
     "    t_reveal = LobbyRevealThread(lcu, state)\n"
     '    thread_manager.register("Lobby Reveal", t_reveal, stop_method=t_reveal.stop)\n'
     "\n" + ANALYTICS_ANCHOR),
    ("pengu/communication/broadcaster.py", SEND_ANCHOR,
     "    def broadcast_lobby_reveal(self, payload: dict) -> None:\n"
     '        """Broadcast revealed champ select teammates to the LobbyReveal plugin"""\n'
     "        if not self.websocket_server.loop or not self.websocket_server.connections:\n"
     "            return\n"
     '        self._send_message(json.dumps({"type": "lobby-reveal", **payload}))\n'
     "\n" + SEND_ANCHOR),
    ("Parasite.spec", "    'lcu.features.lcu_swiftplay',\n",
     "    'lcu.features.lcu_swiftplay',\n    'lcu.features.lobby_reveal',\n"),
    ("Parasite.spec", "    'threads.core.lcu_monitor_thread',\n",
     "    'threads.core.lcu_monitor_thread',\n    'threads.core.lobby_reveal_thread',\n"),
]

# One click on the PARASITE label toggled the panel twice (nav item + section listeners),
# so closing reopened it at once. The nav item's capture listener toggles alone.
EDITS += [
    (UI_JS,
     "            e.stopPropagation();\n"
     "            e.preventDefault();\n"
     "\n"
     "            // Dispatch event to open settings panel\n"
     '            const event = new CustomEvent("parasite-open-settings", {\n'
     "              detail: { navItem: navItem },\n"
     "              bubbles: true,\n"
     "              cancelable: true,\n"
     "            });\n"
     "            window.dispatchEvent(event);\n"
     "            log.info(\n"
     '              "Dispatched parasite-open-settings event from Golden Parasite section"\n'
     "            );\n",
     "            e.stopPropagation();\n"
     "            e.preventDefault();\n"
     "            // The nav item's capture listener already toggled the settings panel\n"),
]

# PARASITE-Theme's asset library lists, opens, deletes and receives its files through Parasite
EDITS += [
    ('pengu/communication/message_handler.py',
     '        # Route to appropriate handler\n'
     '        if payload_type in {"chroma-log", "plugin-log"}:\n',
     '        # Route to appropriate handler\n'
     '        if payload_type == "parasite-assets":\n'
     '            from pengu.communication.parasite_assets import handle as _handle_parasite_assets\n'
     '            self._send_response(json.dumps(_handle_parasite_assets(payload)))\n'
     '            return\n'
     '        if payload_type in {"chroma-log", "plugin-log"}:\n'),
    ('Parasite.spec', "    'launcher.core',\n", "    'launcher.core',\n    'pengu.communication.parasite_assets',\n"),
]

# Once Pengu is active, an earlier "could not be activated" report no longer applies:
# Troubleshooting kept showing it after Parasite had recovered by itself.
PENGU_PY = 'utils/integration/pengu_loader.py'
EDITS += [
    (PENGU_PY, "def activate() -> bool:\n",
     "def _clear_stale_activation_issue() -> None:\n"
     '    """Pengu is active now: drop an earlier "could not be activated" report."""\n'
     "    try:\n"
     "        from utils.core.issue_reporter import remove_issues\n"
     '        remove_issues(lambda line, fix: "Pengu Loader could not be activated" in line)\n'
     "    except Exception as e:\n"
     "        log.debug('Could not clear the old Pengu activation report: %s', e)\n"
     "\n\n"
     "def activate() -> bool:\n"),
    (PENGU_PY,
     "            log.error('Pengu activation command succeeded, but status is %s.', status.value)\n"
     "            return False\n"
     "        return True\n",
     "            log.error('Pengu activation command succeeded, but status is %s.', status.value)\n"
     "            return False\n"
     "        _clear_stale_activation_issue()\n"
     "        return True\n"),
    (PENGU_PY,
     "                log.info('Parasite Loader enabled; client restart deferred until the client is ready.')\n"
     "        return True\n",
     "                log.info('Parasite Loader enabled; client restart deferred until the client is ready.')\n"
     "        _clear_stale_activation_issue()\n"
     "        return True\n"),
]

# Parasite Offline's status lives in Parasite's tray menu (its own tray icon is hidden)
EDITS += [
    ('utils/integration/tray_manager.py',
     '            pystray.MenuItem("Open Mods Folder", self._on_open_mods),\n',
     '            pystray.MenuItem("Open Mods Folder", self._on_open_mods),\n'
     '            pystray.MenuItem("Status", _parasite_offline_status_menu()),\n'),
    ('utils/integration/tray_manager.py',
     "    def _create_menu(self) -> pystray.Menu:\n",
     "    def _create_menu(self) -> pystray.Menu:\n"
     "        from launcher.parasite_offline import tray_status_menu as _parasite_offline_status_menu\n"),
]

# Parasite.exe carries version info: antivirus heuristics distrust exes without any
PARASITE_VERSION_INFO = '''# Parasite: version info for Parasite.exe (antivirus heuristics distrust exes without any)
import re as _re
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)
_parasite_version = _re.search(r'APP_VERSION = "([^"]+)"', Path('config.py').read_text(encoding='utf-8')).group(1)
_parasite_numbers = tuple((list(map(int, _re.findall(r'\\d+', _parasite_version))) + [0, 0, 0, 0])[:4])
parasite_version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_parasite_numbers, prodvers=_parasite_numbers),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'Parasite Team'),
            StringStruct('FileDescription', 'Parasite'),
            StringStruct('FileVersion', _parasite_version),
            StringStruct('InternalName', 'Parasite'),
            StringStruct('LegalCopyright', 'Parasite Team, MIT License'),
            StringStruct('OriginalFilename', 'Parasite.exe'),
            StringStruct('ProductName', 'Parasite'),
            StringStruct('ProductVersion', _parasite_version),
        ])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ],
)

'''
EDITS += [
    ('Parasite.spec', "exe = EXE(\n", PARASITE_VERSION_INFO + "exe = EXE(\n"),
    ('Parasite.spec', "    icon='assets/icon.ico',\n    uac_admin=True,",
     "    icon='assets/icon.ico',\n    version=parasite_version_info,\n    uac_admin=True,"),
]

# Parasite Offline: League starts through the chat proxy built from parasite/offline
EDITS += [
    ('main/__init__.py',
     '    # Initialize core components\n',
     '    # Start with Windows is on by default, set once on the first run\n'
     '    from launcher.autostart_default import apply_autostart_default\n'
     '    apply_autostart_default()\n'
     '\n'
     '    # Open League through Parasite Offline so the player can appear offline\n'
     '    from launcher.parasite_offline import start_league_through_parasite_offline\n'
     '    start_league_through_parasite_offline()\n'
     '\n'
     '    # Initialize core components\n'),
    ('Parasite.spec', "    'launcher.core',\n",
     "    'launcher.core',\n    'launcher.parasite_offline',\n    'launcher.autostart_default',\n"),
    ('Parasite.spec', "    'injection/tools/LeagueToolFlop.dll',\n",
     "    'injection/tools/LeagueToolFlop.dll',\n    'injection/tools/ParasiteOffline.exe',  # built by parasite/offline/build_offline.py\n"),
]


# Desktop hub (launcher/parasite_hub.py): startup progress, updates and quick actions in one window
EDITS += [
    ('launcher/core/launcher.py',
     '    updater_log.info("Launcher sequence starting.")\n    dialog = UpdateDialog()\n',
     '    updater_log.info("Launcher sequence starting.")\n'
     '    from launcher.parasite_hub import make_launcher_dialog\n'
     '    dialog = make_launcher_dialog(UpdateDialog)\n'),
    ('launcher/core/launcher.py',
     '    result = user32.MessageBoxW(\n'
     '        dialog.hwnd or None,\n'
     '        message,\n'
     '        "Parasite update available",\n'
     '        MB_YESNO | MB_ICONINFORMATION | MB_DEFBUTTON2 | MB_TOPMOST,\n'
     '    )\n'
     '    accepted = result == IDYES\n',
     '    # The desktop hub asks in its window; None means no hub page, so ask with a message box\n'
     '    hub_answer = dialog.confirm_update(remote_version, local_version) if hasattr(dialog, "confirm_update") else None\n'
     '    if hub_answer is not None:\n'
     '        accepted = hub_answer\n'
     '    else:\n'
     '        result = user32.MessageBoxW(\n'
     '            dialog.hwnd or None,\n'
     '            message,\n'
     '            "Parasite update available",\n'
     '            MB_YESNO | MB_ICONINFORMATION | MB_DEFBUTTON2 | MB_TOPMOST,\n'
     '        )\n'
     '        accepted = result == IDYES\n'),
    ('main/__init__.py',
     '        tray_manager.restart_callback = updated_tray_restart_callback\n',
     '        tray_manager.restart_callback = updated_tray_restart_callback\n'
     '\n'
     '        # The desktop hub takes over from the launcher and uses the tray\'s quit and restart\n'
     '        from launcher.parasite_hub import attach as attach_hub\n'
     '        attach_hub(tray_manager)\n'),
    ('utils/integration/tray_manager.py',
     '            pystray.MenuItem("Open Mods Folder", self._on_open_mods),\n',
     '            pystray.MenuItem("Parasite Hub", self._on_open_hub, default=True),\n'
     '            pystray.MenuItem("Open Mods Folder", self._on_open_mods),\n'),
    ('utils/integration/tray_manager.py',
     '    def _on_open_mods(self, icon, item):\n',
     '    def _on_open_hub(self, icon, item):\n'
     '        """Open Parasite\'s desktop hub (a left click on the tray icon does this too)."""\n'
     '        try:\n'
     '            from launcher.parasite_hub import open_window\n'
     '\n'
     '            open_window()\n'
     '        except Exception as e:\n'
     '            log.error(f"Failed to open the Parasite hub: {e}")\n'
     '\n'
     '    def _on_open_mods(self, icon, item):\n'),
    ('utils/integration/tray_manager.py',
     '        # Wait for tray icon to be ready (up to 5 seconds)\n',
     '        try:\n'
     '            from launcher.parasite_hub import set_ready as _hub_set_ready\n'
     '\n'
     '            _hub_set_ready(status == "unlocked")\n'
     '        except Exception as e:\n'
     '            log.debug(f"Hub status update failed: {e}")\n'
     '\n'
     '        # Wait for tray icon to be ready (up to 5 seconds)\n'),
    ('Parasite.spec', "    'launcher.core',\n",
     "    'launcher.core',\n    'launcher.parasite_hub',\n    'launcher.parasite_hub_window',\n    'launcher.parasite_spotify',\n    'tkinter',\n"),
]



# LP cutoffs for the client hub's welcome card: the page can't read replays.lol itself (no CORS)
EDITS += [
    ('pengu/communication/message_handler.py',
     '        if payload_type == "parasite-assets":\n',
     '        if payload_type == "parasite-cutoffs":\n'
     '            def _reply_cutoffs(request=payload):\n'
     '                from launcher.parasite_hero import cutoffs_for\n'
     '                self._send_response(json.dumps({"type": "parasite-cutoffs", "requestId": request.get("requestId"),\n'
     '                                                "cutoff": cutoffs_for(str(request.get("region") or ""))}))\n'
     '            threading.Thread(target=_reply_cutoffs, daemon=True, name="ParasiteCutoffs").start()\n'
     '            return\n'
     '        if payload_type == "parasite-assets":\n'),
]


# Updates (Rose 1.5.6+ stages the update beside the install and swaps the two folders in
# apply.ps1): a Parasite process left running from the install folder (an old hub window)
# keeps files open and the folder cannot be moved, so it is closed first. Parasite Offline
# can't be closed (League chat goes through it): the update waits for the next start instead.
APPLY_WAIT = "        if (!$parasite.WaitForExit(30000)) { throw 'Timed out waiting for Parasite to exit.' }\n"
EDITS += [
    ('launcher/update/update_installer.py',
     '$swapStarted = $false\n',
     '$swapStarted = $false\n'
     '$parentExited = $false\n'
     '$restarted = $false\n'
     '\n'
     'function Get-InstalledProcess([string]$name) {\n'
     '    $prefix = $destination.TrimEnd([char]92) + [char]92\n'
     '    Get-Process -Name $name -ErrorAction SilentlyContinue |\n'
     '        Where-Object { $_.Path -and $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) }\n'
     '}\n'),
    ('launcher/update/update_installer.py',
     APPLY_WAIT,
     APPLY_WAIT +
     '        $parentExited = $true\n'
     '        # Parasite: Parasite Offline runs from this folder while the Riot Client is open\n'
     '        if (Get-InstalledProcess \'ParasiteOffline\') {\n'
     '            throw \'Parasite Offline is running (League chat goes through it): the update waits for the next start.\'\n'
     '        }\n'
     '        # Parasite: windows left open from this folder (an old hub window) lock its files\n'
     '        $leftOpen = @(Get-InstalledProcess ([System.IO.Path]::GetFileNameWithoutExtension($plan.executable)))\n'
     '        if ($leftOpen.Count) {\n'
     '            Write-UpdateLog (\'Closing Parasite windows left open: \' + (($leftOpen | ForEach-Object { $_.Id }) -join \', \'))\n'
     '            $leftOpen | Stop-Process -Force -ErrorAction SilentlyContinue\n'
     '            Start-Sleep -Milliseconds 800\n'
     '        }\n'),
]


# Privacy: Rose's analytics sent a heartbeat with this PC's machine and install IDs to Rose's
# server every 15 minutes. Parasite sends nothing of the kind.
EDITS += [
    ('config.py',
     "ANALYTICS_SERVER_URL = 'https://analytics.rosekeys.site/'  # Analytics server endpoint\n",
     "ANALYTICS_SERVER_URL = ''  # Parasite has no analytics server\n"),
    ('config.py',
     "ANALYTICS_ENABLED = True  # Enable/disable analytics tracking\n",
     "ANALYTICS_ENABLED = False  # Parasite sends no usage data anywhere\n"),
    ('analytics/tests/test_analytics.py',
     '    def test_missing_config_option_keeps_analytics_enabled(self, post, get_install_id):\n'
     '        post.return_value = Mock(status_code=204)\n'
     '        with patch("analytics.core.analytics_client.get_config_option", return_value=None):\n'
     '            self.assertTrue(AnalyticsClient().send_ping("1.2.14"))\n',
     '    def test_parasite_sends_nothing_by_default(self, post, get_install_id):\n'
     '        post.return_value = Mock(status_code=204)\n'
     '        with patch("analytics.core.analytics_client.get_config_option", return_value=None):\n'
     '            self.assertFalse(AnalyticsClient().send_ping("1.2.14"))\n'
     '        post.assert_not_called()\n'),
]


# README: Parasite's own features, privacy and links (no Rose analytics, donation or Discord)
EDITS += [
    ('README.md',
     '# Parasite\n',
     '# 💜 Parasite\n'),
    ('README.md',
     '[![Installer](https://img.shields.io/badge/Installer-Windows-32A832)](https://github.com/lustmyself/Parasite/releases/latest) [![Downloads](https://img.shields.io/github/downloads/lustmyself/Parasite/total?color=32A832&label=Downloads&cacheSeconds=86400)](https://github.com/lustmyself/Parasite/releases/latest) [![Discord](https://img.shields.io/discord/1490473857075642621?color=32A832&logo=discord&logoColor=white&label=Discord)](https://discord.com/invite/roseskins) [![Ko-Fi](https://img.shields.io/badge/KoFi-Donate-C03030?logo=ko-fi&logoColor=white)](https://ko-fi.com/roseapp) [![License](https://img.shields.io/badge/License-MIT-C03030)](LICENSE)\n',
     '[![Installer](https://img.shields.io/badge/Installer-Windows-32A832)](https://github.com/lustmyself/Parasite/releases/latest) [![Downloads](https://img.shields.io/github/downloads/lustmyself/Parasite/total?color=32A832&label=Downloads&cacheSeconds=86400)](https://github.com/lustmyself/Parasite/releases/latest) [![License](https://img.shields.io/badge/License-MIT-C03030)](LICENSE)\n'),
    # Rose's warning names a fake Rose site; renamed it would name a site that doesn't exist
    ('README.md',
     '> `parasiteskin.xyz` has nothing to do with Parasite, and **its download contains malware**. If you installed anything from it, reinstall Windows. Parasite is only distributed through',
     '> Parasite is only distributed through'),
    ('README.md',
     'Only you see the skin (and your friends, with Party Mode)',
     "Only you see the skin (and other Parasite users in your lobby)"),
    ('README.md',
     "- **Party Mode**: friends running Parasite see each other's skins in game\n",
     "- **Desktop hub**: startup progress, updates, your Riot ID, rank, last match and your server's\n  Grandmaster and Challenger LP cutoffs, quick actions and Parasite Offline's status\n- **Parasite Offline**: appear offline or on mobile to your friends while you play\n- **Custom skins tab**: drop your own `.fantome`, `.zip` or `.modpkg` skins in and switch them\n  on per champion; they play on the champion's default skin\n- **Spotify themes**: 22 Spicetify themes for the Spotify desktop app, re-applied after\n  Spotify updates\n- **Silent updates**: new versions download in the background and install while League is closed\n- **Lobby Reveal**: your teammates' names and op.gg links in champion select\n- **Skin sharing**: Parasite users in your lobby or champ select team see each other's skins and\n  profile icons, through Parasite's own relay (`parasite/relay`)\n"),
    ('README.md',
     '- **22 languages**, following your League client\n',
     '- **Turkish**: the hub, the client menus, the installer and Parasite Offline\n'),
    ('README.md',
     ", and ask on [Discord](https://discord.com/invite/roseskins) if you're stuck.\n",
     ", and open an [issue](https://github.com/lustmyself/Parasite/issues/new/choose) if you're stuck.\n"),
    ('README.md',
     'Only a random installation ID and the app version, sent to `analytics.parasitekeys.site` at startup, every 15 minutes while Parasite runs, and when it closes. The ID is not tied to your hardware or account. Builds from source can turn it off with `ANALYTICS_ENABLED = False` in `config.py`.\n',
     'No. Parasite sends no usage data anywhere: the analytics Rose has are switched off. It talks to GitHub (updates, skins), the League client on your PC, and replays.lol for the LP cutoffs on the welcome card.\n'),
    ('README.md',
     '[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/roseapp)\n\n',
     ''),
    ('README.md',
     ' · [CommunityDragon](https://github.com/CommunityDragon/Data)\n',
     ' · [CommunityDragon](https://github.com/CommunityDragon/Data)\n\nParasite is built on [Rose](https://github.com/Alban1911/Rose) (MIT). Its client theme comes from\n[Elaina](https://github.com/Elaina69/Elaina-theme) (MIT) and Parasite Offline from\n[Deceive](https://github.com/molenzwiebel/Deceive) (GPL-3.0).\n'),
]


# Rose's Discord and Ko-fi links led Parasite players to Rose's community and donations
EDITS += [
    ('Pengu Loader/plugins/PARASITE-SettingsPanel/index.js',
     '    const discordLink = document.createElement("a");\n    discordLink.className = "settings-link";\n    discordLink.href = DISCORD_INVITE_URL;\n    discordLink.target = "_blank";\n    discordLink.textContent = "Discord";\n    linksSection.appendChild(discordLink);\n\n    const kofiLink = document.createElement("a");\n    kofiLink.className = "settings-link";\n    kofiLink.href = KOFI_URL;\n    kofiLink.target = "_blank";\n    kofiLink.textContent = "Ko-Fi";\n    linksSection.appendChild(kofiLink);\n\n',
     '    // Parasite: the GitHub link only\n'),
    ('CONTRIBUTING.md',
     ', and [Discord](https://discord.com/invite/roseskins) is the place for questions.',
     ', and [issues](https://github.com/lustmyself/Parasite/issues/new/choose) are the place for questions.'),
    ('docs/troubleshooting.md',
     ' and ask on [Discord](https://discord.com/invite/roseskins) or open a [bug report]',
     ' and open a [bug report]'),
]


# Party Mode's plugin is gone (see REMOVE): only the skin monitor's ports are checked
EDITS += [
    ('pengu/tests/test_bridge_port_range.py',
     "        for plugin in ('PARASITE-SkinMonitor', 'PARASITE-PartyMode'):\n",
     "        for plugin in ('PARASITE-SkinMonitor',):\n"),
]


# Retired Parasite plugins leave the runtime Pengu Loader the client loads plugins from
EDITS += [
    ('utils/integration/pengu_loader.py',
     '        log.info("Synced Pengu Loader to runtime directory (preserving user files): %s", runtime_dir)\n',
     '        # Parasite plugins a newer Parasite no longer ships stay here otherwise (the copy keeps extras)\n        try:\n            from launcher.parasite_cleanup import clean_retired_plugins\n            clean_retired_plugins(runtime_dir / "plugins")\n        except Exception as exc:\n            log.debug("Could not remove retired Parasite plugins: %s", exc)\n        log.info("Synced Pengu Loader to runtime directory (preserving user files): %s", runtime_dir)\n'),
]


# The hub's Settings page: the skins master switch
EDITS += [
    ('threads/handlers/injection_trigger.py',
     '            log.error(f"   Loadout Timer: #{ticker_id}")\n            log.error("=" * LOG_SEPARATOR_WIDTH)\n            return\n        \n        # Check if custom mod is selected for this skin (before logging)\n',
     '            log.error(f"   Loadout Timer: #{ticker_id}")\n            log.error("=" * LOG_SEPARATOR_WIDTH)\n            return\n        \n        # Parasite: skins switched off in the hub\'s settings: the game starts without mods\n        try:\n            from launcher.parasite_settings import enabled as _parasite_setting\n            if not _parasite_setting("skins"):\n                log.info("[Settings] Skins are off in the hub: nothing is injected")\n                return\n        except Exception as e:\n            log.debug(f"[Settings] Could not read the skins switch: {e}")\n        # Check if custom mod is selected for this skin (before logging)\n'),
    ('Parasite.spec', "    'launcher.parasite_hub',\n", "    'launcher.parasite_hub',\n    'launcher.parasite_settings',\n"),
]


# Spotify's now playing in the hub (launcher/parasite_media.py): Windows' media controls and
# Spotify's own audio session (mute, sound level for the visualizer)
EDITS += [
    ('requirements.txt', 'Pillow==10.4.0\n', 'Pillow==10.4.0\nwinrt-runtime==3.2.1\nwinrt-Windows.Foundation==3.2.1\nwinrt-Windows.Foundation.Collections==3.2.1\nwinrt-Windows.Media.Control==3.2.1\nwinrt-Windows.Storage.Streams==3.2.1\ncomtypes==1.4.17\npycaw==20260927\n'),
    ('Parasite.spec', "    'launcher.parasite_settings',\n", "    'launcher.parasite_settings',\n    'launcher.parasite_media',\n    'launcher.parasite_perf',\n    'winrt.windows.foundation',\n    'winrt.windows.foundation.collections',\n    'winrt.windows.media.control',\n    'winrt.windows.storage.streams',\n    'comtypes',\n    'pycaw.pycaw',\n"),
]


# Updates: a failed update no longer leaves Parasite closed behind an error box: once the old
# Parasite has exited, the installed one starts again (the reason is in update.log). The box is
# kept for when Parasite could not be started at all (Recover-Parasite.cmd is needed then).
EDITS += [
    ('launcher/update/update_installer.py',
     'elseif ($result -ne 0 -and $swapStarted -and [System.IO.File]::Exists($executable)) {\n'
     '    # The swap failed and was undone (or never moved anything): Parasite has\n'
     '    # exited for it, so start the installed one again\n'
     '    try { $null = Start-Parasite; Write-UpdateLog \'Restarted the installed Parasite.\' }\n',
     'elseif ($result -ne 0 -and !$Recover -and $parentExited -and [System.IO.File]::Exists($executable)) {\n'
     '    # The update failed before or during the swap (undone): Parasite has exited\n'
     '    # for it, so start the installed one again (Parasite: also when Parasite\n'
     '    # Offline kept the folder from moving)\n'
     '    try { $null = Start-Parasite; $restarted = $true; Write-UpdateLog \'Restarted the installed Parasite.\' }\n'),
    ('launcher/update/update_installer.py',
     'if ($result -ne 0 -and $Notify) {\n',
     'if ($result -ne 0 -and $Notify -and !$restarted) {\n'),
]


# Restarts keep Pengu on (utils/integration/pengu_loader.py, main/__init__.py)
EDITS += [
    ('utils/integration/pengu_loader.py',
     'def restore_after_parasite() -> bool:\n    with _operation_lock:\n        session = _read_session()\n',
     '# Parasite: a restart (the hub\'s Restart or an update) keeps Pengu on. Switching it off made the\n# next Parasite unable to switch it back on while League was open ("close the running League\n# Client"), and the PARASITE tab was gone until League restarted. The next Parasite adopts it.\nRESTART_KEEP_S = 120\n\n\ndef _keep_flag() -> Path:\n    return get_user_data_dir() / "pengu_keep_for_restart"\n\n\ndef keep_on_for_restart() -> None:\n    """Parasite is about to restart: leave Pengu on when this process exits."""\n    import time\n    try:\n        _keep_flag().write_text(str(time.time()), encoding="utf-8")\n    except OSError as exc:\n        log.debug("Could not mark the restart for Pengu: %s", exc)\n\n\ndef _restarting() -> bool:\n    import time\n    flag = _keep_flag()\n    try:\n        fresh = time.time() - flag.stat().st_mtime < RESTART_KEEP_S\n        flag.unlink()\n        return fresh\n    except OSError:\n        return False\n\n\ndef restore_after_parasite() -> bool:\n    if _restarting():\n        log.info("Parasite is restarting: Pengu stays on and the next Parasite adopts it.")\n        return True\n    with _operation_lock:\n        session = _read_session()\n'),
    ('main/__init__.py',
     '        log.info(f"Restart scheduled via {batch_path}")\n        return True\n',
     '        log.info(f"Restart scheduled via {batch_path}")\n        try:\n            pengu_loader.keep_on_for_restart()\n        except Exception as e:\n            log.debug(f"Could not keep Pengu on for the restart: {e}")\n        return True\n'),
]


# Parasite's CLAUDE.md (working notes that survive a fresh machine) is tracked, not ignored
EDITS += [
    ('.gitignore', 'chroma_issue.txt\nCLAUDE.md\n', 'chroma_issue.txt\n# CLAUDE.md: Parasite keeps its notes for Claude Code in the repo (parasite/overlay/CLAUDE.md)\n'),
]

# Custom skins (pengu/communication/parasite_custom_skins.py): the Parasite hub's Custom skins tab
# replaces champ select's Custom mods button; a switched-on skin plays on its champion's default skin
EDITS += [
    ('pengu/communication/message_handler.py',
     '        if payload_type == "parasite-assets":\n',
     '        if payload_type == "parasite-custom-skins":\n'
     '            from pengu.communication.parasite_custom_skins import handle as _handle_custom_skins\n'
     '            self._send_response(json.dumps(_handle_custom_skins(payload)))\n'
     '            return\n'
     '        if payload_type == "parasite-assets":\n'),
    ('threads/handlers/injection_trigger.py',
     '            # Auto-select previously used custom mods (so users don\'t need to open the Custom Mods UI)\n',
     '            # Parasite custom skins: the one switched on for this champion plays on the skin picked\n'
     '            # (a chroma counts as its skin, so the mod targets the skin and the chroma rides along)\n'
     '            if not selected_custom_mod:\n'
     '                try:\n'
     '                    from pengu.communication.parasite_custom_skins import custom_mod_for\n'
     '                    _parasite_skin = effective_skin_id or ui_skin_id\n'
     '                    _parasite_chromas = getattr(getattr(self.skin_scraper, "cache", None), "chroma_id_map", None) or {}\n'
     '                    try:\n'
     '                        _parasite_skin = int(_parasite_chromas[_parasite_skin]["skinId"])\n'
     '                    except (KeyError, TypeError, ValueError):\n'
     '                        pass\n'
     '                    parasite_custom_skin = custom_mod_for(\n'
     '                        self.state.locked_champ_id or self.state.hovered_champ_id,\n'
     '                        _parasite_skin,\n'
     '                    )\n'
     '                    if parasite_custom_skin:\n'
     '                        self.state.selected_custom_mod = parasite_custom_skin\n'
     '                        selected_custom_mod = parasite_custom_skin\n'
     '                except Exception as e:\n'
     '                    log.warning(f"[CustomSkins] Could not pick a custom skin: {e}")\n'
     '\n'
     '            # Auto-select previously used custom mods (so users don\'t need to open the Custom Mods UI)\n'),
    # The button is never put in champ select (a CSS hide lost to the plugin's own !important rule)
    ('Pengu Loader/plugins/PARASITE-CustomWheel/index.js',
     '    // Append to container (same structure as QUIT button)\n'
     '    targetContainer.appendChild(button);\n',
     '    // Parasite: custom skins live in the Parasite hub (Custom skins tab), not in champ select\n'
     '    return;\n'
     '    // Append to container (same structure as QUIT button)\n'
     '    targetContainer.appendChild(button);\n'),
    ('Parasite.spec', "    'launcher.core',\n", "    'launcher.core',\n    'pengu.communication.parasite_custom_skins',\n"),
]

# A click on PARASITE that reaches Rose's panel (the theme's hub didn't catch it) opens the hub
# when the theme has one; only the hub's "Open core settings" opens Rose's panel.
EDITS += [
    ('Pengu Loader/plugins/PARASITE-SettingsPanel/index.js',
     '    if (navItem) {\n      // Toggle: if panel is already open, close it\n',
     '    const panelOpen = settingsPanel && document.getElementById(PANEL_ID);\n'
     '    if (navItem && !panelOpen && !e.detail?.parasiteCore && typeof window.parasiteOpenHub === "function") {\n'
     '      window.parasiteOpenHub();\n'
     '      return;\n'
     '    }\n'
     '    if (navItem) {\n      // Toggle: if panel is already open, close it\n'),
]

# Parasite's own texts in the client plugins' languages (PARASITE-I18n): Turkish, the only language
# Parasite serves (utils/core/i18n.py); the others get the English text so every language keeps the same keys
LOG_HELP = "If something feels off, open the logs folder and attach the latest log to a GitHub issue."
LOCALE_STRINGS = {
    # Parasite has no Discord: the log goes to a GitHub issue (see the SettingsPanel edit below)
    LOG_HELP: {
        "tr": "Bir sorun varsa kayıt klasörünü aç ve en son kaydı GitHub'da açacağın bir sorun bildirimine ekle.",
    },
}
# Rose's texts its tr.json has no Turkish for (parasite/turkish.py): the client speaks Turkish only
for _key, _turkish in LOCALE_TR.items():
    LOCALE_STRINGS.setdefault(_key, {})["tr"] = _turkish
# Keys Rose's languages have that Parasite no longer uses: dropped from every PARASITE-I18n language
LOCALE_DROPPED = [
    "If something feels off, open the logs folder and share the latest log in a discord ticket.",
]


# Desktop hub in WebView2 (launcher/parasite_hub_shell.py): Parasite.exe --parasite-hub-window <url> shows it
EDITS += [
    ('main/__init__.py',
     '    """Program entry point that prepares and launches Parasite."""\n    args = setup_arguments()\n',
     '    """Program entry point that prepares and launches Parasite."""\n'
     '    # The desktop hub window runs as a second Parasite process (pywebview needs a main thread).\n'
     '    # Only that process loads the hub here: any other start (the uninstaller\'s\n'
     '    # --remove-ltk-mods...) goes through Parasite\'s own flags first, as in Rose\n'
     '    if "--parasite-hub-window" in sys.argv:\n'
     '        from launcher.parasite_hub_shell import main_if_window\n'
     '        if main_if_window():\n'
     '            return\n'
     '    args = setup_arguments()\n'),
    ('requirements.txt', 'requests==2.31.0\n', 'requests==2.31.0\npywebview==6.2.1\n'),
    ('Parasite.spec', "    'launcher.core',\n",
     "    'launcher.core',\n    'launcher.parasite_hub_server',\n    'launcher.parasite_hub_shell',\n"
     "    'launcher.parasite_hub_web',\n    'launcher.parasite_rose',\n    'webview',\n    'webview.platforms.edgechromium',\n"
     "    'webview.platforms.winforms',\n    'clr',\n    'clr_loader',\n"),
    ('Parasite.spec', "# Include the source-built Pengu Loader runtime used for Parasite activation/deactivation\n",
     "# pywebview's WebView2 DLLs for the desktop hub window\n"
     "try:\n"
     "    webview_datas = collect_data_files('webview')\n"
     "    datas += webview_datas\n"
     "    print(f\"[OK] Collected {len(webview_datas)} pywebview data files\")\n"
     "except Exception as e:\n"
     "    print(f\"[WARNING] Could not collect pywebview data files: {e}\")\n\n"
     "# Include the source-built Pengu Loader runtime used for Parasite activation/deactivation\n"),
]


# Parasite's installer had Rose's AppId: Inno Setup took Parasite for a Rose upgrade on a PC with
# Rose, reusing Rose's folder and uninstall entry. Parasite has its own id, and never takes over
# a previous folder by itself.
EDITS += [
    ('installer.iss', 'AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}\n',
     'AppId={{D0EF746D-DCEE-4F08-BD14-FB226CB630F3}}\nUsePreviousAppDir=no\n'),
]


# Update check without GitHub's API when its hourly limit is used up (60 calls per IP,
# shared with the skin downloader): releases/latest redirects to the newest tag, and the
# update package's name follows from it
GH_CLIENT = "launcher/update/github_client.py"
EDITS += [
    (GH_CLIENT,
     '        except Exception as e:\n'
     '            log.warning("Update check failed while fetching latest release: %s", e)\n'
     '            return None\n',
     '        except Exception as e:\n'
     '            log.warning("Update check failed while fetching latest release: %s", e)\n'
     '            return self._latest_from_web()\n'
     '\n'
     '    def _latest_from_web(self) -> Optional[dict]:\n'
     '        """The latest release from github.com itself, which the API limit does not cover."""\n'
     '        repo = GITHUB_RELEASE_API.split("/repos/", 1)[-1].rsplit("/releases", 1)[0]\n'
     '        try:\n'
     '            response = requests.get(f"https://github.com/{repo}/releases/latest",\n'
     '                                    timeout=self.timeout, allow_redirects=False)\n'
     '            tag = response.headers.get("Location", "").rstrip("/").rsplit("/tag/", 1)[-1]\n'
     '        except Exception as e:\n'
     '            log.warning("Update check from github.com failed too: %s", e)\n'
     '            return None\n'
     '        if response.status_code not in (301, 302) or not re.fullmatch(r"v?[0-9][0-9A-Za-z.]*", tag):\n'
     '            log.warning("Update check from github.com found no release tag")\n'
     '            return None\n'
     '        version = tag.lstrip("vV")\n'
     '        name = f"update_package_{version}.zip"\n'
     '        log.info("Latest release %s found on github.com (API limit reached)", tag)\n'
     '        return {"tag_name": tag, "assets": [{\n'
     '            "name": name, "size": 0,\n'
     '            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag}/{name}",\n'
     '        }]}\n'),
    (GH_CLIENT, "from typing import Optional\n", "import re\nfrom typing import Optional\n"),
]

# Parasite's release tags start with "v" (v2.1) but its update packages do not
# (update_package_2.1.zip): the redirect check drops the "v" before naming the package
EDITS += [
    (GH_CLIENT,
     "            name = UPDATE_PACKAGE_NAME.format(version=tag)\n",
     "            name = UPDATE_PACKAGE_NAME.format(version=tag.lstrip(\"vV\"))\n"),
]


# LTK Manager installs itself: when Parasite can't find it, it looks in Windows' list of
# installed programs, then downloads LTK Manager's official installer and runs it
# (injection/tools/ltk_manager_install.py). The dialog is only left for when that fails.
EDITS += [
    ("main/__init__.py",
     "    if ToolsManager(tools_dir).detect_ltk_manager() is None:\n"
     "        return _show_dll_dialog(tools_dir, reason=\"no_manager\")\n"
     "    return True\n",
     "    manager = ToolsManager(tools_dir)\n"
     "    if manager.detect_ltk_manager() is None:\n"
     "        from config import set_config_option\n"
     "        from injection.tools.ltk_manager_install import install_ltk_manager, registered_ltk_manager\n"
     "\n"
     "        found = registered_ltk_manager()\n"
     "        if found is not None:\n"
     "            log.info(f\"[DLL] LTK Manager found in the installed programs: {found}\")\n"
     "        else:\n"
     "            found = install_ltk_manager(manager.detect_ltk_manager)\n"
     "        if found is None:\n"
     "            return _show_dll_dialog(tools_dir, reason=\"no_manager\")\n"
     "        set_config_option(\"General\", \"ltkManagerPath\", str(found))\n"
     "    return True\n"),
    ("main/__init__.py",
     "            \"Parasite can't find LTK Manager\",\n"
     "            \"Parasite applies skins through LTK Manager. It only has to be installed: Parasite \"\n",
     "            \"Parasite couldn't install LTK Manager\",\n"
     "            \"Parasite applies skins through LTK Manager and tried to install it for you, but the \"\n"
     "            \"download or the installation did not finish (no internet, or the Windows prompt was \"\n"
     "            \"declined). It only has to be installed once: Parasite \"\n"),
    ("main/__init__.py",
     "            f\"1. Install LTK Manager ({LTK_MANAGER_DOWNLOAD_URL}), then restart Parasite.\\n\"\n",
     "            \"1. Restart Parasite to try again, and click Yes on the Windows prompt. Or install \"\n"
     "            f\"LTK Manager yourself ({LTK_MANAGER_DOWNLOAD_URL}).\\n\"\n"),
]


# Silent updates (launcher/parasite_autoupdate.py): a package downloaded in the background is
# installed as it is, without downloading it again
EDITS += [
    ("launcher/update/update_sequence.py",
     "        zip_path = updates_root / \"package.zip\"\n"
     "        status_callback(f\"Downloading update {remote_version}\")\n"
     "        if not self.downloader.download_update(\n",
     "        zip_path = updates_root / \"package.zip\"\n"
     "        # Parasite: only the package GitHub published is installed. The background download\n"
     "        # sits in a folder any program of the user can write to: it is copied into the\n"
     "        # workspace (administrators only) and checked there (launcher/parasite_integrity.py)\n"
     "        from launcher.parasite_autoupdate import predownloaded\n"
     "        from launcher.parasite_integrity import BAD_HASH, NO_HASH, take_verified, verify_file\n"
     "        expected = asset.get(\"sha256\")\n"
     "        if not expected:\n"
     "            status_callback(NO_HASH)\n"
     "            return False\n"
     "        background = predownloaded(asset, remote_version)\n"
     "        if background and take_verified(background, zip_path, expected):\n"
     "            status_callback(\"Update downloaded in the background\")\n"
     "        else:\n"
     "            background = None\n"
     "            status_callback(f\"Downloading update {remote_version}\")\n"
     "        if not background and not self.downloader.download_update(\n"),
    # ... and checked again right before it is extracted
    ("launcher/update/update_sequence.py",
     "            return False\n"
     "\n"
     "        status_callback(\"Extracting update\")\n",
     "            return False\n"
     "        if not verify_file(zip_path, expected):\n"
     "            zip_path.unlink(missing_ok=True)\n"
     "            status_callback(BAD_HASH)\n"
     "            return False\n"
     "\n"
     "        status_callback(\"Extracting update\")\n"),
    # The expected SHA-256 comes from GitHub (asset digest or SHA256SUMS) before anything is asked
    ("launcher/update/update_sequence.py",
     "            status_callback(\"No release asset found\")\n"
     "            return False\n",
     "            status_callback(\"No release asset found\")\n"
     "            return False\n"
     "        from launcher.parasite_integrity import NO_HASH, expected_sha256\n"
     "        asset = dict(asset, sha256=expected_sha256(release, asset))\n"
     "        if not asset[\"sha256\"]:\n"
     "            # Not installed unverified: the next start (or release check) tries again\n"
     "            status_callback(NO_HASH)\n"
     "            return False\n"),
    # The workspace (package, staging, apply.ps1) is restricted to administrators
    ("launcher/update/update_installer.py",
     "            raise OSError(f\"Update workspace is a link: {root}\")\n",
     "            raise OSError(f\"Update workspace is a link: {root}\")\n"
     "        # Parasite: only administrators may change what the elevated update installs and runs\n"
     "        from launcher.parasite_integrity import secure_workspace\n"
     "        secure_workspace(root)\n"),
    ("Parasite.spec", "    'launcher.core',\n", "    'launcher.core',\n    'launcher.parasite_autoupdate',\n    'launcher.parasite_cleanup',\n    'launcher.parasite_hero',\n    'launcher.parasite_integrity',\n"),
    # Rose's test of the update sequence: the package it "downloads" now has to match its SHA-256
    ("launcher/tests/test_update_sequence.py",
     "        self.sequence.downloader.download_update.return_value = True\n",
     "        self.sequence.downloader.download_update.side_effect = (\n"
     "            lambda url, path, *rest: path.write_bytes(b\"package\") or True)\n"),
    ("launcher/tests/test_update_sequence.py",
     "        self.sequence.installer.workspace.return_value = Path(temp_dir.name) / \"Parasite.update\"\n",
     "        self.sequence.installer.workspace.return_value = Path(temp_dir.name) / \"Parasite.update\"\n"
     "        self.sequence.installer.workspace.return_value.mkdir()\n"
     "        background = patch(\"launcher.parasite_autoupdate.predownloaded\", return_value=None)\n"
     "        background.start()\n"
     "        self.addCleanup(background.stop)\n"),
    ("launcher/tests/test_update_sequence.py",
     "                {}, \"9.9.9\", {\"browser_download_url\": \"https://example.invalid/u\"}, Mock(), Mock(), None,\n",
     "                {}, \"9.9.9\", {\"browser_download_url\": \"https://example.invalid/u\",\n"
     "                              \"sha256\": hashlib.sha256(b\"package\").hexdigest()}, Mock(), Mock(), None,\n"),
    ("launcher/tests/test_update_sequence.py", "import tempfile\n", "import hashlib\nimport tempfile\n"),
]


# Map skins in the hub (launcher/parasite_maps.py) and the patcher manifest
# (injection/tools/patcher_manifest.py): the hub sees the shared state, PyInstaller takes both
EDITS += [
    ("main/core/initialization.py",
     '        state = SharedState()\n        log.info("Shared state initialized")\n',
     '        state = SharedState()\n        log.info("Shared state initialized")\n'
     '        try:\n'
     '            from launcher import parasite_maps\n'
     '            parasite_maps.attach_state(state)\n'
     '        except Exception as e:  # noqa: BLE001\n'
     '            log.debug(f"[Maps] Hub map picks stay saved choices only: {e}")\n'),
    ("Parasite.spec", "    'launcher.parasite_offline',\n    'launcher.autostart_default',\n",
     "    'launcher.parasite_offline',\n    'launcher.parasite_maps',\n"
     "    'launcher.autostart_default',\n"),
]


# Profile background in the hub (launcher/parasite_profile.py): PyInstaller takes it
EDITS += [
    ("Parasite.spec", "    'launcher.parasite_maps',\n", "    'launcher.parasite_maps',\n    'launcher.parasite_profile',\n"),
]

# Troubleshooting: the "Pengu Loader could not be activated" report goes away once the client
# plugins connect.
EDITS += [
    ('pengu/core/websocket_server.py',
     '        self._connections.add(websocket)\n',
     '        self._connections.add(websocket)\n'
     '        try:  # Parasite: a plugin reached the bridge, so Pengu Loader is active\n'
     '            from utils.integration.pengu_loader import _clear_stale_activation_issue\n'
     '            _clear_stale_activation_issue()\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'),
]

# Profile icon (launcher/parasite_icon.py): the PARASITE-ProfileIcon plugin asks for the chosen icon
EDITS += [
    ('pengu/communication/message_handler.py',
     '        if payload_type == "parasite-assets":\n',
     '        if payload_type == "parasite-profile-icon":\n'
     '            from launcher.parasite_icon import bridge_reply as _parasite_icon_reply\n'
     '            self._send_response(json.dumps(_parasite_icon_reply()))\n'
     '            return\n'
     '        if payload_type == "parasite-assets":\n'),
    ("Parasite.spec", "    'launcher.parasite_profile',\n", "    'launcher.parasite_profile',\n    'launcher.parasite_icon',\n"),
]

# Performance: during a match the main loop has no skin UI to follow, so it wakes twice a
# second instead of twenty times (launcher/parasite_perf.py has the rest of performance mode)
EDITS += [
    ('main/runtime/loop.py',
     '    return MAIN_LOOP_SLEEP if fast_loop else MAIN_LOOP_IDLE_SLEEP\n',
     '    if not fast_loop and getattr(state, "phase", None) == "InProgress":\n        return 0.5  # Parasite: a match is running\n    return MAIN_LOOP_SLEEP if fast_loop else MAIN_LOOP_IDLE_SLEEP\n'),
]


# Fonts in the hub (launcher/parasite_fonts.py): the hub sees the shared state, the bundled Korean
# font is added and picked once on a fresh install, PyInstaller takes the module
EDITS += [
    ("main/core/initialization.py",
     '            log.debug(f"[Maps] Hub map picks stay saved choices only: {e}")\n',
     '            log.debug(f"[Maps] Hub map picks stay saved choices only: {e}")\n'
     '        try:\n'
     '            # Before the fonts: their marker tells a fresh install from an update\n'
     '            from pengu.communication.parasite_custom_skins import ensure_default as _parasite_default_skin\n'
     '            _parasite_default_skin()\n'
     '        except Exception as e:  # noqa: BLE001\n'
     '            log.debug(f"[CustomSkins] Bundled skin not set up: {e}")\n'
     '        try:\n'
     '            from launcher import parasite_fonts\n'
     '            parasite_fonts.attach_state(state)\n'
     '            parasite_fonts.ensure_default()\n'
     '        except Exception as e:  # noqa: BLE001\n'
     '            log.debug(f"[Fonts] Default font not set up: {e}")\n'),
    ("Parasite.spec", "    'launcher.parasite_maps',\n", "    'launcher.parasite_maps',\n    'launcher.parasite_fonts',\n"),
    # The default Summoner's Rift, built from the player's game (launcher/parasite_default_rift.py)
    ("Parasite.spec", "    'launcher.parasite_maps',\n", "    'launcher.parasite_maps',\n    'launcher.parasite_default_rift',\n"),
]


# Rose's files that Parasite doesn't use: dropped from the tree on every sync
REMOVE = [
    "relay-worker",  # Rose's party relay server (Cloudflare worker); Parasite's own is parasite/relay
    # Rose's Party Mode panel: Parasite shares skins by itself (launcher/parasite_share.py), and its
    # test with it
    "Pengu Loader/plugins/PARASITE-PartyMode",
    "test/party_ui_reconnect.test.cjs",
    # Parasite has no Discord: the Pengu Loader window has no Discord button (see the edits)
    "vendor/PenguLoader-1.1.6/loader/Resources/icon_discord.png",
]


def remove_unused(tree):
    for rel in REMOVE:
        path = tree / rel
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def add_locale_strings(tree):
    """Add LOCALE_STRINGS to every PARASITE-I18n language, right after the opening brace."""
    for path in sorted((tree / "Pengu Loader/plugins/PARASITE-I18n/locales").glob("*.json")):
        raw = read_text(path)
        newline = "\r\n" if "\r\n" in raw else "\n"
        dropped = tuple(f"  {json.dumps(key, ensure_ascii=False)}:" for key in LOCALE_DROPPED)
        kept = [line for line in raw.split(newline) if not line.startswith(dropped)]
        if len(kept) != len(raw.split(newline)):
            raw = newline.join(kept)
            json.loads(raw)  # still valid JSON (a dropped key is never the last one)
            write_text(path, raw)
        present = json.loads(raw)
        lines = [f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(values.get(path.stem, key), ensure_ascii=False)},"
                 for key, values in LOCALE_STRINGS.items() if key not in present]
        if not lines:
            continue
        head, rest = raw.split("{", 1)
        write_text(path, head + "{" + newline + newline.join(lines) + rest)


def apply_edits(tree):
    failures = []
    for rel, old, new in EDITS:
        old, new = old.replace("config.ini", "cf.ini"), new.replace("config.ini", "cf.ini")
        path = tree / rel
        if not path.exists():
            failures.append(f"{rel}: file is gone")
            continue
        raw = read_text(path)
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        # Every sync starts from a fresh Rose extract, so an edit is never "already applied":
        # its old text must be there exactly once, or the edit no longer fits Rose's code
        if text.count(old) != 1:
            failures.append(f"{rel}: expected text found {text.count(old)} times:\n{old[:200]}")
            continue
        text = text.replace(old, new)
        write_text(path, text.replace("\n", "\r\n") if crlf else text)
    if failures:
        raise SystemExit("[sync] Parasite's edits no longer fit Rose's code:\n\n" + "\n\n".join(failures))


def install(tree):
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                             capture_output=True).stdout.decode("utf-8").split("\0")
    for rel in filter(None, tracked):
        if rel.split("/", 1)[0] in KEEP:
            continue
        path = ROOT / rel
        if path.is_file():
            path.unlink()
    for src in tree.rglob("*"):
        rel = src.relative_to(tree)
        if rel.parts[0] in KEEP or not src.is_file():
            continue
        dst = ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    # Drop directories emptied by Rose deleting files
    for path in sorted(ROOT.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and ".git" not in path.parts and not any(path.iterdir()):
            path.rmdir()


# The desktop app holds everything: the client shows no PARASITE tab (the skin wheel in champ
# select stays). Parasite's client panel (theme, wallpaper, plugins) opens from the app's
# Settings, through the bridge; parasite_auto runs Auto Accept/Ban/Pick from the app.
HIDE_NAV_CSS = r"""    /* Parasite: everything is in the desktop app, no PARASITE tab in the client */
    lol-uikit-navigation-item.menu_item_Golden.Parasite {
      display: none !important;
    }

"""
EDITS += [
    (UI_JS, NAV_ACTIVE_ANCHOR, HIDE_NAV_CSS + NAV_ACTIVE_ANCHOR),
    (UI_JS,
     '      bridge.subscribe("phase-change", handlePhaseChangeFromPython);\n',
     '      bridge.subscribe("phase-change", handlePhaseChangeFromPython);\n'
     '      // Parasite: the desktop app opens the client panel (the PARASITE tab is hidden)\n'
     '      bridge.subscribe("parasite-open-hub", () => {\n'
     '        if (typeof window.parasiteOpenHub === "function") {\n'
     '          window.parasiteOpenHub();\n'
     '          return;\n'
     '        }\n'
     '        const navItem = document.querySelector("lol-uikit-navigation-item.menu_item_Golden.Parasite");\n'
     '        window.dispatchEvent(new CustomEvent("parasite-open-settings", { detail: { navItem } }));\n'
     '      });\n'),
    ("main/core/initialization.py",
     '            log.debug(f"[Fonts] Default font not set up: {e}")\n',
     '            log.debug(f"[Fonts] Default font not set up: {e}")\n'
     '        try:\n'
     '            from launcher import parasite_client\n'
     '            parasite_client.attach_state(state)\n'
     '        except Exception as e:  # noqa: BLE001\n'
     '            log.debug(f"[Client] The app cannot reach the client panel: {e}")\n'),
    ("Parasite.spec", "    'launcher.parasite_fonts',\n",
     "    'launcher.parasite_fonts',\n    'launcher.parasite_client',\n    'launcher.parasite_auto',\n"),
]


# Wallpaper from the desktop app (launcher/parasite_wallpaper.py): the theme asks for the app's
# choice and reports what it shows over the bridge
EDITS += [
    ('pengu/communication/message_handler.py',
     '        if payload_type == "parasite-assets":\n',
     '        if payload_type == "parasite-wallpaper":\n'
     '            from launcher.parasite_wallpaper import bridge_reply as _parasite_wallpaper_reply\n'
     '            self._send_response(json.dumps(_parasite_wallpaper_reply(payload)))\n'
     '            return\n'
     '        if payload_type == "parasite-assets":\n'),
    ("Parasite.spec", "    'launcher.parasite_auto',\n", "    'launcher.parasite_auto',\n    'launcher.parasite_wallpaper',\n"),
    # Sign in with Discord (launcher/parasite_discord.py)
    ("Parasite.spec", "    'launcher.parasite_wallpaper',\n", "    'launcher.parasite_wallpaper',\n    'launcher.parasite_discord',\n"),
]



# Skin sharing (launcher/parasite_share.py): Rose's Party Mode, joined by itself in the rooms of our
# lobby and champ select team, through Parasite's own relay (parasite/relay)
EDITS += [
    ("main/core/initialization.py",
     "        sys.exit(1)\n    \n    return lcu, skin_scraper, state, injection_manager\n",
     "        sys.exit(1)\n    \n"
     "    try:\n"
     "        from launcher import parasite_share\n"
     "        parasite_share.attach(lcu, state, injection_manager)\n"
     "    except Exception as e:  # noqa: BLE001\n"
     "        log.debug(f\"[Share] Skin sharing not started: {e}\")\n"
     "    return lcu, skin_scraper, state, injection_manager\n"),
    ("Parasite.spec", "    'party.integration.injection_hook',\n",
     "    'party.integration.injection_hook',\n    'party.network.relay_config',\n    'launcher.parasite_share',\n"),
]

# Reveal's counters board in the hub (launcher/parasite_counters.py, imported by parasite_auto)
EDITS += [
    ("Parasite.spec", "    'launcher.parasite_auto',\n", "    'launcher.parasite_auto',\n    'launcher.parasite_counters',\n    'launcher.parasite_lobby',\n"),
]

# Parasite's installer AppId in the registry version sync
EDITS += [
    ("main/__init__.py", '"{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}_is1"', '"{D0EF746D-DCEE-4F08-BD14-FB226CB630F3}}_is1"'),
    ("test/test_installer_safety.py", "A1B2C3D4-E5F6-7890-ABCD-EF1234567890", "D0EF746D-DCEE-4F08-BD14-FB226CB630F3"),
]


# Parasite has no Discord (and no Ko-fi): help goes through GitHub issues
ISSUES_URL = "https://github.com/lustmyself/Parasite/issues"
EDITS += [
    ("main/__init__.py",
     '    footer = _with_links("Need help? Join the Parasite Discord: https://discord.gg/roseskins")\n',
     f'    footer = _with_links("Need help? Open an issue: {ISSUES_URL}")\n'),
    ("main/__init__.py",
     '        "Discord: https://discord.gg/roseskins\\n\\n"\n        f"Press OK to',
     f'        "Need help? Open an issue: {ISSUES_URL}\\n\\n"\n        f"Press OK to'),
    ("main/__init__.py",
     '            "Then send report.txt and report.json on the Parasite Discord (https://discord.gg/roseskins) "\n'
     '            "or in a GitHub issue (https://github.com/lustmyself/Parasite/issues), so we can find out why. "\n',
     f'            "Then attach report.txt and report.json to a GitHub issue ({ISSUES_URL}), so we can find out why. "\n'),
    ("pengu/tests/test_activation_warning.py",
     "        self.assertIn('discord.gg/roseskins', text)\n",
     "        self.assertNotIn('discord', text.lower())  # Parasite has no Discord\n"),
    ("Pengu Loader/plugins/PARASITE-SettingsPanel/index.js",
     '  const DISCORD_INVITE_URL = "https://discord.com/invite/roseskins";\n  const KOFI_URL = "https://ko-fi.com/roseapp";\n',
     ""),
    ("Pengu Loader/plugins/PARASITE-SettingsPanel/index.js",
     't("If something feels off, open the logs folder and share the latest log in a discord ticket.")',
     f't({json.dumps(LOG_HELP)})'),
    ("Pengu Loader/plugins/PARASITE-UI/index.js",
     '  const DISCORD_INVITE_URL = "https://discord.com/invite/roseskins";\n'
     '  const PARASITE_DISCORD_GUILD_ID = "1490473857075642621";\n',
     ""),
    ("Pengu Loader/plugins/PARASITE-UI/index.js",
     '      if (source.includes("/discord/")) {\n'
     '        const fixedSource = source.replace(\n'
     '          /\\/discord\\/\\d+/,\n'
     '          "/discord/" + PARASITE_DISCORD_GUILD_ID\n'
     '        );\n'
     '        if (fixedSource !== source) {\n'
     '          badge.setAttribute("src", fixedSource);\n'
     '        }\n'
     '        return;\n'
     '      }\n',
     '      if (source.includes("/discord/")) {\n'
     '        (badge.closest("a") || badge).remove();  // Parasite has no Discord\n'
     '        return;\n'
     '      }\n'),
    # The Pengu Loader window: no Ko-fi ("Support ... Team") or Discord buttons
    ("vendor/PenguLoader-1.1.6/loader/Program.cs",
     '        public static string HomepageUrl => "https://ko-fi.com/roseapp";\n'
     '        public static string DiscordUrl => "https://discord.gg/roseskins";\n',
     ""),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml.cs",
     "        private void DiscordButtonClick(object sender, RoutedEventArgs e)\n"
     "        {\n"
     "            Utils.OpenLink(Program.DiscordUrl);\n"
     "        }\n\n",
     ""),
    # The whole method: its line alone is also inside a longer, more indented line that already
    # opens GithubIssuesUrl, so apply_edits took it for applied and Program.HomepageUrl stayed
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml.cs",
     "        private void HomePageButtonClick(object sender, RoutedEventArgs e)\n"
     "        {\n"
     "            Utils.OpenLink(Program.HomepageUrl);\n",
     "        private void HomePageButtonClick(object sender, RoutedEventArgs e)\n"
     "        {\n"
     "            Utils.OpenLink(Program.GithubIssuesUrl);  // Report a problem\n"),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml",
     '<TextBlock Text="Support Parasite Team" Margin="8,0,0,0" />',
     '<TextBlock Text="Report a problem" Margin="8,0,0,0" />'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml",
     '                    <Button Click="DiscordButtonClick" Grid.Column="0" Background="Transparent" BorderBrush="#6888" Focusable="False" HorizontalAlignment="Stretch" Margin="0">\n'
     '                        <StackPanel Orientation="Horizontal">\n'
     '                            <Image Source="/Resources/icon_discord.png" Width="16" Height="16" />\n'
     '                            <TextBlock Text="Discord" Margin="8,0,0,0" />\n'
     '                        </StackPanel>\n'
     '                    </Button>\n'
     '                    <Button Click="GitHubButtonClick" Grid.Column="1" Background="Transparent" BorderBrush="#6888" Focusable="False" HorizontalAlignment="Stretch" Margin="5,0,0,0">\n',
     '                    <Button Click="GitHubButtonClick" Grid.Column="0" Grid.ColumnSpan="2" Background="Transparent" BorderBrush="#6888" Focusable="False" HorizontalAlignment="Stretch" Margin="0">\n'),
]

# Parasite Offline (Deceive, GPL-3.0): its license and notice ship next to ParasiteOffline.exe
EDITS += [
    ("Parasite.spec",
     "injection_data_files = [\n    'injection/tools/hashes.game.txt',\n",
     "injection_data_files = [\n    'injection/tools/hashes.game.txt',\n"
     "    # ParasiteOffline.exe is GPL-3.0 (Deceive): its license and where its source is\n"
     "    'injection/tools/ParasiteOffline-LICENSE.txt',\n"
     "    'injection/tools/ParasiteOffline-NOTICE.txt',\n"),
]

# Uninstall removes the Spicetify copy Parasite keeps in its install folder
EDITS += [
    ("installer.iss",
     'Type: filesandordirs; Name: "{app}\\_internal"\n',
     'Type: filesandordirs; Name: "{app}\\_internal"\n'
     "; Parasite's own Spicetify (Spotify themes), downloaded at run time\n"
     'Type: filesandordirs; Name: "{app}\\spicetify"\n'),
    ("test/test_installer_safety.py",
     "        # Only Parasite's runtime, which an update replaces with files the uninstall log never saw\n"
     "        self.assertEqual(re.findall(r'Type: filesandordirs; Name: \"([^\"]+)\"', section), ['{app}\\\\_internal'])\n",
     "        # Only Parasite's runtime, which an update replaces with files the uninstall log never saw,\n"
     "        # and Parasite's own Spicetify, downloaded at run time\n"
     "        self.assertEqual(re.findall(r'Type: filesandordirs; Name: \"([^\"]+)\"', section),\n"
     "                         ['{app}\\\\_internal', '{app}\\\\spicetify'])\n"),
]


PARASITE_VERSION = ROOT / "parasite" / "parasite_version.txt"


def parasite_version(rose_version):
    """Parasite's own version (parasite_version.txt, e.g. 2.1), apart from Rose's.

    The release workflow raises it by one (2.1 -> 2.2) when it builds a new Rose
    release; raise it yourself to ship Parasite fixes.
    """
    try:
        version = PARASITE_VERSION.read_text(encoding="utf-8").strip()
    except OSError:
        return rose_version
    if not re.fullmatch(r"[0-9]+(\.[0-9]+){1,3}", version):
        raise SystemExit(f"[sync] parasite_version.txt holds no version: {version!r}")
    return version


def version_info(version):
    """The four-part version Windows shows in the file's properties (2.1 -> 2.1.0.0)."""
    parts = version.split(".")
    return ".".join(parts + ["0"] * (4 - len(parts)))


def apply_parasite_version(tree):
    config = tree / "config.py"
    text = config.read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("[sync] APP_VERSION not found in config.py")
    rose_version = match.group(1)
    version = parasite_version(rose_version)
    if version == rose_version:
        return
    config.write_text(text.replace(f'APP_VERSION = "{rose_version}"', f'APP_VERSION = "{version}"', 1),
                      encoding="utf-8")
    iss = tree / "installer.iss"
    iss_text = iss.read_text(encoding="utf-8")
    for old, new in [(f'#define MyAppVersion "{rose_version}"', f'#define MyAppVersion "{version}"'),
                     (f'#define MyAppVersionInfo "{rose_version}.0"', f'#define MyAppVersionInfo "{version_info(version)}"')]:
        if old not in iss_text:
            raise SystemExit(f"[sync] {old!r} not found in installer.iss")
        iss_text = iss_text.replace(old, new, 1)
    iss.write_text(iss_text, encoding="utf-8")
    print(f"[sync] Parasite version {version}")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    ref = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        extract_rose(ref, tree)
        rebrand_tree(tree)
        patch_core_dll(tree)
        remove_unused(tree)
        copy_overlay(tree)
        apply_edits(tree)
        add_locale_strings(tree)
        apply_turkish(tree, read_text, write_text)
        apply_parasite_version(tree)
        install(tree)
    print(f"[sync] Parasite tree rebuilt from Rose {ref}")


if __name__ == "__main__":
    main()
