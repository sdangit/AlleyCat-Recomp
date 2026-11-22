# SPDX-License-Identifier: MIT
"""Run the checker with Python fixtures as portable executable stand-ins.

Only the fixture launch gains sys.executable; all actual subprocess timeout,
return-code, output and report handling remains the production checker code.
"""
from pathlib import Path
import runpy
import subprocess
import sys

run = subprocess.run
fixture = str(Path(__file__).with_name("runner.py").resolve())


def launch(cmd, *args, **kwargs):
    if str(cmd[0]) == fixture:
        cmd = [sys.executable, *cmd]
    return run(cmd, *args, **kwargs)


subprocess.run = launch
runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/check.py"), run_name="__main__")
