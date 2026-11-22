#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run requested automated port checks; never imply desktop or distribution approval.

Default checks use no game file. Private gameplay and reference comparisons require
explicit --game-file and (for comparisons) --reference-runner. Logs stay beside the
JSON report. PASS means these requested checks passed, not that all product gates did.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
import wave
import zlib

ROOT = Path(__file__).resolve().parents[1]
GAME_SHA256 = "4979c8867826e08881d1d4bec95c95d6bc1ac70fd21050ccdb4f733a50d7bfdd"
HASHES = ["e594e876", "6ab7983c", "a8cd91e7", "d3d5664c", "259e94eb", "04d420cc"]


class ToolUnavailable(Exception):
    pass


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def positive(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return n


def revision(value):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise argparse.ArgumentTypeError("expected a 40-character source commit SHA")
    return value.lower()


def validate_cache(build):
    cache = {}
    for line in (build / "CMakeCache.txt").read_text().splitlines():
        m = re.match(r"([^#/:][^:]*):[^=]+=(.*)", line)
        if m:
            cache[m[1]] = m[2]
    if cache.get("CAT_BUILD_REFERENCE") != "OFF" or cache.get("CAT_BUILD_APP") != "ON":
        raise ValueError("expected a release-only GUI build (reference OFF, app ON)")
    if (build / "gen").exists():
        raise ValueError("release build contains a reference generation directory")
    if not (build / "hand_entries.c").is_file():
        raise ValueError("release routine table missing")
    return cache


def validate_capabilities(text):
    c = json.loads(text)
    if (not isinstance(c, dict) or type(c.get("schema_version")) is not int
            or c["schema_version"] != 1 or c.get("runner") != "cat_test_release"
            or c.get("build_mode") != "release" or c.get("comparison_supported") is not False):
        raise ValueError("runner does not declare schema-1 release capabilities")


def validate_comparison_report(path, source_revision, runner):
    """Consume M03's canonical schema without an external package dependency."""
    schema = json.loads((ROOT / "tools/check_report.schema.json").read_text())
    report = json.loads(Path(path).read_text())
    kinds = {"object": dict, "array": list, "string": str, "integer": int,
             "number": (int, float), "boolean": bool, "null": type(None)}

    def validate(value, node):
        supported = {"$schema", "title", "$defs", "$ref", "type", "const", "enum", "minimum",
                     "maximum", "exclusiveMinimum", "pattern", "required", "properties", "additionalProperties", "items"}
        if node.keys() - supported:
            raise ValueError("unsupported comparison schema constraint")
        if "$ref" in node:
            node = schema["$defs"][node["$ref"].removeprefix("#/$defs/")]
        types = node.get("type", [])
        types = [types] if isinstance(types, str) else types
        if types and not any(isinstance(value, kinds[t]) and
                not (isinstance(value, bool) and t in ("integer", "number")) for t in types):
            raise ValueError("comparison report type mismatch")
        if "const" in node and value != node["const"] or "enum" in node and value not in node["enum"]:
            raise ValueError("comparison report value mismatch")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if (not math.isfinite(value) or "minimum" in node and value < node["minimum"]
                    or "maximum" in node and value > node["maximum"]
                    or "exclusiveMinimum" in node and value <= node["exclusiveMinimum"]):
                raise ValueError("comparison report number outside bounds")
        if isinstance(value, str) and "pattern" in node and not re.search(node["pattern"], value):
            raise ValueError("comparison report pattern mismatch")
        if isinstance(value, dict):
            props = node.get("properties", {})
            if not set(node.get("required", [])) <= value.keys():
                raise ValueError("comparison report required field missing")
            for key, child in value.items():
                rule = props.get(key, node.get("additionalProperties", {}))
                if rule is False: raise ValueError("unexpected comparison report field")
                if isinstance(rule, dict): validate(child, rule)
        if isinstance(value, list):
            for child in value: validate(child, node.get("items", {}))

    validate(report, schema)
    t, jobs = report["totals"], report["jobs"]
    if (report["status"] != "PASS" or report["errors"] or report["source_revision"] != source_revision
            or report["executable_sha256"] != sha256(runner) or report["game_sha256"] != GAME_SHA256
            or t["expected_jobs"] != 41 or t["completed_jobs"] != 41 or len(jobs) != 41
            or len({j["id"] for j in jobs}) != 41 or t["direct_comparisons"] <= 0 or t["mismatches"] != 0
            or any(j["errors"] or j["timed_out"] or not j["completed"] or j["exit_code"] != 0
                   or j["mismatches"] != 0 or j["direct_comparisons"] <= 0 for j in jobs)):
        raise ValueError("comparison evidence incomplete, failed, or unrelated to requested inputs")
    return report


def validate_bundle(app):
    with (app / "Contents/Info.plist").open("rb") as f:
        info = plistlib.load(f)
    if not isinstance(info, dict):
        raise ValueError("bundle plist is not a dictionary")
    name = info.get("CFBundleExecutable", "")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("invalid bundle executable name")
    if info.get("CFBundleIdentifier") != "io.github.sdangit.alleycat":
        raise ValueError("unexpected bundle identifier")
    if info.get("CFBundlePackageType") != "APPL":
        raise ValueError("bundle package type must be APPL")
    exe = app / "Contents/MacOS" / name
    if not exe.is_file() or exe.is_symlink() or not os.access(exe, os.X_OK):
        raise ValueError("bundle executable is missing, linked, or not executable")
    return exe


def validate_package_outputs(text, output_root, source_revision, audited):
    output_root = Path(output_root).resolve()
    outputs = json.loads(text)
    if not isinstance(outputs, dict) or not all(isinstance(outputs.get(k), str) for k in ("archive", "manifest")):
        raise ValueError("invalid packager output object")
    archive, manifest = Path(outputs["archive"]).resolve(), Path(outputs["manifest"]).resolve()
    if (not archive.is_relative_to(output_root) or not manifest.is_relative_to(output_root)
            or archive == manifest):
        raise ValueError("packager outputs are outside the staging root")
    sidecar = json.loads(manifest.read_text())
    if not isinstance(sidecar, dict) or not isinstance(sidecar.get("archive"), dict):
        raise ValueError("invalid package sidecar shape")
    if (sidecar.get("source_revision") != source_revision
            or sidecar.get("content_audit") != ("PASS" if audited else "NOT_RUN")
            or sidecar["archive"].get("name") != archive.name
            or sidecar["archive"].get("sha256") != sha256(archive)):
        raise ValueError("package sidecar identity/audit/checksum mismatch")
    return archive, manifest


def validate_media(png, wav):
    data = png.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("invalid PNG signature/header")
    if (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")) != (640, 400):
        raise ValueError("unexpected headless PNG dimensions")
    at, compressed = 8, bytearray()
    while at + 12 <= len(data):
        size = int.from_bytes(data[at:at + 4], "big")
        if at + size + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        if data[at + 4:at + 8] == b"IDAT":
            compressed.extend(data[at + 8:at + 8 + size])
        at += size + 12
    if len(set(zlib.decompress(compressed))) < 2:
        raise ValueError("PNG contains no varying image data")
    with wave.open(str(wav), "rb") as f:
        if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, 44100):
            raise ValueError("unexpected WAV format")
        samples = f.readframes(f.getnframes())
        if not samples or not any(samples):
            raise ValueError("WAV has no nonzero samples")


class Evidence:
    def __init__(self, path, source_revision, game=None):
        self.path = path
        self.logs = path.parent / (path.stem + ".logs")
        self.logs.mkdir(parents=True, exist_ok=True)
        self.game = str(game) if game else None
        self.report = {"schema_version": 1, "source_revision": source_revision,
                       "revision_provenance": "caller supplied; binary SHA-256 recorded separately",
                       "scope": "requested automated checks only", "product_state": "PARTIAL_VALIDATION",
                       "status": "FAIL", "checks": []}

    def clean(self, value):
        text = str(value)
        return text.replace(self.game, "<game-file>") if self.game else text

    def check(self, gate, name, fn):
        item = {"gate_id": gate, "id": name, "tested_commit": self.report["source_revision"],
                "status": "FAIL", "commands": [], "evidence": [], "duration_seconds": 0, "reason": ""}
        self.report["checks"].append(item)
        start = time.monotonic()
        self.current = item
        try:
            fn()
            item["status"] = "PASS"
        except ToolUnavailable as e:
            item["status"] = "BLOCKED"
            item["reason"] = self.clean(e)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zlib.error, wave.Error) as e:
            item["reason"] = self.clean(e)
        item["duration_seconds"] = round(time.monotonic() - start, 6)
        return item["status"] == "PASS"

    def run(self, command, timeout=120, expected=0):
        command = list(map(str, command))
        record = {"argv": [self.clean(s) for s in command], "exit_code": None}
        self.current["commands"].append(record)
        try:
            p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as e:
            if Path(command[0]).name == command[0]:
                raise ToolUnavailable(f"required tool unavailable: {command[0]}") from e
            raise
        except subprocess.TimeoutExpired as e:
            raise ValueError(f"command timed out after {timeout} seconds") from e
        record["exit_code"] = p.returncode
        log = self.logs / f"{self.current['id']}-{len(self.current['commands'])}.log"
        log.write_text(self.clean(p.stdout + "\n[stderr]\n" + p.stderr), encoding="utf-8")
        self.current["evidence"].append(str(log))
        if p.returncode != expected:
            raise ValueError(f"command returned {p.returncode}, expected {expected}; see {log.name}")
        return p.stdout

    def skipped(self, gate, name, reason, status="NOT_RUN"):
        self.report["checks"].append({"gate_id": gate, "id": name, "tested_commit": self.report["source_revision"],
            "status": status, "commands": [], "evidence": [], "duration_seconds": 0, "reason": reason})

    def save(self):
        failed = any(c["status"] in ("FAIL", "BLOCKED") for c in self.report["checks"])
        self.report["status"] = "FAIL" if failed else "PASS"
        self.path.write_text(json.dumps(self.report, indent=2) + "\n", encoding="utf-8")
        return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--source-revision", required=True, type=revision)
    ap.add_argument("--platform", choices=("macos", "windows"), default="macos")
    ap.add_argument("--configure", action="store_true", help="configure/build a fresh release directory")
    ap.add_argument("--cmake-arg", action="append", default=[])
    ap.add_argument("--jobs", type=positive, default=4)
    ap.add_argument("--app", type=Path, help="inspect this Mac application bundle")
    ap.add_argument("--package-output", type=Path, help="run packaging into a fresh staging directory")
    ap.add_argument("--version", default="1.0-macos")
    ap.add_argument("--game-file", type=Path, help="explicit private input; enables deterministic gameplay")
    ap.add_argument("--reference-runner", type=Path, help="explicitly opt into the full private comparison suite")
    a = ap.parse_args(argv)
    if a.reference_runner and not a.game_file:
        ap.error("--reference-runner requires explicit --game-file")
    if a.package_output and not a.app:
        ap.error("--package-output requires --app")
    a.build, a.report = a.build.resolve(), a.report.resolve()
    if a.app: a.app = a.app.resolve()
    if a.game_file: a.game_file = a.game_file.resolve()
    try:
        ev = Evidence(a.report, a.source_revision, a.game_file)
        if a.configure:
            def build():
                if (a.build / "CMakeCache.txt").exists():
                    raise ValueError("--configure requires a fresh build directory")
                ev.run(["cmake", "-S", ROOT, "-B", a.build, "-DCAT_BUILD_REFERENCE=OFF", "-DCAT_BUILD_APP=ON",
                        f"-DPython3_EXECUTABLE={sys.executable}", *a.cmake_arg], timeout=300)
                ev.run(["cmake", "--build", a.build, "--parallel", a.jobs], timeout=600)
            ev.check("G01", "release-build", build)
        ev.check("G01", "release-only-cache", lambda: validate_cache(a.build))
        runner = a.build / ("cat_test_release.exe" if a.platform == "windows" else "cat_test_release")
        def runner_check():
            ev.report["release_runner_sha256"] = sha256(runner)
            validate_capabilities(ev.run([runner, "--capabilities"]))
            for mode in ("check", "gen", "invalid"):
                ev.run([runner, "absent-game-file", "--hand-mode", mode], expected=2)
        ev.check("G02", "release-capabilities-and-modes", runner_check)
        ev.check("G02", "python-negative-tests", lambda: ev.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"], timeout=120))
        if a.app:
            def bundle_check():
                exe = validate_bundle(a.app)
                ev.report["application_sha256"] = sha256(exe)
                arch = ev.run(["lipo", "-archs", exe]).strip().split()
                if arch != ["arm64"]: raise ValueError("expected an ARM64-only initial Mac artifact")
                deps = ev.run(["otool", "-L", exe]).splitlines()[1:]
                if not deps: raise ValueError("no Mach-O dependency report")
                for dep in deps:
                    if not dep.strip().startswith(("/System/Library/", "/usr/lib/")):
                        raise ValueError("non-system Mach-O dependency")
            ev.check("G07", "bundle-structure-and-dependencies", bundle_check)
        if a.game_file:
            def gameplay():
                if sha256(a.game_file) != GAME_SHA256: raise ValueError("private game digest mismatch")
                ev.report["game_sha256"] = GAME_SHA256
                png, wav = ev.logs / "frame300.png", ev.logs / "release.wav"
                out = ev.run([runner, a.game_file, "--frames", "6000", "--autoplay", "1", "--rooms",
                              "--status", "1000", "--shot", f"300:{png}", "--wav", wav])
                if re.findall(r"frame\s+\d+\s+vram ([0-9a-f]{8})", out) != HASHES:
                    raise ValueError("deterministic video hashes differ from audit baseline")
                if "interpreted instructions: 0\n" not in out or "end: frame 6000," not in out:
                    raise ValueError("release run did not finish natively at frame 6000")
                validate_media(png, wav)
                ev.current["evidence"] += [str(png), str(wav)]
            game_ok = ev.check("G04", "private-deterministic-gameplay", gameplay)
        else:
            game_ok = False
            ev.skipped("G04", "private-deterministic-gameplay", "No private game input supplied")
        if a.reference_runner:
            def compare():
                if not game_ok: raise ValueError("private input/gameplay gate failed")
                report = ev.logs / "comparison.json"
                ev.run([sys.executable, ROOT / "tools/check.py", a.game_file, "--all-rooms",
                        "--exe", a.reference_runner.resolve(), "--jobs", a.jobs, "--timeout", "120",
                        "--source-revision", a.source_revision, "--json-report", report], timeout=1500)
                validate_comparison_report(report, a.source_revision, a.reference_runner.resolve())
                ev.current["evidence"].append(str(report))
            ev.check("G03", "private-reference-comparison", compare)
        else:
            ev.skipped("G03", "private-reference-comparison", "No explicit reference runner supplied")
        if a.package_output:
            def package():
                cmd = [sys.executable, ROOT / "tools/make_macos_release.py", "--app", a.app,
                       "--build", a.build, "--output", a.package_output.resolve(), "--version", a.version,
                       "--source-revision", a.source_revision]
                cmd += ["--game-file", a.game_file] if a.game_file else ["--skip-game-audit"]
                archive, manifest = validate_package_outputs(ev.run(cmd, timeout=300),
                    a.package_output.resolve(), a.source_revision, bool(a.game_file))
                ev.current["evidence"] += [str(archive), str(manifest)]
            ev.check("G07", "package-private-audit" if a.game_file else "package-structure-only", package)
        for gate, name, reason in (
            ("G05", "native-desktop-interaction", "Coordinator-driven native UI evidence required"),
            ("G06", "storage-and-relocation", "Coordinator-driven state/relocation evidence required"),
            ("G09", "independent-review", "Independent reviewer evidence required"),
            ("G10", "distribution", "Developer ID signing and notarization not exercised; local packaging may use ad-hoc signing")):
            ev.skipped(gate, name, reason)
        if a.platform == "windows" and os.name == "nt" and a.configure:
            def windows_check():
                checks = {c["id"]: c for c in ev.report["checks"]}
                if not all(checks.get(k, {}).get("status") == "PASS" for k in
                           ("release-build", "release-only-cache", "release-capabilities-and-modes", "python-negative-tests")):
                    raise ValueError("native Windows build or shared checks failed")
                ev.current["reason"] = "Native Windows release compilation/execution and shared Python checks passed; gameplay not tested"
                ev.current["evidence"] = [path for k in ("release-build", "release-capabilities-and-modes", "python-negative-tests")
                                          for path in checks[k]["evidence"]]
            ev.check("G08", "windows-build-and-shared-tests", windows_check)
        else:
            ev.skipped("G08", "windows-regression", "Separate native or cross-compile Windows evidence required")
        code = ev.save()
    except (OSError, ValueError) as e:
        print(f"validation report/input failure: {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"{ev.report['status']}: requested automated checks; product remains PARTIAL_VALIDATION")
    print(a.report)
    return code


if __name__ == "__main__":
    sys.exit(main())
