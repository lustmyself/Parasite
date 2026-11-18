import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from launcher import parasite_rose


def _proc(name, exe):
    proc = MagicMock()
    proc.info = {"name": name, "exe": exe}
    return proc


class RoseProcessTests(unittest.TestCase):
    """Only a Rose.exe started from where Rose is installed is closed, not any program named rose.exe"""

    def setUp(self):
        self.rose_dir = Path(os.sep, "Apps", "Rose")
        self.registry = [{"UninstallString": f'"{self.rose_dir / "unins000.exe"}"', "InstallLocation": ""}]
        for patcher in (
            patch.object(parasite_rose, "_registry_entries", side_effect=lambda: list(self.registry)),
            patch.dict("os.environ", {"ProgramFiles": str(Path(os.sep, "PF"))}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_guard(self, procs):
        with patch.object(parasite_rose.psutil, "process_iter", return_value=procs):
            return parasite_rose._close_rose()

    def test_rose_from_its_install_folder_is_closed(self):
        rose = _proc("Rose.exe", str(self.rose_dir / "Rose.exe"))
        self.assertTrue(self.run_guard([rose]))
        rose.terminate.assert_called_once()

    def test_rose_in_the_default_folder_is_closed(self):
        self.registry = []
        rose = _proc("rose.exe", str(Path(os.sep, "PF", "Rose", "Rose.exe")))
        self.assertTrue(self.run_guard([rose]))
        rose.terminate.assert_called_once()

    def test_other_programs_named_rose_are_left_alone(self):
        other = _proc("rose.exe", str(Path(os.sep, "Games", "Rose Garden", "rose.exe")))
        hidden = _proc("rose.exe", None)  # its path can't be read
        unrelated = _proc("Parasite.exe", str(self.rose_dir / "Parasite.exe"))
        self.assertFalse(self.run_guard([other, hidden, unrelated]))
        for proc in (other, hidden, unrelated):
            proc.terminate.assert_not_called()

    def test_install_location_counts_as_rose(self):
        self.registry = [{"UninstallString": "", "InstallLocation": str(Path(os.sep, "D", "Rose2"))}]
        rose = _proc("Rose.exe", str(Path(os.sep, "D", "Rose2", "Rose.exe")))
        self.assertTrue(self.run_guard([rose]))

    def test_status_reports_only_rose_installs_as_running(self):
        other = _proc("rose.exe", str(Path(os.sep, "Games", "rose.exe")))
        with patch.object(parasite_rose.psutil, "process_iter", return_value=[other]), \
                patch.object(parasite_rose, "_folder", return_value=None):
            self.assertFalse(parasite_rose.status()["running"])


if __name__ == "__main__":
    unittest.main()
