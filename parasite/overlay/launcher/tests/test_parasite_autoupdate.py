import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from launcher import parasite_autoupdate as auto


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Parasite.exe", b"x" * 100)
    return buffer.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _response(data: bytes):
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [data]
    return response


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = patch.object(auto, "_updates_dir", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        auto._pending = None

    def test_a_complete_download_is_ready(self):
        target = self.dir / "update_package_9.zip"
        data = _zip_bytes()
        with patch.object(auto.requests, "get", return_value=_response(data)):
            self.assertTrue(auto._download("https://x", target, len(data), _sha(data)))
        self.assertTrue(auto.is_ready(target))
        self.assertTrue(auto.is_ready(target, _sha(data)))
        self.assertFalse(auto.is_ready(target, _sha(b"another package")))
        target.write_bytes(data + b"more")  # changed afterwards: not the package that was checked
        self.assertFalse(auto.is_ready(target))

    def test_a_damaged_or_short_download_is_dropped(self):
        target = self.dir / "update_package_9.zip"
        with patch.object(auto.requests, "get", return_value=_response(b"not a zip")):
            self.assertFalse(auto._download("https://x", target, 0, _sha(b"not a zip")))
        data = _zip_bytes()
        with patch.object(auto.requests, "get", return_value=_response(data)):
            self.assertFalse(auto._download("https://x", target, len(data) + 5, _sha(data)))
        self.assertFalse(target.exists())
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_the_update_sequence_takes_the_background_package(self):
        data = _zip_bytes()
        asset = {"name": "update_package_9.zip", "browser_download_url": "https://x", "size": 0, "sha256": _sha(data)}
        self.assertIsNone(auto.predownloaded(asset, "v9"))
        with patch.object(auto.requests, "get", return_value=_response(data)):
            self.assertTrue(auto._download("https://x", self.dir / "update_package_9.zip", len(data), _sha(data)))
        self.assertEqual(auto.predownloaded(asset, "v9"), self.dir / "update_package_9.zip")
        # Taken once: the update sequence deletes the package after extracting it
        self.assertFalse(auto.ready_path(self.dir / "update_package_9.zip").exists())

    def test_a_download_that_is_not_the_published_package_is_dropped(self):
        target = self.dir / "update_package_9.zip"
        data = _zip_bytes()
        with patch.object(auto.requests, "get", return_value=_response(data)):
            self.assertFalse(auto._download("https://x", target, len(data), _sha(b"the published one")))
            # Without a published SHA-256 nothing is downloaded at all
            self.assertFalse(auto._download("https://x", target, len(data), None))
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_package_changed_after_its_download_is_not_handed_over(self):
        data = _zip_bytes()
        target = self.dir / "update_package_9.zip"
        with patch.object(auto.requests, "get", return_value=_response(data)):
            self.assertTrue(auto._download("https://x", target, len(data), _sha(data)))
        swapped = bytearray(data)
        swapped[-1] ^= 1  # same size: only the SHA-256 tells them apart
        target.write_bytes(bytes(swapped))
        asset = {"name": target.name, "browser_download_url": "https://x", "sha256": _sha(data)}
        self.assertIsNone(auto.predownloaded(asset, "v9"))

    def test_a_release_without_a_published_sha256_is_retried_later(self):
        with patch.object(auto, "_download", return_value=True) as download, \
                patch.object(auto, "enabled", return_value=True), \
                patch("launcher.parasite_integrity.expected_sha256", return_value=None), \
                patch.object(auto.threading, "Thread"), patch("launcher.parasite_hub.toast"):
            auto.on_release(self._client("1.4.9.9"), {}, "1.4.9.5")
        download.assert_not_called()
        self.assertIsNone(auto.pending())
        with patch.object(auto, "_download", return_value=True) as download, \
                patch.object(auto, "enabled", return_value=True), \
                patch("launcher.parasite_integrity.expected_sha256", return_value="ab" * 32), \
                patch.object(auto.threading, "Thread"), patch("launcher.parasite_hub.toast"):
            auto.on_release(self._client("1.4.9.9"), {}, "1.4.9.5")
        download.assert_called_once()
        self.assertEqual(download.call_args.args[3], "ab" * 32)
        self.assertEqual(auto.pending(), "1.4.9.9")

    def test_parasite_offline_keeps_the_install_waiting(self):
        self.assertIn("parasiteoffline.exe", auto.LEAGUE)

    def _client(self, version):
        client = MagicMock()
        client.get_release_version.return_value = f"v{version}"
        client.get_zip_asset.return_value = {"name": f"update_package_{version}.zip",
                                             "browser_download_url": "https://x", "size": 0}
        return client

    def test_only_newer_releases_download_and_only_when_on(self):
        with patch.object(auto, "_download", return_value=True) as download, \
                patch.object(auto, "enabled", return_value=True), \
                patch("launcher.parasite_integrity.expected_sha256", return_value="ab" * 32), \
                patch.object(auto.threading, "Thread"), patch("launcher.parasite_hub.toast"):
            auto.on_release(self._client("1.4.9.1"), {}, "1.4.9.5")
            download.assert_not_called()
            auto.on_release(self._client("1.4.9.9"), {}, "1.4.9.5")
            download.assert_called_once()
            self.assertEqual(auto.pending(), "1.4.9.9")
        auto._pending = None
        with patch.object(auto, "_download") as download, patch.object(auto, "enabled", return_value=False):
            auto.on_release(self._client("1.4.9.9"), {}, "1.4.9.5")
            download.assert_not_called()

    def test_installs_only_after_league_was_closed_twice(self):
        auto._pending = "1.4.9.9"
        states = iter([True, False, True, False, False])
        with patch.object(auto, "_league_running", side_effect=lambda: next(states)), \
                patch.object(auto, "enabled", return_value=True), patch.object(auto, "IDLE_CHECK_S", 0), \
                patch.object(auto.time, "sleep"), patch("launcher.parasite_hub.toast"), \
                patch("launcher.parasite_hub.run_action") as run:
            auto._install_when_idle()
        run.assert_called_once_with("update")

    def test_a_newer_release_found_while_waiting_is_the_one_installed(self):
        auto._pending = "1.4.9.8"
        toasts = []
        checks = iter([True, True, False, False])

        def league_running():
            running = next(checks)
            if not running:
                auto._pending = "1.4.9.9"  # downloaded meanwhile by another release check
            return running

        with patch.object(auto, "_league_running", side_effect=league_running), \
                patch.object(auto, "enabled", return_value=True), patch.object(auto.time, "sleep"), \
                patch("launcher.parasite_hub.toast", side_effect=toasts.append), \
                patch("launcher.parasite_hub.mark_quiet_restart"), \
                patch("launcher.parasite_hub.run_action") as run:
            auto._install_when_idle()
        run.assert_called_once_with("update")
        self.assertIn("1.4.9.9", toasts[-1])

    def test_a_newer_release_reuses_the_running_waiter(self):
        alive = MagicMock()
        alive.is_alive.return_value = True
        with patch.object(auto, "_download", return_value=True), \
                patch.object(auto, "enabled", return_value=True), \
                patch.object(auto, "_waiter", alive), \
                patch.object(auto.threading, "Thread") as thread, patch("launcher.parasite_hub.toast"):
            auto.on_release(self._client("1.4.9.9"), {}, "1.4.9.5")
            self.assertEqual(auto.pending(), "1.4.9.9")
            thread.assert_not_called()
        with patch.object(auto, "_download", return_value=True), \
                patch.object(auto, "enabled", return_value=True), \
                patch.object(auto, "_waiter", None), \
                patch.object(auto.threading, "Thread") as thread, patch("launcher.parasite_hub.toast"):
            auto.on_release(self._client("1.5.0.0"), {}, "1.4.9.5")
            thread.assert_called_once()
            thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
