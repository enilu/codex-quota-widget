import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from updates import (OfficialRedirect, UpdateError, cached, check, feed_url,
                     parse_feed, version)


INSTALLED = {"installedVersion": "26.1016.51333", "installedBuild": "21161", "package": {}}


def feed(items):
    return ('<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">' +
            '<channel>' + items + '</channel></rss>').encode()


def item(build, display="26.1022.60000", extra="", attributes=False):
    if attributes:
        return f'<item>{extra}<enclosure sparkle:version="{build}" sparkle:shortVersionString="{display}" url="https://example.invalid/app.zip"/></item>'
    return (f'<item><sparkle:version>{build}</sparkle:version>'
            f'<sparkle:shortVersionString>{display}</sparkle:shortVersionString>{extra}'
            '<enclosure url="https://example.invalid/app.zip"/></item>')


class UpdateTests(unittest.TestCase):
    def test_numeric_version_comparison_and_zero_normalization(self):
        self.assertGreater(version("100"), version("99"))
        self.assertEqual(version("26.0.0"), version("26"))
        with self.assertRaises(UpdateError):
            version("latest-beta")

    def test_new_release_and_latest_selection(self):
        value = parse_feed(feed(item("21162") + item("21170", "26.1023.1")), INSTALLED, "26.0")
        self.assertEqual(value["state"], "available")
        self.assertEqual(value["availableBuild"], "21170")
        self.assertEqual(value["availableVersion"], "26.1023.1")

    def test_equal_old_versions_and_attribute_style(self):
        value = parse_feed(feed(item("21161", attributes=True) + item("21160")), INSTALLED, "26.0")
        self.assertEqual(value["state"], "up_to_date")
        self.assertIsNone(value["availableVersion"])

    def test_beta_and_unsupported_os_are_excluded(self):
        data = feed(item("30000", extra="<sparkle:channel>beta</sparkle:channel>") +
                    item("29999", extra="<sparkle:minimumSystemVersion>27.0</sparkle:minimumSystemVersion>") +
                    item("29998", extra="<sparkle:maximumSystemVersion>25.0</sparkle:maximumSystemVersion>"))
        self.assertEqual(parse_feed(data, INSTALLED, "26.0")["state"], "up_to_date")

    def test_bad_or_unversioned_feed_is_not_up_to_date(self):
        for data in (b"<html/>", feed('<item><enclosure/></item>')):
            with self.assertRaises(UpdateError):
                parse_feed(data, INSTALLED, "26.0")

    def test_backend_reuses_existing_identity_no_new_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            state = home / "Library/Application Support/com.openai.codex/production-appcast-bootstrap.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"backendAppcastEnabled": True, "installationId": "PRIVATE_ID"}), encoding="utf-8")
            before = state.read_bytes()
            with patch("updates.platform.machine", return_value="x86_64"), \
                 patch("updates.platform.mac_ver", return_value=("26.0", (), "")):
                url = feed_url(INSTALLED, home)
            self.assertIn("updates.oaistatic.com/codex/app/appcast?", url)
            self.assertIn("installation_id=PRIVATE_ID", url)
            self.assertIn("beta=false", url)
            self.assertIn("arch=x64", url)
            self.assertEqual(state.read_bytes(), before)

    def test_missing_identity_or_untrusted_legacy_feed_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            for url in ("http://persistent.oaistatic.com/codex-app-prod/appcast.xml", "https://evil.invalid/appcast.xml"):
                data = {**INSTALLED, "package": {"codexSparkleFeedUrl": url}}
                with self.assertRaises(UpdateError):
                    feed_url(data, Path(folder))

    def test_redirect_only_official_https(self):
        redirect = OfficialRedirect()
        request = urllib.request.Request("https://updates.oaistatic.com/codex/app/appcast")
        for url in ("https://evil.invalid/a", "http://persistent.oaistatic.com/a"):
            with self.assertRaises(UpdateError):
                redirect.redirect_request(request, None, 307, "", {}, url)
        allowed = redirect.redirect_request(request, None, 307, "", {}, "https://persistent.oaistatic.com/a.xml")
        self.assertEqual(allowed.full_url, "https://persistent.oaistatic.com/a.xml")
        self.assertIsNone(allowed.get_header("Authorization"))

    def test_installed_change_clears_old_update_badge(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "version.local.json"
            path.write_text(json.dumps({"state": "available", "installedBuild": "21160"}), encoding="utf-8")
            with patch("updates.installed_app", return_value=INSTALLED):
                self.assertEqual(cached(path)["state"], "unknown")

    def test_failed_check_does_not_overwrite_previous_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "version.local.json"
            path.write_text('{"state":"available","installedBuild":"21161"}', encoding="utf-8")
            before = path.read_bytes()
            with patch("updates.installed_app", return_value=INSTALLED), \
                 patch("updates.feed_url", return_value="https://updates.oaistatic.com/codex/app/appcast"), \
                 patch("updates.urllib.request.build_opener", side_effect=UpdateError("offline")):
                with self.assertRaises(UpdateError):
                    check(path)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
