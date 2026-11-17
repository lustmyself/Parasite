import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import requests

from launcher import parasite_integrity as integrity
from launcher.update import update_installer, update_sequence
from launcher.update.update_sequence import UpdateSequence

PACKAGE = b"PK the published update package"
SHA = hashlib.sha256(PACKAGE).hexdigest()
BASE = "https://github.com/lustmyself/Parasite/releases/download/v2.12/"
ASSET = {"name": "update_package_2.12.zip", "browser_download_url": BASE + "update_package_2.12.zip", "size": 1}
RELEASE = {"tag_name": "v2.12", "assets": [dict(ASSET)]}


def _http(status=200, text="", url=None):
    response = MagicMock(status_code=status, text=text)
    response.url = url or BASE + "SHA256SUMS"
    return response


class ExpectedHashTests(unittest.TestCase):
    def test_a_github_digest_is_read(self):
        self.assertEqual(integrity.parse_digest("sha256:" + SHA.upper()), SHA)
        for value in (None, "", "sha1:" + "a" * 40, "sha256:xyz", "sha256:" + SHA[:-1], 5):
            self.assertIsNone(integrity.parse_digest(value))

    def test_sha256sums_in_text_and_binary_mode(self):
        listing = f"{'0' * 64}  Parasite_Setup_2.12.exe\n{SHA} *update_package_2.12.zip\n"
        self.assertEqual(integrity.parse_sums(listing, "update_package_2.12.zip"), SHA)
        self.assertEqual(integrity.parse_sums(f"{SHA}  update_package_2.12.zip", "update_package_2.12.zip"), SHA)
        self.assertIsNone(integrity.parse_sums(listing, "update_package_2.11.zip"))
        self.assertIsNone(integrity.parse_sums("garbage update_package_2.12.zip", "update_package_2.12.zip"))

    def test_the_api_digest_needs_no_request(self):
        with patch.object(integrity.requests, "get") as get:
            self.assertEqual(integrity.expected_sha256(RELEASE, dict(ASSET, digest="sha256:" + SHA)), SHA)
        get.assert_not_called()

    def test_sha256sums_beside_the_package_when_there_is_no_digest(self):
        # The redirect check (no API call) knows only the package's URL
        with patch.object(integrity.requests, "get", return_value=_http(text=f"{SHA}  {ASSET['name']}\n")) as get:
            self.assertEqual(integrity.expected_sha256({"tag_name": "v2.12", "assets": [ASSET]}, ASSET), SHA)
        self.assertEqual(get.call_args.args[0], BASE + "SHA256SUMS")

    def test_a_listed_sha256sums_asset_is_preferred(self):
        sums = {"name": "SHA256SUMS", "browser_download_url": BASE + "SHA256SUMS?listed"}
        release = {"tag_name": "v2.12", "assets": [ASSET, sums]}
        with patch.object(integrity.requests, "get", return_value=_http(text=f"{SHA}  {ASSET['name']}")) as get:
            self.assertEqual(integrity.expected_sha256(release, dict(ASSET, digest=None)), SHA)
        self.assertEqual(get.call_args.args[0], BASE + "SHA256SUMS?listed")

    def test_without_sha256sums_the_api_listing_of_the_tag_gives_the_digest(self):
        api = MagicMock(status_code=200)
        api.json.return_value = {"assets": [dict(ASSET, digest="sha256:" + SHA)]}
        with patch.object(integrity.requests, "get", return_value=_http(status=404)), \
                patch("utils.download.github_rate_limit.api_get", return_value=api) as api_get:
            self.assertEqual(integrity.expected_sha256(RELEASE, ASSET), SHA)
        self.assertTrue(api_get.call_args.args[0].endswith("/repos/lustmyself/Parasite/releases/tags/v2.12"))

    def test_no_published_hash_is_no_hash(self):
        with patch.object(integrity.requests, "get", side_effect=requests.ConnectionError("offline")), \
                patch("utils.download.github_rate_limit.api_get", return_value=None):
            self.assertIsNone(integrity.expected_sha256(RELEASE, ASSET))
        # An API listing without a digest: asking the API again gives nothing more
        with patch.object(integrity.requests, "get", return_value=_http(status=404)), \
                patch("utils.download.github_rate_limit.api_get") as api_get:
            self.assertIsNone(integrity.expected_sha256(RELEASE, dict(ASSET, digest=None)))
        api_get.assert_not_called()

    def test_sha256sums_only_from_github_over_https(self):
        for url in ("http://github.com/lustmyself/Parasite/releases/download/v2.12/u.zip",
                    "https://evil.example/lustmyself/Parasite/releases/download/v2.12/u.zip"):
            with patch.object(integrity.requests, "get") as get, \
                    patch("utils.download.github_rate_limit.api_get", return_value=None):
                self.assertIsNone(integrity.expected_sha256({}, {"name": "u.zip", "browser_download_url": url}))
            get.assert_not_called()
        # Redirected off HTTPS: not trusted
        with patch.object(integrity.requests, "get", return_value=_http(text=f"{SHA}  {ASSET['name']}",
                                                                        url="http://mirror/SHA256SUMS")), \
                patch("utils.download.github_rate_limit.api_get", return_value=None):
            self.assertIsNone(integrity.expected_sha256(RELEASE, ASSET))


class PackageCheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.source = self.dir / "user" / "update_package_2.12.zip"
        self.source.parent.mkdir()
        self.target = self.dir / "Parasite.update" / "package.zip"
        self.target.parent.mkdir()

    def test_verify_file(self):
        self.source.write_bytes(PACKAGE)
        self.assertTrue(integrity.verify_file(self.source, SHA))
        self.assertTrue(integrity.verify_file(self.source, SHA.upper()))
        self.assertFalse(integrity.verify_file(self.source, "0" * 64))
        self.assertFalse(integrity.verify_file(self.source, None))
        self.assertFalse(integrity.verify_file(self.dir / "missing.zip", SHA))

    def test_the_background_download_is_copied_and_checked(self):
        self.source.write_bytes(PACKAGE)
        self.target.write_bytes(b"left from before")
        self.assertTrue(integrity.take_verified(self.source, self.target, SHA))
        self.assertEqual(self.target.read_bytes(), PACKAGE)
        self.assertFalse(self.source.exists())

    def test_a_swapped_background_download_is_refused(self):
        self.source.write_bytes(PACKAGE + b"planted")
        self.assertFalse(integrity.take_verified(self.source, self.target, SHA))
        self.assertFalse(self.target.exists())
        self.assertFalse(self.source.exists())
        self.source.write_bytes(PACKAGE)
        self.assertFalse(integrity.take_verified(self.source, self.target, None))
        self.assertFalse(self.target.exists())


class WorkspaceAclTests(unittest.TestCase):
    def test_the_workspace_descriptor_is_admin_only(self):
        self.assertTrue(integrity.dacl_is_admin_only(integrity.WORKSPACE_SDDL))
        # As Windows reads it back (inherited flags, numeric SIDs, FR/FX names)
        self.assertTrue(integrity.dacl_is_admin_only(
            "O:BAD:PAI(A;OICI;FA;;;S-1-5-18)(A;OICIID;FA;;;BA)(A;OICI;FRFX;;;BU)(D;;FA;;;WD)"))

    def test_anything_users_could_change_is_refused(self):
        for sddl in (
            "O:BAD:AI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)",  # not protected: the parent's entries come in
            "O:S-1-5-21-1-2-3-1001D:PAI(A;OICI;FA;;;BA)",  # a user owns it (and may rewrite the list)
            "O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;BU)",
            "O:BAD:PAI(A;OICI;0x1301bf;;;AU)",  # modify
            "O:BAD:PAI(A;OICI;FW;;;S-1-5-21-1-2-3-1001)",
            "O:BAD:PAI(OA;;FA;;;BU)",
            "O:BAD:PAI",  # no entries: nothing to check
            "O:BAD:PAI(A;OICI;GA;;;CO)",
            "",
        ):
            self.assertFalse(integrity.dacl_is_admin_only(sddl), sddl)

    def test_an_elevated_parasite_restricts_and_checks_it(self):
        root = Path("C:/Program Files/Parasite.update")
        with patch.object(integrity, "_windows", return_value=True), \
                patch.object(integrity, "_elevated", return_value=True), \
                patch.object(integrity, "_has_acls", return_value=True), \
                patch.object(integrity, "_set_security") as set_security, \
                patch.object(integrity, "_get_security", return_value=integrity.WORKSPACE_SDDL):
            integrity.secure_workspace(root)
        set_security.assert_called_once_with(root, integrity.WORKSPACE_SDDL)

    def test_a_workspace_left_open_stops_the_update(self):
        with patch.object(integrity, "_windows", return_value=True), \
                patch.object(integrity, "_elevated", return_value=True), \
                patch.object(integrity, "_has_acls", return_value=True), \
                patch.object(integrity, "_set_security"), \
                patch.object(integrity, "_get_security", return_value="O:BAD:PAI(A;OICI;FA;;;BU)"):
            with self.assertRaises(OSError):
                integrity.secure_workspace(Path("C:/Parasite.update"))
        with patch.object(integrity, "_windows", return_value=True), \
                patch.object(integrity, "_elevated", return_value=True), \
                patch.object(integrity, "_has_acls", return_value=True), \
                patch.object(integrity, "_set_security", side_effect=OSError("error 5")):
            with self.assertRaises(OSError):
                integrity.secure_workspace(Path("C:/Parasite.update"))

    def test_nothing_to_restrict_off_windows_unelevated_or_on_fat(self):
        cases = [(False, True, True), (True, False, True), (True, True, False)]
        for windows, elevated, acls in cases:
            with patch.object(integrity, "_windows", return_value=windows), \
                    patch.object(integrity, "_elevated", return_value=elevated), \
                    patch.object(integrity, "_has_acls", return_value=acls), \
                    patch.object(integrity, "_set_security") as set_security:
                integrity.secure_workspace(Path("C:/Parasite.update"))
            set_security.assert_not_called()

    def test_the_installer_workspace_is_restricted_before_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "Parasite"
            install.mkdir()
            with patch.object(integrity, "secure_workspace") as secure:
                root = update_installer.UpdateInstaller().workspace(install)
            secure.assert_called_once_with(root)
            with patch.object(integrity, "secure_workspace", side_effect=OSError("not restricted")):
                with self.assertRaises(OSError):
                    update_installer.UpdateInstaller().workspace(install)


class UpdateSequenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.install_dir = self.dir / "Parasite"
        self.install_dir.mkdir()
        self.workspace = self.dir / "Parasite.update"
        self.workspace.mkdir()
        self.sequence = UpdateSequence.__new__(UpdateSequence)
        self.sequence.github_client = Mock()
        self.sequence.downloader = Mock()
        self.sequence.installer = Mock()
        self.sequence.installer.workspace.return_value = self.workspace
        self.extracted = self.dir / "staging"
        self.sequence.installer.extract_update.side_effect = self.extract
        self.sequence.installer.install.return_value = True
        self.extracted_from = []
        self.statuses = []

    def extract(self, zip_path, *rest):
        self.extracted_from.append((zip_path, zip_path.read_bytes()))
        return self.extracted

    def download(self, data):
        self.sequence.downloader.download_update.side_effect = lambda url, path, *rest: path.write_bytes(data) or True

    def prepare(self, asset, background=None):
        with patch.object(update_sequence.sys, "executable", str(self.install_dir / "Parasite.exe")), \
                patch("launcher.parasite_autoupdate.predownloaded", return_value=background):
            return self.sequence._prepare_update({}, "2.12", asset, self.statuses.append, Mock(), None)

    def test_the_downloaded_package_is_checked_before_it_is_extracted(self):
        self.download(PACKAGE)
        self.assertTrue(self.prepare(dict(ASSET, sha256=SHA)))
        self.assertEqual(self.extracted_from, [(self.workspace / "package.zip", PACKAGE)])

    def test_a_package_that_is_not_the_published_one_is_not_extracted(self):
        self.download(PACKAGE + b"tampered")
        self.assertFalse(self.prepare(dict(ASSET, sha256=SHA)))
        self.assertEqual(self.extracted_from, [])
        self.assertFalse((self.workspace / "package.zip").exists())
        self.assertEqual(self.statuses[-1], integrity.BAD_HASH)

    def test_no_hash_no_install(self):
        self.download(PACKAGE)
        self.assertFalse(self.prepare(dict(ASSET)))
        self.sequence.downloader.download_update.assert_not_called()
        self.assertEqual(self.statuses[-1], integrity.NO_HASH)

    def test_the_background_package_is_extracted_from_the_workspace_copy(self):
        background = self.dir / "LocalAppData" / ASSET["name"]
        background.parent.mkdir()
        background.write_bytes(PACKAGE)
        self.assertTrue(self.prepare(dict(ASSET, sha256=SHA), background))
        self.sequence.downloader.download_update.assert_not_called()
        self.assertEqual(self.extracted_from, [(self.workspace / "package.zip", PACKAGE)])
        self.assertFalse(background.exists())

    def test_a_swapped_background_package_is_downloaded_again(self):
        background = self.dir / "LocalAppData" / ASSET["name"]
        background.parent.mkdir()
        background.write_bytes(b"planted by another program")
        self.download(PACKAGE)
        self.assertTrue(self.prepare(dict(ASSET, sha256=SHA), background))
        self.sequence.downloader.download_update.assert_called_once()
        self.assertEqual(self.extracted_from, [(self.workspace / "package.zip", PACKAGE)])

    def test_a_release_without_a_published_hash_is_not_offered(self):
        client = self.sequence.github_client
        client.get_latest_release.return_value = RELEASE
        client.get_release_version.return_value = "v99.0"
        client.get_zip_asset.return_value = dict(ASSET)
        confirm = Mock(return_value=True)
        with patch.object(update_sequence.sys, "frozen", True, create=True), \
                patch.object(update_sequence, "APP_VERSION", "2.11"), \
                patch("launcher.parasite_integrity.expected_sha256", return_value=None):
            self.assertFalse(self.sequence.perform_update(self.statuses.append, Mock(), confirm_callback=confirm))
        confirm.assert_not_called()
        self.assertEqual(self.statuses[-1], integrity.NO_HASH)


if __name__ == "__main__":
    unittest.main()
