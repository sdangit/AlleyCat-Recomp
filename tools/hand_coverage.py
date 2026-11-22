#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Syncr0ndi
"""Line coverage of the hand-written C (src/game) under check-mode autoplay runs.

Builds build/cov (clang source-based coverage, no SDL app) if needed, runs the check seeds,
and prints, per file, the percentage of lines executed and the line ranges never executed.
Code that never ran has not been compared with the original yet.

Usage: python tools/hand_coverage.py CAT.EXE [--seeds N] [--frames N] [--files lines.c,cat.c]"""
import argparse, concurrent.futures, os, re, shutil, subprocess, sys
import check
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("cat_exe")
ap.add_argument("--seeds", type=check.positive_int, default=12)
ap.add_argument("--frames", type=check.positive_int, default=10000)
ap.add_argument("--files", default="")
ap.add_argument("--build", type=Path, default=ROOT / "build" / "cov")
ap.add_argument("--exe", type=Path, help="use an existing coverage-instrumented runner without building")
ap.add_argument("--generator", help="CMake generator for a new build directory")
ap.add_argument("--compiler", default="clang")
ap.add_argument("--jobs", type=check.positive_int, default=min(4, os.cpu_count() or 1))
ap.add_argument("--timeout", type=check.positive_seconds, default=120)
ap.add_argument("--llvm-profdata")
ap.add_argument("--llvm-cov")
ap.add_argument("--room", type=int, choices=range(1, 8), action="append", default=[], help="also run seeds pinned to room N")
a = ap.parse_args()

B = a.build.resolve()
a.cat_exe = str(Path(a.cat_exe).resolve())
flags = "-fprofile-instr-generate -fcoverage-mapping"
if not a.exe:
    configure = ["cmake", "-S", str(ROOT), "-B", str(B), f"-DCMAKE_C_COMPILER={a.compiler}",
                 "-DCAT_BUILD_APP=OFF", "-DCAT_BUILD_REFERENCE=ON", f"-DCAT_EXE={a.cat_exe}",
                 f"-DPython3_EXECUTABLE={sys.executable}", f"-DCMAKE_C_FLAGS={flags}",
                 f"-DCMAKE_EXE_LINKER_FLAGS={flags}"]
    if a.generator:
        configure += ["-G", a.generator]
    subprocess.run(configure, check=True)
    subprocess.run(["cmake", "--build", str(B), "--target", "cat_test", "--parallel", str(a.jobs)], check=True)
exe = a.exe.resolve() if a.exe else B / ("cat_test.exe" if os.name == "nt" else "cat_test")
B.mkdir(parents=True, exist_ok=True)
check.capabilities(exe, a.timeout, env=dict(os.environ, LLVM_PROFILE_FILE=str(B / "capability.profraw")))


def llvm_tool(explicit, name):
    if explicit:
        return explicit
    if sys.platform == "darwin":
        found = subprocess.run(["xcrun", "--find", name], capture_output=True, text=True, check=True).stdout.strip()
        if found:
            return found
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"cannot find {name}; provide --{name}")
    return found


profdata = llvm_tool(a.llvm_profdata, "llvm-profdata")
llvm_cov = llvm_tool(a.llvm_cov, "llvm-cov")
prof = B / "prof"
prof.mkdir(parents=True, exist_ok=True)
for f in prof.glob("*.profraw"): f.unlink()


def run(job):
    seed, room = job
    env = dict(os.environ, LLVM_PROFILE_FILE=str(prof / f"s{seed}_{room}.profraw"))
    extra = ["--room", str(room)] if room >= 0 else ["--rooms"]
    p = subprocess.run([str(exe), a.cat_exe, "--hand-mode", "check", "--autoplay", str(seed), "--frames", str(a.frames)] + extra,
                       env=env, capture_output=True, text=True, timeout=a.timeout)
    rows, complete, errors = check.parse_output(p.stdout, a.frames)
    if p.returncode or p.stderr.strip() or not complete or errors:
        raise RuntimeError(f"coverage run seed={seed}, room={room} failed (exit {p.returncode}): {errors}")
    return sum(row["direct"] for row in rows.values())


jobs = [(s, -1) for s in range(1, a.seeds + 1)] + [(s, r) for r in a.room for s in range(1, 5)]
with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
    total = sum(ex.map(run, jobs))
if not total:
    raise SystemExit("no direct comparisons were performed")
if not list(prof.glob("*.profraw")):
    raise SystemExit("runner produced no coverage profiles; use an instrumented build")
subprocess.run([profdata, "merge", "-o", str(prof / "all.profdata")] + [str(p) for p in prof.glob("*.profraw")], check=True)
srcs = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src" / "game").glob("*.c"))
if a.files: srcs = [s for s in srcs if Path(s).name in a.files.split(",")]
if not srcs: raise SystemExit("no source files match --files")
out = subprocess.run([llvm_cov, "show", str(exe), f"-instr-profile={prof / 'all.profdata'}", "-show-line-counts", f"-compilation-dir={ROOT}"]
                     + srcs, capture_output=True, text=True, cwd=ROOT, check=True).stdout
cur = Path(srcs[0]).name if len(srcs) == 1 else None
lines = {cur: []} if cur else {}
for ln in out.splitlines():
    m = re.match(r"^(\S.*\.c):$", ln)
    if m: cur = Path(m.group(1)).name; lines[cur] = []; continue
    m = re.match(r"^\s*(\d+)\|\s*([0-9.kM]*)\|(.*)$", ln)
    if m and cur: lines[cur].append((int(m.group(1)), m.group(2), m.group(3)))
if not any(lines.values()): raise SystemExit("llvm-cov returned no source coverage lines")
for name, ls in lines.items():
    counted = [(n, cnt, t) for n, cnt, t in ls if cnt != ""]
    zero = [n for n, cnt, t in counted if cnt == "0"]
    pct = 100 * (len(counted) - len(zero)) / max(1, len(counted))
    print(f"{name}: {pct:.1f}% of {len(counted)} lines")
    ranges, start, prev = [], None, None
    for n in zero:
        if start is None: start = prev = n
        elif n == prev + 1: prev = n
        else: ranges.append((start, prev)); start = prev = n
    if start is not None: ranges.append((start, prev))
    if ranges: print("   never ran: " + ", ".join(f"{s}" if s == e else f"{s}-{e}" for s, e in ranges))
