"""Update integrity: an update is installed only as the exact package GitHub published.

Parasite runs as administrator and its updates replace its own folder in Program Files. The
update package used to be checked only by its size and a zip test, and the one downloaded in
the background waits in %LOCALAPPDATA%\\Parasite\\updates, which every program the user runs
can write to: swapping it between the download and the install ran that program's files as
administrator. Now:

- The release's SHA-256 comes from GitHub over HTTPS: the asset's `digest` (GitHub computes it
  on upload and the API lists it), else the release's SHA256SUMS file (rose-sync.yml publishes
  it), else the API's listing of that release. Without one, nothing is installed.
- The package is checked after the download, copied into the update workspace (beside the
  install folder, administrators only) and checked again there right before it is extracted.
- The workspace, where the package is extracted and apply.ps1 runs from, gets an access list
  of its own: administrators and SYSTEM may change it, users may only read it, like Program
  Files. Nothing is run from %LOCALAPPDATA%.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

import requests

from utils.core.logging import get_logger

log = get_logger()

SUMS_NAME = "SHA256SUMS"
RELEASES_PAGE = "https://github.com/lustmyself/Parasite/releases/latest"
CHUNK = 1024 * 1024

# Shown in the update window (Turkish only, like the rest of Parasite)
NO_HASH = ("Güncelleme doğrulanamadı: GitHub bu sürümün SHA-256 özetini vermedi, güvenlik için "
           "kurulmadı. Parasite bir sonraki açılışta yeniden dener; hemen kurmak için: " + RELEASES_PAGE)
BAD_HASH = ("Güncelleme doğrulanamadı: indirilen paket GitHub'daki SHA-256 özetiyle eşleşmiyor, "
            "kurulmadı. Parasite bir sonraki açılışta yeniden indirir.")

_HEX = re.compile(r"[0-9a-fA-F]{64}")


# ---- the expected SHA-256 ----

def parse_digest(value) -> Optional[str]:
    """The hex SHA-256 of a GitHub asset `digest` ("sha256:<hex>"), or None."""
    if not isinstance(value, str) or not value.lower().startswith("sha256:"):
        return None
    hex_digest = value.split(":", 1)[1].strip()
    return hex_digest.lower() if _HEX.fullmatch(hex_digest) else None


def parse_sums(text: str, name: str) -> Optional[str]:
    """The SHA-256 a sha256sum listing gives for `name` ("<hex>  name" or "<hex> *name")."""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not _HEX.fullmatch(parts[0]):
            continue
        listed = parts[1].strip()
        listed = listed[1:] if listed.startswith("*") else listed
        if listed == name:
            return parts[0].lower()
    return None


def _github_https(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname == "github.com"


def _sums_url(release: dict, asset: dict) -> Optional[str]:
    """SHA256SUMS of the release: the listed asset, else beside the update package."""
    for item in release.get("assets") or []:
        if isinstance(item, dict) and item.get("name") == SUMS_NAME and _github_https(item.get("browser_download_url")):
            return item["browser_download_url"]
    url = asset.get("browser_download_url") or ""
    if _github_https(url) and "/releases/download/" in url:
        return url.rsplit("/", 1)[0] + "/" + SUMS_NAME
    return None


def _from_sums(release: dict, asset: dict, timeout: float) -> Optional[str]:
    url = _sums_url(release, asset)
    if not url:
        return None
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
        if response.status_code != 200 or not str(response.url or url).startswith("https://"):
            log.info(f"[Integrity] No {SUMS_NAME} for this release (HTTP {response.status_code})")
            return None
        return parse_sums(response.text[:65536], asset.get("name") or "")
    except requests.RequestException as exc:
        log.info(f"[Integrity] {SUMS_NAME} could not be read: {exc}")
        return None


def _from_api(release: dict, asset: dict, timeout: float) -> Optional[str]:
    """The asset's digest from the API's listing of the release (one API call)."""
    from launcher.update.github_client import GITHUB_RELEASE_API
    from utils.download import github_rate_limit
    tag = release.get("tag_name") or ""
    if not GITHUB_RELEASE_API or not tag:
        return None
    url = GITHUB_RELEASE_API.rsplit("/latest", 1)[0] + "/tags/" + quote(tag, safe="")
    try:
        response = github_rate_limit.api_get(url, timeout=timeout)
        if response is None or response.status_code != 200:
            return None
        for item in response.json().get("assets") or []:
            if isinstance(item, dict) and item.get("name") == asset.get("name"):
                return parse_digest(item.get("digest"))
    except Exception as exc:  # noqa: BLE001 - no digest is the answer
        log.info(f"[Integrity] The release's digest could not be read from the API: {exc}")
    return None


def expected_sha256(release: dict, asset: dict, timeout: float = 20) -> Optional[str]:
    """The SHA-256 GitHub publishes for the update package `asset` of `release`, or None.

    The API's asset digest when the release came from the API; else SHA256SUMS (github.com,
    outside the API's hourly limit); else the API's listing of that release.
    """
    digest = parse_digest(asset.get("digest"))
    if digest:
        return digest
    digest = _from_sums(release, asset, timeout)
    if digest:
        return digest
    if "digest" not in asset:  # an API listing without a digest has none to give
        digest = _from_api(release, asset, timeout)
    if not digest:
        log.warning(f"[Integrity] No SHA-256 published for {asset.get('name')}: the update is not installed")
    return digest


# ---- checking the package ----

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected: Optional[str]) -> bool:
    """`path` holds exactly the package whose SHA-256 is `expected`."""
    if not expected:
        return False
    try:
        actual = sha256_file(path)
    except OSError as exc:
        log.warning(f"[Integrity] Could not read {path}: {exc}")
        return False
    if actual != expected.lower():
        log.warning(f"[Integrity] {path.name}: SHA-256 {actual}, expected {expected.lower()}")
        return False
    return True


def take_verified(source: Path, target: Path, expected: Optional[str]) -> bool:
    """Copy `source` (the background download, in a folder the user can write to) to `target`
    in the workspace, checking the bytes written; `source` is deleted either way."""
    ok = False
    try:
        if expected:
            target.unlink(missing_ok=True)
            digest = hashlib.sha256()
            with open(source, "rb") as reader, open(target, "xb") as writer:
                for chunk in iter(lambda: reader.read(CHUNK), b""):
                    digest.update(chunk)
                    writer.write(chunk)
            ok = digest.hexdigest() == expected.lower()
            if not ok:
                log.warning("[Integrity] The background download does not match the release: downloading again")
    except OSError as exc:
        log.warning(f"[Integrity] Could not copy the background download: {exc}")
    finally:
        if not ok:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass
    return ok


# ---- the update workspace: administrators only ----

# Owner Administrators; protected (nothing inherited from the parent); administrators and
# SYSTEM full control, users and app packages read and run (Program Files' defaults)
WORKSPACE_SDDL = "O:BAD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)(A;OICI;0x1200a9;;;AC)"
_ADMIN_SIDS = {"SY", "BA", "S-1-5-18", "S-1-5-32-544"}
_READ_RUN = 0x1200A9 | 0x80000000 | 0x20000000  # read + execute, generic read + generic execute
_READ_RUN_NAMES = {"FR", "FX", "GR", "GX"}


def dacl_is_admin_only(sddl: str) -> bool:
    """`sddl` (owner and DACL) leaves changes to administrators and SYSTEM only."""
    owner = re.search(r"O:([A-Z]{2}|S-[0-9-]+)", sddl)
    dacl = re.search(r"D:([A-Z]*)((?:\([^)]*\))*)", sddl)
    if not owner or owner.group(1) not in _ADMIN_SIDS or not dacl or "P" not in dacl.group(1):
        return False
    aces = re.findall(r"\(([^)]*)\)", dacl.group(2))
    if not aces:
        return False
    for ace in aces:
        fields = ace.split(";")
        if len(fields) < 6:
            return False
        kind, rights, sid = fields[0], fields[2], fields[5]
        if kind == "D" or sid in _ADMIN_SIDS:
            continue  # a deny entry, or an administrator's
        if kind != "A":
            return False
        if rights.lower().startswith("0x"):
            if int(rights, 16) & ~_READ_RUN:
                return False
        elif not rights or len(rights) % 2 or any(
                rights[i:i + 2] not in _READ_RUN_NAMES for i in range(0, len(rights), 2)):
            return False
    return True


def _windows() -> bool:
    return os.name == "nt"


def _elevated() -> bool:
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _has_acls(path: Path) -> bool:
    """The volume keeps access lists (NTFS, ReFS); FAT and exFAT don't."""
    import ctypes
    from ctypes import wintypes
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        volume = ctypes.create_unicode_buffer(261)
        if not kernel.GetVolumePathNameW(str(path), volume, 261):
            return True
        flags = wintypes.DWORD()
        if not kernel.GetVolumeInformationW(volume, None, 0, None, None, ctypes.byref(flags), None, 0):
            return True
        return bool(flags.value & 0x8)  # FILE_PERSISTENT_ACLS
    except Exception:  # noqa: BLE001 - assume access lists, so a failure to set them stops the update
        return True


