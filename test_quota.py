import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quota import (QuotaError, NoRedirect, normalize_usage, normalize_credits,
                   refresh, read_cache, get_json)


def usage(used=41):
    return {"rate_limit": {"primary_window": {"used_percent": 5, "limit_window_seconds": 18000,
                                               "reset_at": 1800000000},
                           "secondary_window": {"used_percent": used, "limit_window_seconds": 604800,
                                                 "reset_at": 1800500000}}}


class QuotaTests(unittest.TestCase):
    def test_percent_is_remaining_and_weekly_window_is_selected(self):
        result = normalize_usage(usage())
        self.assertEqual(result["remaining"], 59)
        self.assertEqual(result["seconds"], 604800)

    def test_only_one_window_is_supported(self):
        data = usage()
        data["rate_limit"]["secondary_window"] = None
        self.assertEqual(normalize_usage(data)["remaining"], 95)

    def test_missing_invalid_percent_and_zero_are_distinct(self):
        self.assertEqual(normalize_usage(usage(100))["remaining"], 0)
        for invalid in (-1, 101, None, float("nan"), True):
            with self.assertRaises(QuotaError):
                normalize_usage(usage(invalid))
        with self.assertRaises(QuotaError):
            normalize_usage({})

    def test_available_unexpired_credits_sorted_by_expiry(self):
        result = normalize_credits({"credits": [
            {"status": "available", "expires_at": 3000},
            {"status": "available", "expires_at": 2000},
            {"status": "used", "expires_at": 1500},
            {"status": "available", "expires_at": 999},
        ]}, now=1000)
        self.assertEqual(result, [2000, 3000])

    def test_no_cards_is_different_from_unknown(self):
        self.assertEqual(normalize_credits({"credits": []}), [])
        with self.assertRaises(QuotaError):
            normalize_credits({})
        with self.assertRaises(QuotaError):
            normalize_credits({"credits": [{"status": "available"}]})

    def test_missing_invalid_and_unknown_status_are_not_no_cards(self):
        for status in (None, "", "new_available", True, [], {}):
            with self.subTest(status=status), self.assertRaises(QuotaError):
                normalize_credits({"credits": [{"status": status, "expires_at": 3000}]}, now=1000)
        with self.assertRaises(QuotaError):
            normalize_credits({"credits": [{"expires_at": 3000}]}, now=1000)

    def test_known_unavailable_statuses_are_skipped(self):
        self.assertEqual(normalize_credits({"credits": [
            {"status": "used"}, {"status": "expired"},
        ]}, now=1000), [])

    def test_unknown_card_status_preserves_usage_as_unknown_cards(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("quota.auth", return_value=("TOKEN", "ACCOUNT")), \
                 patch("quota.get_json", side_effect=[usage(), {"credits": [{"expires_at": 3000}]}]):
                value = refresh(Path(folder) / "usage.local.json")
            self.assertEqual(value["remaining"], 59)
            self.assertIsNone(value["creditExpiries"])
            self.assertIsNotNone(value["creditError"])

    def test_iso_expiry_has_explicit_timezone(self):
        self.assertEqual(normalize_credits({"credits": [
            {"status": "available", "expires_at": "2026-10-23T04:38:48+08:00"}
        ]}, now=0), [1792701528])

    def test_network_is_fixed_get_only_and_redirects_are_rejected(self):
        with self.assertRaises(QuotaError):
            get_json("https://evil.invalid", "SECRET", "ACCOUNT")
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid"))

    def test_refresh_caches_no_credentials_and_cache_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "auth.json").write_text(json.dumps({"tokens": {
                "access_token": "SECRET_ACCESS", "account_id": "SECRET_ACCOUNT",
                "refresh_token": "SECRET_REFRESH"}}), encoding="utf-8")
            cache = home / "usage.local.json"
            with patch("quota.get_json", side_effect=[usage(), {"credits": []}]) as request:
                result = refresh(cache, home)
                self.assertEqual(request.call_count, 2)
                self.assertEqual(result["creditExpiries"], [])
            serialized = cache.read_text(encoding="utf-8")
            self.assertNotIn("SECRET_", serialized)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
            with patch("quota.get_json", side_effect=AssertionError("缓存不应联网")):
                self.assertEqual(read_cache(cache, home)["remaining"], 59)
            previous = cache.read_bytes()
            with patch("quota.get_json", side_effect=QuotaError("network")):
                with self.assertRaises(QuotaError):
                    refresh(cache, home)
            self.assertEqual(cache.read_bytes(), previous)

    def test_card_failure_is_unknown_and_keeps_successful_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "usage.local.json"
            with patch("quota.auth", return_value=("TOKEN", "ACCOUNT")), \
                 patch("quota.get_json", side_effect=[usage(), QuotaError("卡片读取失败")]):
                value = refresh(cache)
            self.assertEqual(value["remaining"], 59)
            self.assertIsNone(value["creditExpiries"])
            self.assertEqual(value["creditError"], "卡片读取失败")

    def test_account_switch_does_not_publish_old_account(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "usage.local.json"
            with patch("quota.auth", side_effect=[("TOKEN", "FIRST"), ("TOKEN2", "SECOND")]), \
                 patch("quota.get_json", side_effect=[usage(), {"credits": []}]):
                with self.assertRaises(QuotaError):
                    refresh(cache)
            self.assertFalse(cache.exists())


if __name__ == "__main__":
    unittest.main()
