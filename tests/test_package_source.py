"""Keep private files and unexpected paths out of the source upload package."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package_source import public_files


class PackageTests(unittest.TestCase):
    def test_only_explicit_public_files_are_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "README.md").write_text("public", encoding="utf-8")
            (root / "usage.local.json").write_text("private", encoding="utf-8")
            (root / "PUBLIC_FILES.txt").write_text("# public files\nREADME.md\n", encoding="utf-8")
            self.assertEqual(public_files(root), ["README.md"])

    def test_private_missing_duplicate_and_unsafe_entries_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ("usage.local.json", "auth.json", "README.md", ".env.local", "debug.log"):
                (root / name).write_text("fixture", encoding="utf-8")
            for listing in ("usage.local.json", "auth.json", "../README.md", "/tmp/file",
                            "README.md\nREADME.md", "missing.md", "", "./README.md", ".env.local", "debug.log"):
                with self.subTest(listing=listing):
                    (root / "PUBLIC_FILES.txt").write_text(listing, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        public_files(root)

    def test_symlink_cannot_smuggle_a_private_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "usage.local.json").write_text("private", encoding="utf-8")
            try:
                (root / "README.md").symlink_to(root / "usage.local.json")
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows account lacks symbolic-link privilege")
                raise
            (root / "PUBLIC_FILES.txt").write_text("README.md", encoding="utf-8")
            with self.assertRaises(ValueError):
                public_files(root)


if __name__ == "__main__":
    unittest.main()