def _security_api():
    """advapi32 and kernel32 with the signatures the calls below need."""
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer, out = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, out, ctypes.POINTER(wintypes.ULONG)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorOwner.argtypes = [pointer, out, ctypes.POINTER(wintypes.BOOL)]
    advapi.GetSecurityDescriptorOwner.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorDacl.argtypes = [
        pointer, ctypes.POINTER(wintypes.BOOL), out, ctypes.POINTER(wintypes.BOOL)]
    advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, pointer, pointer, pointer, pointer]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, out, out, out, out, out]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        pointer, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    return advapi, kernel


def _set_security(path: Path, sddl: str) -> None:
    """Replace the owner and the whole access list of `path` (advapi32, no extra process)."""
    import ctypes
    from ctypes import wintypes
    advapi, kernel = _security_api()
    descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise OSError(f"invalid security descriptor ({ctypes.get_last_error()})")
    try:
        owner, dacl = ctypes.c_void_p(), ctypes.c_void_p()
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        if not advapi.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)) or \
                not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl),
                                                     ctypes.byref(defaulted)):
            raise OSError(f"could not read the security descriptor ({ctypes.get_last_error()})")
        # OWNER | DACL | PROTECTED_DACL: inherited entries of the parent are dropped
        error = advapi.SetNamedSecurityInfoW(str(path), 1, 0x1 | 0x4 | 0x80000000,
                                             owner, None, dacl, None)
        if error:
            raise OSError(f"could not restrict {path} to administrators (error {error})")
    finally:
        kernel.LocalFree(descriptor)


