#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Subprocess fixture; no game data or generated game code."""
import json
import os
import signal
import sys
import time

scenario = os.environ.get("CHECK_FIXTURE", "pass")
if "--capabilities" in sys.argv:
    caps = {"schema_version": 1, "runner": "cat_test", "build_mode": "reference", "comparison_supported": True}
    if scenario == "release":
        caps.update(runner="cat_test_release", build_mode="release", comparison_supported=False)
    elif scenario == "bad_capability":
        caps["comparison_supported"] = "true"
    elif scenario == "bad_schema":
        caps["schema_version"] = True
    elif scenario == "extra_field":
        caps["optional"] = 123
    elif scenario == "malformed_capability":
        print("not json")
        sys.exit(0)
    print(json.dumps(caps))
    sys.exit(0)
if scenario == "timeout": time.sleep(10)
if scenario == "signal": os.kill(os.getpid(), signal.SIGTERM)
if scenario == "legitimate_exit": print("game exited (0)")
print("hand-written routines checked against the recompiled code:")
if scenario == "malformed_row":
    print("hand_0000: garbage")
elif scenario != "empty":
    bad = 1 if scenario == "mismatch" else 0
    print(f"  hand_0000: 1 calls checked, {bad} mismatches, 0 flag-only differences, 0 nested")
print("total mismatches: 0")
print("interpreted instructions: 0")
if scenario != "truncated":
    frames = 2 if scenario in ("premature", "legitimate_exit") else 6000
    print(f"end: frame {frames}, vram 01234567, CS:IP F000:001A")
if scenario == "stderr": print("unexpected diagnostic", file=sys.stderr)
sys.exit(9 if scenario == "exit" else 0)
