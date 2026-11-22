"""Packaging boundaries and byte-audit regressions; no original game data needed."""
import argparse
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("macos_package", ROOT / "tools/make_macos_release.py")
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


class PackagingBoundaries(unittest.TestCase):
    def make_bundle(self, root):
        app = root / "AlleyCat.app"
        for name in pack.REQUIRED_APP_FILES:
            p = app / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"placeholder")
        return app

    def test_inventory_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_bundle(Path(tmp))
            self.assertEqual(pack.bundle_inventory(app), pack.REQUIRED_APP_FILES)
            (app / 'Contents/game.exe').write_bytes(b'not game data')
            with self.assertRaisesRegex(pack.AuditError, 'unexpected bundle file'):
                pack.bundle_inventory(app)

    @unittest.skipIf(os.name == "nt", "Creating symlinks may require Windows developer privileges")
    def test_symlinks_and_extra_directories_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_bundle(Path(tmp))
            (app / 'Contents/Resources/escape').symlink_to(Path(tmp))
            with self.assertRaisesRegex(pack.AuditError, 'symlink'):
                pack.bundle_inventory(app)
            (app / 'Contents/Resources/escape').unlink()
            (app / 'Contents/Frameworks').mkdir()
            with self.assertRaisesRegex(pack.AuditError, 'unexpected bundle directory'):
                pack.bundle_inventory(app)

    def test_final_window_and_exact_length_are_checked(self):
        marker = bytes(range(32))
        self.assertEqual(pack.byte_matches(marker, marker), 1)
        self.assertEqual(pack.byte_matches(b'head' + marker, b'prefix' + marker), 1)
        self.assertEqual(pack.byte_matches(marker[:-1], marker), 0)
        self.assertEqual(pack.byte_matches(b'0' * 32, b'0' * 32), 0)

    def test_reject_wrong_original_and_unsafe_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'private.exe'
            p.write_bytes(bytes(55067))
            with self.assertRaises(pack.AuditError): pack.read_game(p)
        for version in ('../release', '/absolute', 'x/y', ''):
            with self.assertRaises(argparse.ArgumentTypeError): pack.safe_version(version)
        with self.assertRaises(argparse.ArgumentTypeError): pack.revision('bad')
        self.assertEqual(pack.revision('A' * 40), 'a' * 40)

    def test_existing_output_is_never_removed(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); sentinel = p / 'keep'; sentinel.write_text('important')
            with patch.object(pack.sys, 'platform', 'darwin'):
                with self.assertRaisesRegex(pack.AuditError, 'already exists'):
                    pack.package(argparse.Namespace(output=p))
            self.assertEqual(sentinel.read_text(), 'important')

    def test_output_inside_app_is_rejected_without_mutation(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_bundle(Path(tmp))
            sentinel = app / 'Contents/Resources/keep'
            sentinel.write_text('important')
            before = {str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}
            for output in (app / 'release', app / 'Contents/../release', app):
                with self.subTest(output=output), patch.object(pack.sys, 'platform', 'darwin'), \
                        patch.object(pack, 'inspect_bundle') as inspect:
                    with self.assertRaises(pack.AuditError):
                        pack.package(argparse.Namespace(app=app, output=output))
                    inspect.assert_not_called()
                self.assertEqual({str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}, before)
                self.assertFalse((app / 'release').exists())

    @unittest.skipIf(os.name == "nt", "Creating symlinks may require Windows developer privileges")
    def test_output_symlink_parent_cannot_enter_app(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_bundle(Path(tmp))
            alias = Path(tmp) / 'alias'
            alias.symlink_to(app, target_is_directory=True)
            with patch.object(pack.sys, 'platform', 'darwin'):
                with self.assertRaisesRegex(pack.AuditError, 'outside the source app'):
                    pack.package(argparse.Namespace(app=app, output=alias / 'release'))
            self.assertFalse((app / 'release').exists())


if __name__ == '__main__': unittest.main()
