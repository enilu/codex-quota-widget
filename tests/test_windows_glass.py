"""Offline reader lifecycle checks for the Qt UI; never reads real login data."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from windows_glass import GlassWidget
    from quota import QuotaError


@unittest.skipUnless(HAS_QT, "Optional Windows Qt dependency is not installed")
class GlassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.material = patch("windows_glass.acrylic", return_value=False)
        self.material.start()
        self.widget = GlassWidget(Path("synthetic-home"), demo=True)
        self.widget.timer.stop()

    def tearDown(self):
        self.widget.close()
        self.material.stop()

    def test_demo_refresh_does_not_spawn_reader_or_read_login(self):
        with patch("windows_glass.subprocess.Popen", side_effect=AssertionError("No reader in demo")), \
             patch("windows_glass.quota.auth", side_effect=AssertionError("No login in demo")):
            self.widget.refresh()
            self.widget.tick()
        self.assertIsNone(self.widget.process)

    def test_timeout_reaps_reader_and_drops_old_account_snapshot(self):
        process = MagicMock()
        process.poll.return_value = None
        process.communicate.return_value = (b"", b"")
        self.widget.process = process
        self.widget.started = 0
        with patch("windows_glass.time.monotonic", return_value=36), \
             patch("windows_glass.quota.read_cache", side_effect=QuotaError("account changed")):
            self.widget.poll_reader()
        process.kill.assert_called_once()
        process.communicate.assert_called_once()
        self.assertIsNone(self.widget.process)
        self.assertNotIn("remaining", self.widget.data)
        self.assertIn("超时", self.widget.data["error"])

    def test_closing_reaps_active_reader(self):
        process = MagicMock()
        self.widget.process = process
        self.widget.close()
        process.kill.assert_called_once()
        process.communicate.assert_called_once()
        self.assertIsNone(self.widget.process)


if __name__ == "__main__":
    unittest.main()
