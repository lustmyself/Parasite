"""Silent updates: download a new Parasite while it runs, install it when League is closed.

The hub's release check calls `on_release()`: with "auto update" on (the default) the
update package is downloaded in the background into Parasite's updates folder, next to a
`.ready` file holding its size and SHA-256. The launcher's update sequence then skips its own
download for that package, and the hub's update question answers itself.

Only a package matching the SHA-256 GitHub publishes for it is kept (launcher/parasite_integrity.py);
a release without one is not downloaded, and the next release check (every 30 minutes) tries again.
The updates folder is the user's: the update sequence copies the package into its own
administrators-only folder and checks it again there before installing it.

The install needs Parasite to restart into its launcher. That happens only while no League
client or game runs (checked twice, a minute apart), so nobody is cut off mid-game;
otherwise the package waits for the next start. Parasite Offline counts too: it runs from
Parasite's folder while the Riot Client is open, and the update swaps that folder.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import requests

from utils.core.logging import get_logger

log = get_logger()

CONFIG_KEY = "autoUpdate"
IDLE_CHECK_S = 60
LEAGUE = {"leagueclient.exe", "leagueclientux.exe", "league of legends.exe",
          # The update moves Parasite's folder, which Parasite Offline keeps open
          "parasiteoffline.exe"}
_lock = threading.Lock()
_pending: Optional[str] = None  # version downloaded and waiting to be installed
_waiter: Optional[threading.Thread] = None


def enabled() -> bool:
    from config import get_config_option
    return (get_config_option("General", CONFIG_KEY) or "1") != "0"


def set_enabled(on: bool) -> None:
    from config import set_config_option
    set_config_option("General", CONFIG_KEY, "1" if on else "0")


def pending() -> Optional[str]:
    return _pending


def _updates_dir() -> Path:
    from config import get_config_file_path
    path = get_config_file_path().parent / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ready_path(zip_path: Path) -> Path:
    return zip_path.with_name(zip_path.name + ".ready")


def is_ready(zip_path: Path, expected: Optional[str] = None) -> bool:
    """The package was fully downloaded in the background (and, given `expected`, is that package)."""
    try:
        recorded = ready_path(zip_path).read_text(encoding="utf-8").split()
        if not zip_path.is_file() or not recorded or recorded[0] != str(zip_path.stat().st_size):
            return False
    except OSError:
        return False
    if expected is None:
        return True
    from launcher.parasite_integrity import verify_file
    return verify_file(zip_path, expected)


def package_path(asset: dict, version: str) -> Path:
    """Where the background download keeps `asset` (the release's update package)."""
    return _updates_dir() / (asset.get("name") or f"update_package_{version.lstrip('vV')}.zip")


def predownloaded(asset: dict, version: str) -> Optional[Path]:
    """The package downloaded in the background for `asset`, when it is complete.

    The launcher's update sequence copies it into its own folder, checks it against the
    release's SHA-256 there (`asset["sha256"]`) and deletes this copy.
    """
    try:
        target = package_path(asset, version)
    except OSError:
        return None
    if not is_ready(target, asset.get("sha256")):
        return None
    ready_path(target).unlink(missing_ok=True)
    return target


def _download(url: str, target: Path, expected: int = 0, sha256: Optional[str] = None) -> bool:
    import hashlib
    part = target.with_name(target.name + ".part")
    try:
        if not sha256:
            raise OSError("no SHA-256 to check the package against")
        digest = hashlib.sha256()
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with part.open("wb") as handle:
                for chunk in response.iter_content(1024 * 256):
                    digest.update(chunk)
                    handle.write(chunk)
        size = part.stat().st_size
        if size == 0 or (expected and size != expected):
            raise OSError(f"size {size}, expected {expected}")
        if digest.hexdigest() != sha256.lower():
            raise OSError(f"SHA-256 {digest.hexdigest()}, expected {sha256.lower()}")
        import zipfile
        with zipfile.ZipFile(part) as archive:
            if archive.testzip() is not None:
                raise OSError("the package is damaged")
        part.replace(target)
        ready_path(target).write_text(f"{size} {sha256.lower()}", encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[AutoUpdate] Download failed: {exc}")
        part.unlink(missing_ok=True)
        return False


def _league_running() -> bool:
    import psutil
    return any((p.info.get("name") or "").lower() in LEAGUE for p in psutil.process_iter(["name"]))


def _install_when_idle() -> None:
    """Restart Parasite into its installer once League has been closed for a minute.

    Installs whatever is pending by then: a newer release downloaded while this waits replaces
    the one it started for (the update sequence takes the newest package).
    """
    idle_checks = 0
    while _pending and enabled():
        idle_checks = idle_checks + 1 if not _league_running() else 0
        if idle_checks >= 2:
            from launcher import parasite_hub
            version = _pending
            log.info(f"[AutoUpdate] League is closed; restarting Parasite to install {version}")
            parasite_hub.toast(f"Parasite {version} kuruluyor, birkaç saniye sürecek")
            parasite_hub.mark_quiet_restart()
            time.sleep(3)
            parasite_hub.run_action("update")
            return
        time.sleep(IDLE_CHECK_S)


def on_release(client, release: dict, current: str) -> None:
    """A release check found `release`: download it in the background when it is newer."""
    global _pending, _waiter
    from launcher import parasite_hub
    version = client.get_release_version(release).lstrip("vV")
    if not enabled() or not parasite_hub._version_tuple(version) > parasite_hub._version_tuple(current):
        return
    from launcher.parasite_perf import resting
    if resting():
        return  # performance mode: no download during a match; the next check after it gets it
    asset = client.get_zip_asset(release)
    if not asset or not asset.get("browser_download_url"):
        return
    target = package_path(asset, version)
    with _lock:
        if _pending == version:
            return
        from launcher.parasite_integrity import expected_sha256
        sha256 = expected_sha256(release, asset)
        if not sha256:
            # Nothing unverified is downloaded; the next release check tries again
            log.warning(f"[AutoUpdate] Parasite {version} has no published SHA-256 yet; retrying at the next check")
            return
        if not is_ready(target, sha256):
            log.info(f"[AutoUpdate] Downloading Parasite {version} in the background")
            if not _download(asset["browser_download_url"], target, int(asset.get("size") or 0), sha256):
                return
        _pending = version
    log.info(f"[AutoUpdate] Parasite {version} is downloaded and waits for League to be closed")
    parasite_hub.toast(f"Parasite {version} indirildi; League kapalıyken kendiliğinden kurulacak")
    with _lock:
        # A waiter already running picks up the newer version by itself
        if not _waiter or not _waiter.is_alive():
            _waiter = threading.Thread(target=_install_when_idle, daemon=True, name="ParasiteAutoUpdate")
            _waiter.start()
