import os
import tempfile
import unittest
from unittest import mock

from ajazzctl import desktop


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {"XDG_CONFIG_HOME": f"{self.tmp.name}/cfg", "XDG_DATA_HOME": f"{self.tmp.name}/data",
               "XDG_DATA_DIRS": f"{self.tmp.name}/sys"}
        self.patch = mock.patch.dict(os.environ, env)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_autostart_roundtrip(self):
        self.assertFalse(desktop.autostart_enabled())
        desktop.set_autostart(True)
        text = desktop.autostart_path().read_text()
        self.assertIn("--hidden", text)
        self.assertIn("Icon=io.github.ajazzctl", text)
        self.assertTrue(desktop.autostart_enabled())
        desktop.set_autostart(False)
        self.assertFalse(desktop.autostart_enabled())

    def test_user_integration_written_once(self):
        self.assertTrue(desktop.ensure_user_integration())
        self.assertFalse(desktop.ensure_user_integration())   # idempotent
        entry = os.path.join(self.tmp.name, "data/applications/io.github.ajazzctl.desktop")
        self.assertIn("StartupWMClass=io.github.ajazzctl", open(entry).read())

    def test_user_copy_removed_once_system_installed(self):
        desktop.ensure_user_integration()                       # source-checkout run
        user_entry = os.path.join(self.tmp.name, "data/applications/io.github.ajazzctl.desktop")
        self.assertTrue(os.path.exists(user_entry))
        sysapp = os.path.join(self.tmp.name, "sys/applications")
        os.makedirs(sysapp)
        open(os.path.join(sysapp, "io.github.ajazzctl.desktop"), "w").close()
        self.assertTrue(desktop.ensure_user_integration())      # package now installed
        self.assertFalse(os.path.exists(user_entry))
        self.assertFalse(desktop.ensure_user_integration())


if __name__ == "__main__":
    unittest.main()
