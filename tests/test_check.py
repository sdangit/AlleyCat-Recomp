# SPDX-License-Identifier: MIT
"""Exercise checker boundaries through real controlled subprocesses, without CAT.EXE."""
import copy
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("checker", ROOT / "tools/check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CheckerProcesses(unittest.TestCase):
    def run_case(self, scenario):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "private input"
            game.write_bytes(b"fixture, not game data")
            report = Path(tmp) / "report.json"
            runner = ROOT / "tests/check_fixtures/runner.py"
            p = subprocess.run([sys.executable, str(ROOT / "tests/check_fixtures/check_driver.py"), str(game),
                                "--exe", str(runner), "--seeds", "1", "--jobs", "2",
                                "--timeout", "0.5", "--source-revision", "a" * 40,
                                "--json-report", str(report)],
                               env=dict(os.environ, CHECK_FIXTURE=scenario), capture_output=True,
                               text=True, timeout=20)
            data = json.loads(report.read_text())
            self.assertNotIn(str(game), report.read_text())
            self.assertEqual(data["source_revision"], "a" * 40)
            self.assertEqual(len(data["executable_sha256"]), 64)
            self.assertEqual(data["totals"]["expected_jobs"], 6)
            self.validate_schema(data)
            return p, data

    def validate_schema(self, report):
        # Validate the schema's required/type/enum/const/shape constraints using
        # stdlib so asset-free tests do not require a package installation.
        schema = json.loads((ROOT / "tools/check_report.schema.json").read_text())
        kinds = {"object": dict, "array": list, "string": str, "integer": int,
                 "number": (int, float), "boolean": bool, "null": type(None)}
        def validate(value, node):
            if "$ref" in node:
                node = schema["$defs"][node["$ref"].split("/")[-1]]
            types = node.get("type", [])
            types = [types] if isinstance(types, str) else types
            if types:
                self.assertTrue(any(isinstance(value, kinds[t]) and
                    not (isinstance(value, bool) and t in ("integer", "number")) for t in types))
            if "const" in node: self.assertEqual(value, node["const"])
            if "enum" in node: self.assertIn(value, node["enum"])
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in node: self.assertGreaterEqual(value, node["minimum"])
                if "maximum" in node: self.assertLessEqual(value, node["maximum"])
                if "exclusiveMinimum" in node: self.assertGreater(value, node["exclusiveMinimum"])
            if isinstance(value, str) and "pattern" in node:
                self.assertIsNotNone(re.search(node["pattern"], value))
            if isinstance(value, dict):
                self.assertTrue(set(node.get("required", [])) <= value.keys())
                if node.get("additionalProperties") is False:
                    self.assertTrue(value.keys() <= node.get("properties", {}).keys())
                for key, sub in node.get("properties", {}).items():
                    if key in value: validate(value[key], sub)
                if isinstance(node.get("additionalProperties"), dict):
                    for key, sub in value.items():
                        if key not in node.get("properties", {}): validate(sub, node["additionalProperties"])
            if isinstance(value, list):
                for child in value: validate(child, node.get("items", {}))
        validate(report, schema)

    def test_success_and_additive_capabilities(self):
        for scenario in ("pass", "extra_field", "legitimate_exit"):
            with self.subTest(scenario=scenario):
                p, d = self.run_case(scenario)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(d["status"], "PASS")
                self.assertEqual(d["totals"]["direct_comparisons"], 6)
                self.assertEqual(d["totals"]["completed_jobs"], 6)

    def test_failures_cannot_report_success(self):
        for scenario in ("exit", "timeout", "truncated", "premature", "empty", "mismatch", "malformed_row", "stderr",
                         "release", "bad_capability", "bad_schema", "malformed_capability"):
            with self.subTest(scenario=scenario):
                p, d = self.run_case(scenario)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(d["status"], "FAIL")
                self.assertTrue(d["errors"])

    @unittest.skipIf(os.name == "nt", "POSIX signal exit semantics")
    def test_signal_is_failure(self):
        p, d = self.run_case("signal")
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(all(j["exit_code"] < 0 for j in d["jobs"]))

    def test_duplicate_and_disagreeing_reports(self):
        body = (checker.HEADING + "\nhand_0000: 1 calls checked, 0 mismatches, 0 flag-only differences, 0 nested\n"
                "total mismatches: 0\ninterpreted instructions: 0\nend: frame 2, vram 01234567, CS:IP F000:001A\n")
        for out in (body + body, body.replace("total mismatches: 0", "total mismatches: 1")):
            self.assertTrue(checker.parse_output(out)[2])

    def test_schema_rejects_invalid_values(self):
        _, valid = self.run_case("pass")
        for key, value in (("source_revision", "not a SHA"), ("schema_version", True),
                           ("extra_property", 1)):
            bad = copy.deepcopy(valid)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.validate_schema(bad)
        for key, value in (("jobs", 0), ("timeout_seconds", 0), ("rooms", [8])):
            bad = copy.deepcopy(valid)
            bad["parameters"][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.validate_schema(bad)

    def test_report_write_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = subprocess.run([sys.executable, str(ROOT / "tools/check.py"), "missing",
                                "--json-report", tmp], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("cannot write JSON report", p.stderr)


if __name__ == "__main__":
    unittest.main()
