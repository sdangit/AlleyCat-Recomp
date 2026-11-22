#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Syncr0ndi
"""Compare handwritten routines against generated code, failing on incomplete runs.

Use --json-report for machine-readable evidence. --source-revision records a caller-
supplied revision; executable_sha256 independently identifies the tested binary.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"hand_([0-9a-f]{4}):\s+(\d+) calls checked, (\d+) mismatches, (\d+) flag-only differences, (\d+) nested")
END = re.compile(r"end: frame (\d+), vram [0-9a-f]{8}, CS:IP [0-9A-F]{4}:[0-9A-F]{4}")
HEADING = "hand-written routines checked against the recompiled code:"


def positive_int(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


def positive_seconds(value):
    n = float(value)
    if not 0 < n < float("inf"):
        raise argparse.ArgumentTypeError("must be positive finite seconds")
    return n


def revision(value):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise argparse.ArgumentTypeError("must be a 40-character hexadecimal SHA")
    return value.lower()


def digest(path):
    with open(path, "rb") as f:
        h = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
        return h.hexdigest()


def capabilities(exe, timeout, env=None):
    """Require a reference runner before starting any gameplay jobs."""
    try:
        p = subprocess.run([str(exe), "--capabilities"], capture_output=True,
                           text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise ValueError("capability query timed out") from e
    except (OSError, UnicodeError) as e:
        raise ValueError("capability query could not execute") from e
    if p.returncode != 0 or p.stderr.strip():
        raise ValueError("capability query failed")
    try:
        c = json.loads(p.stdout)
    except (ValueError, TypeError) as e:
        raise ValueError("capability response is not one JSON object") from e
    if (not isinstance(c, dict) or type(c.get("schema_version")) is not int
            or c["schema_version"] != 1 or c.get("runner") != "cat_test"
            or c.get("build_mode") != "reference"
            or c.get("comparison_supported") is not True):
        raise ValueError("runner does not declare schema-1 reference comparison support")
    return c


def parse_output(out, expected_frames=None):
    """Accept the runner's complete report, not a substring saying zero errors."""
    rows, summaries, ends, interpreted, headings = {}, [], [], [], 0
    game_exits = []
    errors = []
    for line in out.splitlines():
        line = line.strip()
        if line == HEADING:
            headings += 1
        elif line.startswith("hand_"):
            m = ROW.fullmatch(line)
            if not m or m[1] in rows:
                errors.append("malformed or duplicate routine row")
            else:
                rows[m[1]] = dict(zip(("direct", "mismatches", "flag_only", "nested"),
                                      map(int, m.groups()[1:])))
        elif line.startswith("total mismatches:"):
            m = re.fullmatch(r"total mismatches: (\d+)", line)
            if m:
                summaries.append(int(m[1]))
            else:
                errors.append("malformed mismatch summary")
        elif line.startswith("game exited"):
            m = re.fullmatch(r"game exited \((\d+)\)", line)
            if m: game_exits.append(int(m[1]))
            else: errors.append("malformed game-exit marker")
        elif line.startswith("end:"):
            m = END.fullmatch(line)
            if m:
                ends.append(int(m[1]))
            else:
                errors.append("malformed completion marker")
        elif line.startswith("interpreted instructions:"):
            m = re.fullmatch(r"interpreted instructions: (\d+)", line)
            if m:
                interpreted.append(int(m[1]))
            else:
                errors.append("malformed interpreter summary")
    if headings != 1 or len(summaries) != 1 or len(interpreted) != 1:
        errors.append("missing or duplicate comparison summary")
    if len(ends) != 1:
        errors.append("missing or duplicate completion marker")
    if len(game_exits) > 1 or any(game_exits):
        errors.append("duplicate or unsuccessful game exit")
    if expected_frames is not None and len(ends) == 1 and ends[0] != expected_frames:
        if not (ends[0] < expected_frames and game_exits == [0]):
            errors.append("run did not reach requested frame count")
    mismatch = sum(r["mismatches"] for r in rows.values())
    if len(summaries) == 1 and summaries[0] != mismatch:
        errors.append("routine mismatches disagree with summary")
    if mismatch or any(summaries):
        errors.append("comparison mismatches")
    return rows, len(ends) == 1, errors


def job_args(seed, room):
    extra = ["--room", str(room)] if room >= 0 else ["--rooms"] + (["--joystick"] if room == -2 else [])
    play = ["--autoplay", str(seed)]
    if room == -3:
        play = []
        extra = ["--key", "100:39", "--key", "160:31", "--key", "240:25", "--key", "320:39",
                 "--key", "600:1d:20", "--key", "605:15:5"]
    return play + extra


