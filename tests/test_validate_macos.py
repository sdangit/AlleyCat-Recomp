# SPDX-License-Identifier: MIT
"""Validate evidence and failure handling without private game files or desktop access."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validator", ROOT / "tools/validate_macos.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class ValidationTests(unittest.TestCase):
    def test_command_failure_and_timeout_remain_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = v.Evidence(Path(tmp) / "report.json", "a" * 40)
            self.assertFalse(ev.check("G02", "exit", lambda: ev.run([sys.executable, "-c", "raise SystemExit(9)"])))
            self.assertFalse(ev.check("G02", "timeout", lambda: ev.run([sys.executable, "-c", "import time; time.sleep(2)"], timeout=.1)))
            self.assertEqual(ev.save(), 1)
            d = json.loads(ev.path.read_text())
            self.assertEqual(d["status"], "FAIL")
            self.assertIn("timed out", d["checks"][1]["reason"])
            self.assertEqual(d["checks"][0]["commands"][0]["exit_code"], 9)

    def test_pass_does_not_claim_product_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = v.Evidence(Path(tmp) / "report.json", "a" * 40)
            ev.check("G02", "ok", lambda: ev.run([sys.executable, "-c", "print('ok')"]))
            ev.skipped("G10", "signing", "No credentials accessed")
            self.assertEqual(ev.save(), 0)
            self.assertEqual(ev.report["product_state"], "PARTIAL_VALIDATION")
            self.assertEqual(ev.report["checks"][-1]["status"], "NOT_RUN")
            ev.skipped("G05", "requested-desktop", "No display", "BLOCKED")
            self.assertEqual(ev.save(), 1)

    def test_game_path_is_redacted_from_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = str(Path(tmp) / "private-game.exe")
            ev = v.Evidence(Path(tmp) / "report.json", "a" * 40, private)
            ev.check("G04", "private", lambda: ev.run([sys.executable, "-c", "import sys; print(sys.argv[1])", private]))
            ev.save()
            self.assertNotIn(private, ev.path.read_text())
            for log in ev.logs.glob("*.log"):
                self.assertNotIn(private, log.read_text())

    def test_reference_build_or_stale_generation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "hand_entries.c").write_text("release names only")
            (p / "CMakeCache.txt").write_text("CAT_BUILD_REFERENCE:BOOL=OFF\nCAT_BUILD_APP:BOOL=ON\n")
            v.validate_cache(p)
            (p / "gen").mkdir()
            with self.assertRaises(ValueError): v.validate_cache(p)
            (p / "gen").rmdir()
            (p / "CMakeCache.txt").write_text("CAT_BUILD_REFERENCE:BOOL=ON\nCAT_BUILD_APP:BOOL=ON\n")
            with self.assertRaises(ValueError): v.validate_cache(p)

    def test_capability_shape_and_bundle_executable_paths(self):
        good = {"schema_version": 1, "runner": "cat_test_release", "build_mode": "release", "comparison_supported": False}
        v.validate_capabilities(json.dumps(good))
        for key, value in (("schema_version", True), ("comparison_supported", 0), ("runner", "cat_test")):
            with self.assertRaises(ValueError): v.validate_capabilities(json.dumps(dict(good, **{key: value})))
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "AlleyCat.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            exe = app / "Contents/MacOS/AlleyCat"; exe.write_bytes(b"fixture"); exe.chmod(0o755)
            info = {"CFBundleExecutable": "AlleyCat", "CFBundleIdentifier": "io.github.sdangit.alleycat", "CFBundlePackageType": "APPL"}
            plist = app / "Contents/Info.plist"
            with plist.open("wb") as f: plistlib.dump(info, f)
            self.assertEqual(v.validate_bundle(app), exe)
            info["CFBundleExecutable"] = "../outside"
            with plist.open("wb") as f: plistlib.dump(info, f)
            with self.assertRaises(ValueError): v.validate_bundle(app)

    def test_missing_tool_is_blocked_and_package_checksum_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ev = v.Evidence(root / "report.json", "a" * 40)
            ev.check("G07", "tool", lambda: ev.run(["alleycat-unavailable-test-tool"]))
            self.assertEqual(ev.report["checks"][0]["status"], "BLOCKED")
            self.assertEqual(ev.save(), 1)
            archive = root / "release.zip"; archive.write_bytes(b"archive fixture")
            manifest = root / "release.manifest.json"
            contents = {"source_revision": "a" * 40, "content_audit": "NOT_RUN",
                        "archive": {"name": archive.name, "sha256": v.sha256(archive)}}
            manifest.write_text(json.dumps(contents))
            output = json.dumps({"archive": str(archive), "manifest": str(manifest)})
            self.assertEqual(v.validate_package_outputs(output, root, "a" * 40, False),
                             (archive.resolve(), manifest.resolve()))
            with self.assertRaises(ValueError): v.validate_package_outputs(output, root, "a" * 40, True)
            archive.write_bytes(b"changed bytes")
            with self.assertRaises(ValueError): v.validate_package_outputs(output, root, "a" * 40, False)
            with self.assertRaises(ValueError): v.validate_package_outputs("[]", root, "a" * 40, False)

    def test_private_comparison_requires_explicit_input(self):
        p = subprocess.run([sys.executable, str(ROOT / "tools/validate_macos.py"), "--build", "absent", "--report", "absent/report.json",
            "--source-revision", "a" * 40, "--reference-runner", "absent/runner"], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("requires explicit --game-file", p.stderr)

    def test_comparison_schema_and_fail_closed_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = root / "runner"; runner.write_bytes(b"fixture")
            report = root / "report.json"
            jobs = [{"id": str(i), "seed": 1, "room": None, "mode": "general", "exit_code": 0,
                     "timed_out": False, "completed": True, "direct_comparisons": 1, "mismatches": 0,
                     "duration_seconds": 0.1, "evidence": [], "errors": []} for i in range(41)]
            good = {"schema_version": 1, "status": "PASS", "source_revision": "a" * 40,
                    "executable_sha256": v.sha256(runner), "game_sha256": v.GAME_SHA256,
                    "parameters": {"seeds": 8, "frames": 6000, "rooms": list(range(1, 8)), "jobs": 4, "timeout_seconds": 120},
                    "jobs": jobs, "totals": {"expected_jobs": 41, "completed_jobs": 41, "direct_comparisons": 41, "mismatches": 0},
                    "coverage": {"routines": {}, "uncounted": []}, "errors": []}
            report.write_text(json.dumps(good))
            v.validate_comparison_report(report, "a" * 40, runner)
            for key, value in (("schema_version", True), ("source_revision", "b" * 40),
                               ("game_sha256", "b" * 64), ("status", "FAIL"), ("jobs", jobs[:-1]),
                               ("errors", ["incomplete"]), ("extra", "unsupported")):
                report.write_text(json.dumps(dict(good, **{key: value})))
                with self.assertRaises(ValueError):
                    v.validate_comparison_report(report, "a" * 40, runner)


if __name__ == "__main__":
    unittest.main()
