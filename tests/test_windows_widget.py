"""Offline Windows display and reader lifecycle regressions; synthetic data only."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows_widget import Widget, countdown, presentation, reader_command
from quota import QuotaError, account_hash


class WindowsTests(unittest.TestCase):
    def data(self, **fields):
        return dict(remaining=60, resetsAt=1800500000, windowSeconds=604800,
                    updatedAt=1800000000, creditExpiries=[], **fields)

    def test_expired_window_never_assumes_restored_quota(self):
        value = presentation(self.data(), 1800500001)
        self.assertEqual(value["percent"], "60%")
        self.assertIn("历史", value["budget"])
        self.assertIn("确认", value["reset"])

    def test_unknown_cards_and_missing_quota_are_not_zero(self):
        self.assertEqual(presentation({}, 1800000000)["percent"], "—")
        value = self.data()
        value["creditExpiries"] = None
        self.assertIn("未知", presentation(value, 1800000000)["cards"])
        self.assertIn("无可用卡", presentation(self.data(), 1800000000)["cards"])

    def test_stale_and_failed_reads_disable_daily_budget(self):
        self.assertIn("历史", presentation(self.data(), 1800000181)["budget"])
        self.assertIn("历史", presentation(self.data(), 1799999939)["budget"])
        value = self.data(error="network")
        self.assertIn("历史", presentation(value, 1800000000)["budget"])

    def test_expired_cards_excluded_and_urgent_cards_flagged(self):
        value = self.data()
        value["creditExpiries"] = [1799999999, 1800000100]
        display = presentation(value, 1800000000)
        self.assertIn("1 张", display["cards"])
        self.assertTrue(display["urgent"])
        self.assertEqual(countdown(-1), "0天 00:00:00")

    def test_cli_custom_home_reads_same_account_cache_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "auth.json").write_text(json.dumps({"tokens": {
                "access_token": "SYNTHETIC_TOKEN", "account_id": "SYNTHETIC_ACCOUNT"}}), encoding="utf-8")
            cache = home / "usage.local.json"
            cache.write_text(json.dumps(self.data(accountHash=account_hash("SYNTHETIC_ACCOUNT"))), encoding="utf-8")
            command = reader_command(cache, home)
            command.remove("--refresh")
            result = subprocess.run(command, capture_output=True, check=True)
            value = json.loads(result.stdout)
            self.assertEqual(value["remaining"], 60)
            self.assertNotIn("accountHash", value)
            self.assertNotIn(b"SYNTHETIC", result.stdout)

    def test_reader_timeout_kills_and_revalidates_account(self):
        widget = Widget.__new__(Widget)
        widget.process = MagicMock()
        process = widget.process
        process.poll.return_value = None
        process.communicate.return_value = (b"", b"")
        widget.started = 0
        widget.cache, widget.home = Path("usage.local.json"), Path("synthetic-home")
        widget.refresh_button = MagicMock()
        widget.data = self.data()
        with patch("windows_widget.time.monotonic", return_value=36), \
             patch("windows_widget.quota.read_cache", side_effect=QuotaError("account changed")):
            widget.poll_reader()
        process.kill.assert_called_once()
        process.communicate.assert_called_once()
        self.assertIsNone(widget.process)
        self.assertNotIn("remaining", widget.data)
        self.assertIn("超时", widget.data["error"])

    def test_closing_reaps_active_reader(self):
        widget = Widget.__new__(Widget)
        widget.process = MagicMock()
        widget.root = MagicMock()
        widget.demo, widget.mutex = True, None
        widget.close()
        widget.process.kill.assert_called_once()
        widget.process.communicate.assert_called_once()
        widget.root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