def run_job(job, args, logs):
    index, seed, room = job
    mode = "room" if room >= 0 else {-1: "general", -2: "joystick", -3: "quit"}[room]
    result = {"id": f"job-{index:03d}", "seed": seed, "room": room if room >= 0 else None,
              "mode": mode, "exit_code": None, "timed_out": False, "completed": False,
              "direct_comparisons": 0, "mismatches": 0, "duration_seconds": 0,
              "evidence": [], "errors": []}
    cmd = [str(args.exe), args.cat_exe, "--hand-mode", "check", "--frames", str(args.frames)] + job_args(seed, room)
    start = time.monotonic()
    out, err = "", ""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
        result["exit_code"] = p.returncode
        out, err = p.stdout, p.stderr
        if p.returncode != 0:
            result["errors"].append(f"process exited with code {p.returncode}")
    except subprocess.TimeoutExpired as e:
        result["timed_out"] = True
        result["errors"].append("process timed out")
        out = e.stdout or ""
        err = e.stderr or ""
        if isinstance(out, bytes): out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes): err = err.decode("utf-8", errors="replace")
    except (OSError, UnicodeError) as e:
        result["errors"].append(f"process could not execute or decode output ({type(e).__name__})")
    result["duration_seconds"] = round(time.monotonic() - start, 6)
    rows, completed, errors = parse_output(out, args.frames)
    result["completed"] = completed
    result["errors"] += errors
    if err.strip():
        result["errors"].append("process wrote diagnostics to stderr")
    result["direct_comparisons"] = sum(r["direct"] for r in rows.values())
    result["mismatches"] = sum(r["mismatches"] for r in rows.values())
    if logs:
        for label, content in (("stdout", out), ("stderr", err)):
            path = logs / f"{result['id']}.{label}.log"
            # Evidence may be shared; never persist the private input pathname.
            path.write_text(content.replace(args.cat_exe, "<game-file>"), encoding="utf-8")
            result["evidence"].append(str(path))
    return result, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cat_exe")
    ap.add_argument("--seeds", type=positive_int, default=8)
    ap.add_argument("--frames", type=positive_int, default=6000)
    ap.add_argument("--exe", type=Path, default=ROOT / "build" / "rel" / ("cat_test.exe" if os.name == "nt" else "cat_test"))
    ap.add_argument("--room", type=int, choices=range(1, 8), action="append", default=[])
    ap.add_argument("--all-rooms", action="store_true")
    ap.add_argument("--jobs", type=positive_int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--timeout", type=positive_seconds, default=120)
    ap.add_argument("--source-revision", type=revision)
    ap.add_argument("--json-report", type=Path)
    a = ap.parse_args(argv)
    a.exe = a.exe.resolve()
    rooms = list(range(1, 8)) if a.all_rooms else list(dict.fromkeys(a.room))
    specs = [(s, -1) for s in range(1, a.seeds + 1)] + [(s, r) for r in rooms for s in range(1, 5)] + [(s, -2) for s in range(1, 5)] + [(1, -3)]
    report = {"schema_version": 1, "status": "FAIL", "source_revision": a.source_revision,
              "executable_sha256": None, "game_sha256": None,
              "parameters": {"seeds": a.seeds, "frames": a.frames, "rooms": rooms,
                             "jobs": a.jobs, "timeout_seconds": a.timeout},
              "jobs": [], "totals": {"expected_jobs": len(specs), "completed_jobs": 0,
                                     "direct_comparisons": 0, "mismatches": 0},
              "coverage": {"routines": {}, "uncounted": []}, "errors": []}
    known = set()
    for f in (ROOT / "src" / "game").glob("*.c"):
        known.update(re.findall(r"^void hand_([0-9a-f]{4})\(V30 \*c\)", f.read_text(), re.M))
    counts = {o: collections.Counter() for o in sorted(known)}
    logs = None
    try:
        report["executable_sha256"] = digest(a.exe)
        report["game_sha256"] = digest(a.cat_exe)
        capabilities(a.exe, a.timeout)
        if a.json_report:
            a.json_report.parent.mkdir(parents=True, exist_ok=True)
            logs = a.json_report.parent / (a.json_report.stem + ".logs")
            logs.mkdir(parents=True, exist_ok=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
            futures = [pool.submit(run_job, (i, s, r), a, logs) for i, (s, r) in enumerate(specs)]
            for future in futures:
                job, rows = future.result()
                report["jobs"].append(job)
                if set(rows) - known:
                    job["errors"].append("report contains unknown routine IDs")
                for off, values in rows.items():
                    if off in counts: counts[off].update(values)
                report["errors"].extend(f"{job['id']}: {error}" for error in job["errors"])
    except (OSError, ValueError, UnicodeError) as e:
        # Do not leak an input path through an exception's string representation.
        report["errors"].append(str(e) if isinstance(e, ValueError) else f"input/report I/O failed ({type(e).__name__})")
    for off, c in counts.items():
        report["coverage"]["routines"][off] = {k: c[k] for k in ("direct", "nested", "mismatches", "flag_only")}
        if not c["direct"] and not c["nested"]:
            report["coverage"]["uncounted"].append(off)
    report["totals"].update(completed_jobs=sum(j["completed"] and not j["errors"] for j in report["jobs"]),
                            direct_comparisons=sum(c["direct"] for c in counts.values()),
                            mismatches=sum(c["mismatches"] for c in counts.values()))
    if len(report["jobs"]) != len(specs): report["errors"].append("incomplete job set")
    if report["totals"]["direct_comparisons"] == 0: report["errors"].append("no direct comparisons were performed")
    if not report["errors"]: report["status"] = "PASS"
    for off, c in counts.items():
        tag = ("NEVER CALLED" if not c["nested"] else "OK (inside callers)") if not c["direct"] else ("OK" if not c["mismatches"] else "MISMATCH")
        print(f"  {off.upper()}  {c['direct']:8d} calls  {c['nested']:8d} nested  {c['mismatches']:5d} bad  {tag}")
    t = report["totals"]
    print(f"{len(known)} routines, {t['direct_comparisons']} calls checked, {t['mismatches']} mismatches, {len(report['coverage']['uncounted'])} never called")
    print(f"{report['status']}: {t['completed_jobs']}/{t['expected_jobs']} jobs completed")
    for error in report["errors"][:12]: print(error, file=sys.stderr)
    if a.json_report:
        try:
            a.json_report.parent.mkdir(parents=True, exist_ok=True)
            a.json_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except OSError:
            print("cannot write JSON report", file=sys.stderr)
            return 1
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
