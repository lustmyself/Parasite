"""The desktop hub's page, served on 127.0.0.1 to the WebView2 window (launcher/parasite_hub_shell.py).

Every API call needs the token baked into the page and a 127.0.0.1 Host header, so other
web pages and DNS rebinding can't drive it. A window left open from a previous Parasite (after
an update or a restart) gets 403, reloads, and picks up the new token.
"""

from __future__ import annotations

import json
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from utils.core.logging import get_logger

log = get_logger()

PORTS = range(47823, 47833)
PAGE_ALIVE_S = 4.0

_server: Optional[ThreadingHTTPServer] = None
_port = 0
_token = secrets.token_urlsafe(24)
_last_seen = 0.0
_lock = threading.Lock()


def page_open() -> bool:
    return time.time() - _last_seen < PAGE_ALIVE_S


def url() -> str:
    return f"http://127.0.0.1:{_port}/"


def _themes() -> list:
    from launcher.parasite_spotify import PREVIEWS, THEMES
    return [{"key": key, "label": value[2], "bg": value[3], "accent": value[4], "preview": key in PREVIEWS}
            for key, value in THEMES.items()]


class _Handler(BaseHTTPRequestHandler):
    server_version = "ParasiteHub"

    def log_message(self, *args) -> None:
        pass

    def _allowed_host(self) -> bool:
        return self.headers.get("Host", "") in (f"127.0.0.1:{_port}", f"localhost:{_port}")

    def _authorized(self) -> bool:
        return self._allowed_host() and secrets.compare_digest(self.headers.get("X-Parasite-Hub", ""), _token)

    def _send(self, code: int, body: bytes = b"", kind: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, kind: str) -> None:
        """A wallpaper file, streamed; videos ask for byte ranges to seek."""
        try:
            size = path.stat().st_size
            start, end = 0, size - 1
            ranged = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
            if ranged and (ranged.group(1) or ranged.group(2)):
                if ranged.group(1):
                    start = int(ranged.group(1))
                    end = min(int(ranged.group(2)), size - 1) if ranged.group(2) else size - 1
                else:
                    start = max(size - int(ranged.group(2)), 0)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
            self.send_response(206 if ranged else 200)
            self.send_header("Content-Type", kind)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if ranged:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = handle.read(min(left, 256 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (OSError, ConnectionError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        global _last_seen
        if not self._allowed_host():
            return self._send(403)
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            from config import APP_VERSION
            from launcher.parasite_hub_web import render
            page = render(_token, APP_VERSION, _themes())
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/state":
            if not self._authorized():
                return self._send(403)
            _last_seen = time.time()
            from launcher import parasite_hub
            return self._send(200, json.dumps(parasite_hub.snapshot()).encode("utf-8"), "application/json")
        match = re.fullmatch(r"/preview/([a-z]+)\.png", path)
        if match:
            from launcher import parasite_spotify
            preview = parasite_spotify.preview_path(match.group(1)) if match.group(1) in parasite_spotify.PREVIEWS else None
            if preview:
                return self._send(200, preview.read_bytes(), "image/png")
            return self._send(404)
        if path == "/discord":
            from launcher.parasite_discord import CALLBACK_PAGE
            return self._send(200, CALLBACK_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/discord-avatar.png":
            from launcher import parasite_discord
            try:
                return self._send(200, parasite_discord.avatar_path().read_bytes(), "image/png")
            except OSError:
                return self._send(404)
        if path == "/hero.jpg":
            from launcher import parasite_hero
            try:
                return self._send(200, parasite_hero.image_path().read_bytes(), "image/jpeg")
            except OSError:
                return self._send(404)
        if path == "/api/tiles":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_hub
            return self._send(200, json.dumps(parasite_hub.tiles(), ensure_ascii=False).encode("utf-8"), "application/json")
        if path == "/api/auto":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_auto
            return self._send(200, parasite_auto.dumps_listing(), "application/json")
        if path == "/api/wallpapers":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_wallpaper
            return self._send(200, parasite_wallpaper.dumps_listing(), "application/json")
        if path == "/wallpaper-file":
            from urllib.parse import parse_qs
            from launcher import parasite_wallpaper
            name = (parse_qs(self.path.split("?", 1)[-1]).get("name") or [""])[0]
            found = parasite_wallpaper.file_info(name) if name else None
            return self._send_file(*found) if found else self._send(404)
        if path == "/api/maps":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_maps
            return self._send(200, parasite_maps.dumps_listing(), "application/json")
        if path == "/api/fonts":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_fonts
            return self._send(200, parasite_fonts.dumps_listing(), "application/json")
        if path == "/api/skins":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_skins
            return self._send(200, parasite_skins.dumps_listing(), "application/json")
        if path == "/api/profile":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_profile
            return self._send(200, parasite_profile.dumps_listing(), "application/json")
        if path == "/api/icon":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_icon
            return self._send(200, parasite_icon.dumps_listing(), "application/json")
        if path == "/api/profile/skins":
            if not self._authorized():
                return self._send(403)
            from urllib.parse import parse_qs
            from launcher import parasite_profile
            champion = (parse_qs(self.path.split("?", 1)[-1]).get("champion") or [""])[0]
            return self._send(200, parasite_profile.dumps_skins(champion), "application/json")
        if path == "/map-preview":
            from urllib.parse import parse_qs
            from launcher import parasite_maps
            map_id = (parse_qs(self.path.split("?", 1)[-1]).get("id") or [""])[0]
            found = parasite_maps.preview_bytes(map_id) if map_id else None
            return self._send(200, *found) if found else self._send(404)
        if path == "/api/media":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_media
            return self._send(200, json.dumps(parasite_media.state()).encode("utf-8"), "application/json")
        if path == "/api/level":
            if not self._authorized():
                return self._send(403)
            from launcher import parasite_media
            return self._send(200, json.dumps({"level": round(parasite_media.level(), 3)}).encode("utf-8"), "application/json")
        if path == "/cover.jpg":
            from launcher import parasite_media
            try:
                return self._send(200, parasite_media.cover_path().read_bytes(), "image/jpeg")
            except OSError:
                return self._send(404)
        # The home page's fonts (Anton, Barlow Condensed; OFL), bundled in assets/parasite_hub_fonts
        match = re.fullmatch(r"/hubfont/([A-Za-z-]+\.ttf)", path)
        if match:
            try:
                from utils.core.paths import get_asset_path
                return self._send(200, get_asset_path("parasite_hub_fonts/" + match.group(1)).read_bytes(), "font/ttf")
            except OSError:
                return self._send(404)
        # Pages' background art, bundled in assets/parasite_hub_art
        match = re.fullmatch(r"/hubart/([a-z0-9-]+\.jpg)", path)
        if match:
            try:
                from utils.core.paths import get_asset_path
                return self._send(200, get_asset_path("parasite_hub_art/" + match.group(1)).read_bytes(), "image/jpeg")
            except OSError:
                return self._send(404)
        if path == "/icon.png":
            try:
                from utils.core.paths import get_asset_path
                return self._send(200, get_asset_path("tray_ready.png").read_bytes(), "image/png")
            except OSError:
                return self._send(404)
        return self._send(404)

    def do_POST(self) -> None:  # noqa: N802
        # Discord's sign-in comes back in the player's browser, which has no hub token:
        # the one-time state the hub made for this sign-in is the proof
        if self._allowed_host() and self.path == "/discord/finish":
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                body = {}
            body = body if isinstance(body, dict) else {}
            from launcher import parasite_discord, parasite_hub
            message = parasite_discord.finish(body.get("access_token"), body.get("state"))
            parasite_hub.toast(message)
            parasite_hub._cache.pop("discord", None)
            return self._send(200, json.dumps({"message": message}).encode("utf-8"), "application/json")
        if self._authorized() and self.path.startswith("/api/media/"):
            from launcher import parasite_media
            ok = parasite_media.control(self.path.rsplit("/", 1)[-1])
            return self._send(200 if ok else 404, b'{"ok": true}' if ok else b"", "application/json")
        if self._authorized() and self.path.startswith("/api/maps/upload"):
            from urllib.parse import parse_qs, unquote
            from launcher import parasite_hub, parasite_maps
            name = unquote((parse_qs(self.path.split("?", 1)[-1]).get("name") or [""])[0])
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            message = parasite_maps.import_upload(name, self.rfile, length)
            if message:
                parasite_hub.toast(message)
            return self._send(200, json.dumps({"message": message}).encode("utf-8"), "application/json")
        if self._authorized() and self.path.startswith("/api/fonts/upload"):
            from urllib.parse import parse_qs, unquote
            from launcher import parasite_fonts, parasite_hub
            name = unquote((parse_qs(self.path.split("?", 1)[-1]).get("name") or [""])[0])
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            message = parasite_fonts.import_upload(name, self.rfile, length)
            if message:
                parasite_hub.toast(message)
            return self._send(200, json.dumps({"message": message}).encode("utf-8"), "application/json")
        if self._authorized() and self.path.startswith("/api/wallpapers/upload"):
            from urllib.parse import parse_qs, unquote
            from launcher import parasite_hub, parasite_wallpaper
            name = unquote((parse_qs(self.path.split("?", 1)[-1]).get("name") or [""])[0])
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            message = parasite_wallpaper.import_upload(name, self.rfile, length)
            if message:
                parasite_hub.toast(message)
            return self._send(200, json.dumps({"message": message}).encode("utf-8"), "application/json")
        if self._authorized() and self.path.startswith("/api/skins/upload"):
            from urllib.parse import parse_qs, unquote
            from launcher import parasite_hub, parasite_skins
            name = unquote((parse_qs(self.path.split("?", 1)[-1]).get("name") or [""])[0])
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            message = parasite_skins.import_upload(name, self.rfile, length)
            if message:
                parasite_hub.toast(message)
            return self._send(200, json.dumps({"message": message}).encode("utf-8"), "application/json")
        if not self._authorized() or not self.path.startswith("/api/action/"):
            # Read a small body first: closing with it unread resets the connection on Windows
            # before the client sees the 403
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if 0 < length <= 4096:
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            return self._send(403)
        name = self.path.rsplit("/", 1)[-1]
        from launcher import parasite_hub
        if name not in parasite_hub.ACTIONS:
            return self._send(404)
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        # Some actions take a while (Spotify themes); the page polls for the result
        threading.Thread(target=parasite_hub.run_action, args=(name, body if isinstance(body, dict) else {}),
                         daemon=True, name=f"ParasiteHub-{name}").start()
        return self._send(200, b'{"ok": true}', "application/json")


class _Server(ThreadingHTTPServer):
    # Windows lets SO_REUSEADDR share a port another process listens on; the hub's must be its own
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start() -> bool:
    global _server, _port
    with _lock:
        if _server:
            return True
        for port in PORTS:
            try:
                server = _Server(("127.0.0.1", port), _Handler)
            except OSError:
                continue
            _server, _port = server, port
            threading.Thread(target=server.serve_forever, daemon=True, name="ParasiteHubServer").start()
            log.info(f"[Hub] Serving the hub page on 127.0.0.1:{port}")
            return True
    log.warning("[Hub] No free port for the hub page")
    return False
