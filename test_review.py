"""Regression checks for the complete widget review, using synthetic data only."""
import base64
import contextlib
import io
import runpy
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quota import QuotaError, account_hash, normalize_usage, normalize_credits, read_cache, refresh, timestamp
from updates import UpdateError, cached, check, installed_app, plan_type
from test_quota import usage
from test_updates import INSTALLED, feed, item


class ReviewTests(unittest.TestCase):
    def test_malformed_usage_and_window_types(self):
        for data in (None, [], 'bad', {'rate_limit': {'primary_window': []}},
                     {'rate_limit': {'primary_window': 'bad'}}):
            with self.subTest(data=data), self.assertRaises(QuotaError):
                normalize_usage(data)

    def test_duration_rejects_bool_nonfinite_and_extreme(self):
        for duration in (True, float('nan'), float('inf'), -1, 10**30, 10**1000):
            data = usage()
            data['rate_limit']['secondary_window']['limit_window_seconds'] = duration
            with self.subTest(duration=duration), self.assertRaises(QuotaError):
                normalize_usage(data)

    def test_time_bounds_and_milliseconds(self):
        self.assertEqual(timestamp(1800000000000), 1800000000)
        for value in (True, float('inf'), 10**30, '1960-01-01T00:00:00+00:00'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timestamp(value)

    def test_malformed_cards_keep_successful_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            for bad in (None, 'bad', []):
                with patch('quota.auth', return_value=('TOKEN', 'ACCOUNT')), \
                     patch('quota.get_json', side_effect=[usage(), {'credits': [bad]}]):
                    value = refresh(Path(folder) / 'usage.local.json')
                self.assertEqual(value['remaining'], 59)
                self.assertIsNone(value['creditExpiries'])
                self.assertIsNotNone(value['creditError'])

    def test_cache_schema_allowlist_and_bad_fields(self):
        with tempfile.TemporaryDirectory() as folder, patch('quota.auth', return_value=('TOKEN', 'ACCOUNT')):
            path = Path(folder) / 'usage.local.json'
            good = dict(remaining=59, resetsAt=1800500000, updatedAt=1800000000,
                        windowSeconds=604800, creditExpiries=[], accountHash=account_hash('ACCOUNT'))
            path.write_text(json.dumps({**good, 'access_token': 'SHOULD_NOT_ESCAPE'}), encoding='utf-8')
            self.assertNotIn('access_token', read_cache(path))
            for bad in ([], {**good, 'remaining': True}, {**good, 'updatedAt': 10**30},
                        {**good, 'creditExpiries': [float('inf')]}, {**good, 'creditError': []}):
                path.write_text(json.dumps(bad), encoding='utf-8')
                with self.subTest(bad=bad), self.assertRaises(QuotaError):
                    read_cache(path)

    def test_unexpected_reader_error_keeps_safe_same_account_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / '.codex').mkdir()
            (home / '.codex/auth.json').write_text(json.dumps({'tokens': {
                'access_token': 'TOKEN', 'account_id': 'ACCOUNT'}}), encoding='utf-8')
            path = home / 'usage.local.json'
            path.write_text(json.dumps(dict(remaining=59, resetsAt=1800500000,
                updatedAt=1800000000, windowSeconds=604800, creditExpiries=[],
                accountHash=account_hash('ACCOUNT'))), encoding='utf-8')
            output = io.StringIO()
            with patch('pathlib.Path.home', return_value=home), \
                 patch('sys.argv', ['quota.py', str(path), '--refresh']), \
                 patch('urllib.request.build_opener', side_effect=RuntimeError('SECRET_DETAIL')), \
                 contextlib.redirect_stdout(output):
                runpy.run_path(str(Path(__file__).resolve().parents[1] / 'quota.py'), run_name='__main__')
            value = json.loads(output.getvalue())
            self.assertEqual(value['remaining'], 59)
            self.assertIn('error', value)
            self.assertNotIn('SECRET_DETAIL', output.getvalue())
            self.assertNotIn('accountHash', value)

    def test_bad_auth_claims_use_unknown_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / '.codex').mkdir()
            for claims in ([], {'https://api.openai.com/auth': []},
                           {'https://api.openai.com/auth': {'chatgpt_plan_type': []}}):
                token = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
                (home / '.codex/auth.json').write_text(json.dumps({'tokens': {'id_token': 'a.' + token + '.b'}}), encoding='utf-8')
                self.assertEqual(plan_type(home), 'unknown')

    def test_select_newest_stable_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            apps = []
            for index, build in enumerate(('21161', '21170', '30000')):
                app = Path(folder) / str(index)
                (app / 'Contents').mkdir(parents=True)
                (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                    'CFBundleIdentifier': 'com.openai.codex', 'CFBundleVersion': build,
                    'CFBundleShortVersionString': '26.1'}))
                apps.append(app)
            with patch('updates.asar_package', side_effect=[{'codexBuildFlavor': 'prod'},
                        {'codexBuildFlavor': 'prod'}, {'codexBuildFlavor': 'beta'}]):
                self.assertEqual(installed_app(apps)['installedBuild'], '21170')

    def test_mid_check_install_change_does_not_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'version.local.json'
            response = MagicMock()
            response.__enter__.return_value.read.return_value = feed(item('21170'))
            with patch('updates.installed_app', side_effect=[INSTALLED, {**INSTALLED, 'installedBuild': '21170'}]), \
                 patch('updates.feed_url', return_value='https://updates.oaistatic.com/codex/app/appcast'), \
                 patch('updates.urllib.request.build_opener') as opener, \
                 patch('updates.platform.mac_ver', return_value=('26.0', (), '')):
                opener.return_value.open.return_value = response
                with self.assertRaises(UpdateError):
                    check(path)
            self.assertFalse(path.exists())

    def test_broken_candidates_do_not_hide_valid_installation(self):
        for broken in ("plist", "xml_plist", "asar", "build", "display", "package"):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as folder:
                apps = [Path(folder) / "broken.app", Path(folder) / "valid.app"]
                for app in apps:
                    (app / "Contents").mkdir(parents=True)
                    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
                        "CFBundleIdentifier": "com.openai.codex", "CFBundleVersion": "21170",
                        "CFBundleShortVersionString": "26.2"}))
                info = apps[0] / "Contents/Info.plist"
                if broken == "plist":
                    info.write_bytes(b"incomplete plist")
                elif broken == "xml_plist":
                    info.write_bytes(b'<?xml version="1.0"?><plist><dict>')
                elif broken in {"build", "display"}:
                    data = plistlib.loads(info.read_bytes())
                    data["CFBundleVersion" if broken == "build" else "CFBundleShortVersionString"] = "invalid"
                    info.write_bytes(plistlib.dumps(data))
                def package(path):
                    if path.is_relative_to(apps[0]):
                        if broken == "asar":
                            raise FileNotFoundError()
                        if broken == "package":
                            return []
                    return {"codexBuildFlavor": "prod"}
                with patch("updates.asar_package", side_effect=package):
                    self.assertEqual(installed_app(apps)["installedBuild"], "21170")

    def test_all_broken_installations_return_safe_error(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / "broken.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(b"incomplete plist")
            with self.assertRaises(UpdateError):
                installed_app([app])

    def test_version_cache_schema_and_allowlist(self):
        with tempfile.TemporaryDirectory() as folder, patch('updates.installed_app', return_value=INSTALLED):
            path = Path(folder) / 'version.local.json'
            good = dict(state='available', installedBuild='21161', installedVersion='26.1',
                        availableBuild='21170', availableVersion='26.2', checkedAt=1800000000)
            path.write_text(json.dumps({**good, 'installationId': 'PRIVATE'}), encoding='utf-8')
            self.assertNotIn('installationId', cached(path))
            for bad in ([], {**good, 'checkedAt': True}, {**good, 'availableBuild': '21160'}):
                path.write_text(json.dumps(bad), encoding='utf-8')
                with self.subTest(bad=bad), self.assertRaises(UpdateError):
                    cached(path)


if __name__ == '__main__':
    unittest.main()