def _get_security(path: Path) -> str:
    """The owner and access list of `path`, as SDDL."""
    import ctypes
    advapi, kernel = _security_api()
    descriptor = ctypes.c_void_p()
    error = advapi.GetNamedSecurityInfoW(str(path), 1, 0x1 | 0x4, None, None, None, None,
                                         ctypes.byref(descriptor))
    if error:
        raise OSError(f"could not read the access list of {path} (error {error})")
    try:
        text = ctypes.c_wchar_p()
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 0x1 | 0x4, ctypes.byref(text), None):
            raise OSError(f"could not read the access list of {path} ({ctypes.get_last_error()})")
        try:
            return text.value or ""
        finally:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.LocalFree(descriptor)


def secure_workspace(root: Path) -> None:
    """Let only administrators and SYSTEM change the update workspace `root`; raise OSError
    when that fails (the update is not installed then).

    Program Files gives it that already; an install elsewhere (C:\\Games) may not, and a
    workspace left from before may carry other entries. Only an elevated Parasite has
    something to protect (and the right to): an ordinary one installs nothing in Program Files.
    """
    if not _windows() or not _elevated():
        return
    if not _has_acls(root):
        log.warning(f"[Integrity] {root} is on a volume without access lists: it can't be restricted")
        return
    _set_security(root, WORKSPACE_SDDL)
    current = _get_security(root)
    if not dacl_is_admin_only(current):
        raise OSError(f"the update folder {root} is not restricted to administrators: {current}")
