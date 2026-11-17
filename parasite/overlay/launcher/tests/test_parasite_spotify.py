import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import parasite_spotify as spotify


class ReapplyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exe = self.root / "Spotify.exe"
        self.exe.write_bytes(b"v1")
        for target, value in (("get_user_data_dir", self.root), ("spotify_exe", self.exe)):
            patcher = patch.object(spotify, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_applies_again_only_after_spotify_changed(self):
        spotify._save({"theme": "parasite", "auto": True, "marker": spotify._marker(self.exe)})
        with patch.object(spotify, "_run") as run:
            self.assertIsNone(spotify.reapply_if_updated())
            run.assert_not_called()
            self.exe.write_bytes(b"version two")
            self.assertTrue(spotify.reapply_if_updated())
            run.assert_called_once_with("apply")
            self.assertIsNone(spotify.reapply_if_updated())  # marker updated

    def test_nothing_without_a_theme_or_with_auto_off(self):
        self.exe.write_bytes(b"changed")
        with patch.object(spotify, "_run") as run:
            spotify._save({"theme": "", "auto": True, "marker": "old"})
            self.assertIsNone(spotify.reapply_if_updated())
            spotify._save({"theme": "parasite", "auto": False})
            self.assertIsNone(spotify.reapply_if_updated())
            run.assert_not_called()

    def test_patch_falls_back_to_backup_then_restore(self):
        calls = []

        def run(*args):
            calls.append(args)
            if args != ("restore", "backup", "apply"):
                raise RuntimeError("Please restore first then backup")
        with patch.object(spotify, "_run", side_effect=run):
            spotify._patch()
        self.assertEqual(calls, [("apply",), ("backup", "apply"), ("restore", "backup", "apply")])

    def test_unknown_theme_is_ignored(self):
        self.assertEqual(spotify.apply("../evil"), "")


def _zip(files):
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class CliDownloadTests(unittest.TestCase):
    """The elevated app runs Spicetify's CLI: it is verified and kept out of the user's data folder"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.app = self.root / "app"
        self.data = self.root / "data"
        self.app.mkdir()
        self.data.mkdir()
        for target, value in (("get_app_dir", self.app), ("get_user_data_dir", self.data)):
            patcher = patch.object(spotify, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.archive = _zip({"spicetify.exe": b"MZ cli", "jsHelper/a.js": b"x"})

    def serve(self, digest):
        import hashlib
        from unittest.mock import MagicMock
        if digest == "right":
            digest = "sha256:" + hashlib.sha256(self.archive).hexdigest()
        release = MagicMock()
        release.json.return_value = {"tag_name": "v9.9.9", "assets": [
            {"name": "spicetify-9.9.9-windows-x64.zip", "browser_download_url": "https://example.invalid/cli.zip",
             **({"digest": digest} if digest else {})}]}
        download = MagicMock(content=self.archive)
        return patch.object(spotify.requests, "get", side_effect=[release, download])

    def test_a_verified_cli_goes_to_the_install_folder(self):
        with self.serve("right"):
            exe = spotify._cli()
        self.assertEqual(exe, self.app / "spicetify" / "spicetify.exe")
        self.assertEqual(exe.read_bytes(), b"MZ cli")
        self.assertFalse((self.data / "spicetify" / "cli").exists())
        self.assertFalse((self.app / "spicetify.new").exists())

    def test_a_download_that_does_not_match_its_digest_is_refused(self):
        with self.serve("sha256:" + "0" * 64), self.assertRaises(RuntimeError):
            spotify._cli()
        self.assertFalse((self.app / "spicetify").exists())
        self.assertFalse((self.app / "spicetify.new").exists())

    def test_a_release_without_a_digest_is_refused(self):
        for digest in (None, "md5:abc", "sha256:nothex"):
            with self.subTest(digest=digest), self.serve(digest), self.assertRaises(RuntimeError):
                spotify._cli()
            self.assertFalse((self.app / "spicetify").exists())

    def test_a_cli_in_the_users_data_folder_is_never_run(self):
        planted = self.data / "spicetify" / "cli" / "spicetify.exe"
        planted.parent.mkdir(parents=True)
        planted.write_bytes(b"planted")
        with self.serve("right"):
            self.assertNotEqual(spotify._cli(), planted)

    def test_an_installed_cli_is_used_without_downloading(self):
        exe = self.app / "spicetify" / "spicetify.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"MZ")
        with patch.object(spotify.requests, "get") as get:
            self.assertEqual(spotify._cli(), exe)
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
