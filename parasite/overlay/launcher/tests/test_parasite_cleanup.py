import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import parasite_cleanup as cleanup
from launcher import parasite_rose


class CleanUpdatesTests(unittest.TestCase):
    def test_old_packages_and_staging_go_newer_ones_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            updates = Path(tmp)
            for name in ("update_package_1.4.9.20.zip", "update_package_1.4.9.20.zip.ready",
                         "update_package_1.4.9.23.zip", "update_package_1.4.9.24.zip",
                         "update_package_1.4.9.24.zip.ready", "notes.txt"):
                (updates / name).write_text("x")
            (updates / "staging").mkdir()
            cleanup.clean_updates(updates, "1.4.9.23")
            self.assertEqual(sorted(p.name for p in updates.iterdir()),
                             ["notes.txt", "update_package_1.4.9.24.zip", "update_package_1.4.9.24.zip.ready"])


class CleanOldInstallsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.here = self.root / "Parasite"
        self.here.mkdir()

    def _run(self, entries):
        deleted = []
        with patch.object(cleanup, "_entries", return_value=iter(entries)), \
                patch.object(cleanup, "_delete_entry", side_effect=lambda view, app_id: deleted.append(app_id)):
            cleanup.clean_old_installs(self.here)
        return deleted

    def test_duplicate_entry_for_this_install_is_removed_files_stay(self):
        (self.here / "Parasite.exe").write_text("x")
        deleted = self._run([(0, "old", {"DisplayName": "Parasite", "InstallLocation": f'"{self.here}"'})])
        self.assertEqual(deleted, ["old"])
        self.assertTrue((self.here / "Parasite.exe").exists())

    def test_a_parasite_copy_elsewhere_goes_with_its_entry(self):
        old = self.root / "Old"
        old.mkdir()
        (old / "Parasite.exe").write_text("x")
        deleted = self._run([(0, "old", {"DisplayName": "Parasite", "InstallLocation": str(old)})])
        self.assertEqual(deleted, ["old"])
        self.assertFalse(old.exists())

    def test_roses_entry_and_folders_with_rose_are_left_alone(self):
        rose = self.root / "Rose"
        rose.mkdir()
        (rose / "Rose.exe").write_text("x")
        (rose / "Parasite.exe").write_text("x")
        deleted = self._run([
            (0, "rose", {"DisplayName": "Rose", "InstallLocation": str(rose)}),
            (0, "mixed", {"DisplayName": "Parasite", "InstallLocation": str(rose)}),
        ])
        self.assertEqual(deleted, [])
        self.assertTrue((rose / "Rose.exe").exists())


class RoseGuardTests(unittest.TestCase):
    def test_takes_back_only_a_hook_that_runs_roses_loader(self):
        with patch("utils.integration.pengu_loader._hook_of_another_loader",
                   return_value=Path(r"C:\Program Files\Rose\_internal\Pengu Loader\core.dll")), \
                patch("utils.integration.pengu_loader.activate", return_value=True) as activate:
            self.assertTrue(parasite_rose._take_back_hook())
            activate.assert_called_once()
        with patch("utils.integration.pengu_loader._hook_of_another_loader",
                   return_value=Path(r"C:\Tools\Pengu Loader\core.dll")), \
                patch("utils.integration.pengu_loader.activate") as activate:
            self.assertFalse(parasite_rose._take_back_hook())
            activate.assert_not_called()



class RetiredPluginTests(unittest.TestCase):
    def test_only_retired_parasite_plugins_go(self):
        import tempfile
        from launcher import parasite_cleanup
        with tempfile.TemporaryDirectory() as folder:
            plugins = Path(folder)
            (plugins / "PARASITE-PartyMode").mkdir()
            (plugins / "PARASITE-PartyMode" / "index.js").write_text("x", encoding="utf-8")
            (plugins / "PARASITE-Theme").mkdir()
            (plugins / "my-own-plugin").mkdir()
            self.assertEqual(parasite_cleanup.clean_retired_plugins(plugins), 1)
            self.assertFalse((plugins / "PARASITE-PartyMode").exists())
            self.assertTrue((plugins / "PARASITE-Theme").exists())
            self.assertTrue((plugins / "my-own-plugin").exists())

if __name__ == "__main__":
    unittest.main()
