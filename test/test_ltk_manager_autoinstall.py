import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as parasite_main
from injection.tools import ltk_manager_install
from injection.tools.tools_manager import LTF_BRIDGE_DLL, LTF_LAUNCHER, ToolsManager


@unittest.skipUnless(sys.platform == "win32", "LTK Manager is a Windows program")
class LtkManagerAutoInstallTests(unittest.TestCase):
    """Without LTK Manager, Parasite finds it in the installed programs or installs
    it itself; the dialog is only for when both fail"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.tools = Path(temp_dir.name)
        for name in (LTF_LAUNCHER, LTF_BRIDGE_DLL):
            (self.tools / name).write_bytes(b"x")
        self.exe = self.tools / "ltk-manager.exe"
        for patcher in (
            # Rose 1.5.6+ reads it from utils.core.paths when the check runs
            patch("utils.core.paths.get_tools_dir", return_value=self.tools),
            patch.object(ToolsManager, "detect_ltk_manager", return_value=None),
            # Never this PC's own cf.ini
            patch("config.set_config_option"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        import config
        self.set_config_option = config.set_config_option

    def check(self, registered=None, installed=None):
        with (
            patch.object(ltk_manager_install, "registered_ltk_manager", return_value=registered),
            patch.object(ltk_manager_install, "install_ltk_manager", return_value=installed) as install,
            patch.object(parasite_main, "_show_dll_dialog", return_value=False) as dialog,
        ):
            return parasite_main._check_dll_present(), install, dialog

    def test_an_installed_ltk_manager_elsewhere_is_found_and_saved(self):
        ok, install, dialog = self.check(registered=self.exe)

        self.assertTrue(ok)
        install.assert_not_called()
        dialog.assert_not_called()
        self.set_config_option.assert_called_once_with("General", "ltkManagerPath", str(self.exe))

    def test_a_missing_ltk_manager_is_installed(self):
        ok, install, dialog = self.check(installed=self.exe)

        self.assertTrue(ok)
        install.assert_called_once()
        dialog.assert_not_called()
        self.set_config_option.assert_called_once_with("General", "ltkManagerPath", str(self.exe))

    def test_the_dialog_shows_when_the_install_fails(self):
        ok, _, dialog = self.check()

        self.assertFalse(ok)
        dialog.assert_called_once()
        self.set_config_option.assert_not_called()


class InstallerSourceTests(unittest.TestCase):
    def test_the_installer_comes_from_ltk_managers_own_releases(self):
        self.assertTrue(ltk_manager_install.INSTALLER_URL.startswith(
            "https://github.com/LeagueToolkit/ltk-manager/releases/latest/download/"))

    def test_nothing_is_installed_off_windows(self):
        with patch.object(ltk_manager_install.sys, "platform", "linux"):
            self.assertIsNone(ltk_manager_install.install_ltk_manager(lambda: None))
            self.assertIsNone(ltk_manager_install.registered_ltk_manager())


class SignatureTests(unittest.TestCase):
    """The installer runs as administrator: its signature must be valid and LTK Manager's own"""

    def check(self, stdout):
        from unittest.mock import MagicMock
        result = MagicMock(stdout=stdout, stderr="")
        with patch.object(ltk_manager_install.subprocess, "run", return_value=result) as run:
            valid = ltk_manager_install.signature_is_valid(Path("setup.exe"))
        return valid, run.call_args[0][0]

    def test_ltk_managers_signer_is_accepted(self):
        self.assertTrue(self.check("Valid\r\nCN=Natoken LLC, O=Natoken LLC, L=Austin, S=Texas, C=US\r\n")[0])

    def test_a_valid_signature_from_anybody_else_is_refused(self):
        for subject in ("CN=Evil Corp, O=Evil Corp, C=US", "CN=Natoken LLC, O=Someone Else", "",
                        'CN="Natoken LLC, O=Natoken LLC", O=Evil'):
            with self.subTest(subject=subject):
                self.assertFalse(self.check(f"Valid\n{subject}\n")[0])

    def test_an_invalid_signature_is_refused(self):
        for status in ("NotSigned", "HashMismatch", "UnknownError", ""):
            with self.subTest(status=status):
                self.assertFalse(self.check(f"{status}\nCN=Natoken LLC, O=Natoken LLC\n")[0])

    def test_powershell_is_run_by_its_full_path(self):
        _, command = self.check("Valid\nCN=Natoken LLC, O=Natoken LLC\n")
        self.assertTrue(Path(command[0]).is_absolute() or command[0].startswith("C:\\"))
        self.assertTrue(command[0].replace("/", "\\").lower().endswith(
            "\\system32\\windowspowershell\\v1.0\\powershell.exe"))

    def test_powershell_ignores_a_systemroot_set_by_the_user(self):
        with patch.dict("os.environ", {"SystemRoot": r"C:\Users\me\fake", "windir": r"C:\Users\me\fake"}):
            self.assertNotIn("fake", ltk_manager_install.powershell_exe())


if __name__ == "__main__":
    unittest.main()
