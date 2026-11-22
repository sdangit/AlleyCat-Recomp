#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Syncr0ndi
"""Stage, audit and archive a macOS release. Never uploads or notarizes software."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GAME_SHA256 = "4979c8867826e08881d1d4bec95c95d6bc1ac70fd21050ccdb4f733a50d7bfdd"
SDL_VERSION = "2.30.9"
SDL_SHA256 = "24b574f71c87a763f50704bbb630cbe38298d544a1f890f099a4696b1d6beba4"
APP_FILES = {"Contents/Info.plist", "Contents/MacOS/AlleyCat", "Contents/Resources/AlleyCat.icns",
             "Contents/_CodeSignature/CodeResources"}
REQUIRED_APP_FILES = APP_FILES - {"Contents/_CodeSignature/CodeResources"}
MACH_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


class AuditError(Exception):
    pass


def run(command):
    p = subprocess.run([str(x) for x in command], capture_output=True, text=True)
    if p.returncode:
        raise AuditError(f"{command[0]} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout + p.stderr


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def safe_version(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise argparse.ArgumentTypeError("version must contain only letters, numbers, dot, underscore or hyphen")
    return value


def revision(value):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise argparse.ArgumentTypeError("source revision must be a 40-character hexadecimal SHA")
    return value.lower()


def bundle_inventory(app):
    if app.is_symlink() or not app.is_dir() or app.suffix != ".app":
        raise AuditError("app must be a real .app directory, not a symlink")
    found = set()
    directories = {"Contents", "Contents/MacOS", "Contents/Resources", "Contents/_CodeSignature"}
    for p in app.rglob("*"):
        rel = p.relative_to(app).as_posix()
        if p.is_symlink(): raise AuditError(f"bundle symlink is not permitted: {rel}")
        if p.is_dir():
            if rel not in directories: raise AuditError(f"unexpected bundle directory: {rel}")
        elif p.is_file():
            if rel not in APP_FILES: raise AuditError(f"unexpected bundle file: {rel}")
            found.add(rel)
        else:
            raise AuditError(f"unsupported bundle entry: {rel}")
    if not REQUIRED_APP_FILES <= found:
        raise AuditError("bundle is missing required release files: " + ", ".join(sorted(REQUIRED_APP_FILES - found)))
    return found


def inspect_bundle(app):
    bundle_inventory(app)
    if sha256(app / "Contents/Resources/AlleyCat.icns") != sha256(ROOT / "release/macos/AlleyCat.icns"):
        raise AuditError("bundle icon differs from repository-owned artwork")
    run(["plutil", "-lint", app / "Contents/Info.plist"])
    with (app / "Contents/Info.plist").open("rb") as f: info = plistlib.load(f)
    if info.get("CFBundleExecutable") != "AlleyCat" or info.get("CFBundlePackageType") != "APPL":
        raise AuditError("bundle metadata does not identify the release application")
    if not isinstance(info.get("CFBundleIdentifier"), str) or not info["CFBundleIdentifier"]:
        raise AuditError("missing bundle identifier")
    if info.get("CFBundleIconFile") != "AlleyCat.icns" or not info.get("NSHighResolutionCapable"):
        raise AuditError("missing icon or high-DPI metadata")
    deployment = info.get("LSMinimumSystemVersion", "")
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", deployment):
        raise AuditError("missing or malformed deployment target")
    exe = app / "Contents/MacOS/AlleyCat"
    if not exe.stat().st_mode & stat.S_IXUSR: raise AuditError("bundle executable is not executable")
    data = exe.read_bytes()
    if data[:4] not in MACH_MAGICS: raise AuditError("bundle executable is not Mach-O")
    arch = run(["lipo", "-archs", exe]).strip()
    if arch != "arm64": raise AuditError(f"initial release requires arm64 only, found {arch}")
    loads = run(["otool", "-l", exe])
    versions = re.findall(r"\bminos\s+(\d+\.\d+(?:\.\d+)?)", loads)
    def version_tuple(text):
        parts = tuple(map(int, text.split(".")))
        return parts + (0,) * (3 - len(parts))
    if not versions or any(version_tuple(x) != version_tuple(deployment) for x in versions):
        raise AuditError("Mach-O minimum OS differs from bundle metadata")
    deps = []
    for line in run(["otool", "-L", exe]).splitlines()[1:]:
        dep = line.strip().split(" (", 1)[0]
        if not dep: continue
        if not dep.startswith(("/System/Library/", "/usr/lib/")) or ".." in Path(dep).parts:
            raise AuditError(f"non-system runtime dependency: {dep}")
        deps.append(dep)
    if not deps: raise AuditError("could not inspect executable dependencies")
    for marker in (b"/Users/", b"/home/", b"/private/tmp/", b"/opt/homebrew/"):
        if marker in data: raise AuditError("executable contains a developer-machine path")
    return info, exe, arch, deps


def byte_matches(program, game):
    """Existing filtered 32-byte heuristic, including the last possible window."""
    grams = {game[i:i + 32] for i in range(max(0, len(game) - 31)) if len(set(game[i:i + 32])) > 4}
    return sum(program[i:i + 32] in grams for i in range(max(0, len(program) - 31)))


def read_game(path):
    if path.stat().st_size != 55067 or sha256(path) != GAME_SHA256:
        raise AuditError("game file is not the known original CAT.EXE")
    return path.read_bytes()


def sdl_license(build):
    cache = build / "CMakeCache.txt"
    if not cache.is_file(): raise AuditError("build directory lacks CMakeCache.txt")
    values = {}
    for line in cache.read_text(encoding="utf-8").splitlines():
        if not line.startswith(("//", "#")) and "=" in line:
            key, value = line.split("=", 1)
            values[key.split(":", 1)[0]] = value
    source = Path(values.get("FETCHCONTENT_SOURCE_DIR_SDL2") or build / "_deps/sdl2-src")
    header = source / "include/SDL_version.h"
    if not header.is_file(): raise AuditError("cannot verify SDL source version in build")
    text = header.read_text(encoding="utf-8")
    for name, number in (("SDL_MAJOR_VERSION", "2"), ("SDL_MINOR_VERSION", "30"), ("SDL_PATCHLEVEL", "9")):
        if not re.search(r"#define\s+" + name + r"\s+" + number + r"\b", text):
            raise AuditError("SDL source version differs from the repository pin")
    license_file = source / "LICENSE.txt"
    if not license_file.is_file(): raise AuditError("SDL license missing from build")
    return license_file


def sign_bundle(app, identity):
    if identity == "-":
        run(["codesign", "--force", "--sign", "-", "--timestamp=none", app])
    else:
        run(["codesign", "--force", "--sign", identity, "--options", "runtime", "--timestamp", app])
    run(["codesign", "--verify", "--strict", app])
    details = run(["codesign", "-d", "--verbose=4", app])
    if identity == "-":
        if "Signature=adhoc" not in details: raise AuditError("expected ad-hoc signature")
        state = "ad-hoc"
    else:
        if "Authority=Developer ID Application:" not in details or "runtime" not in details:
            raise AuditError("distribution signing requires a Developer ID Application identity and hardened runtime")
        state = "developer-id"
    return {"state": state, "notarization": "NOT_RUN"}


def package(a):
    if sys.platform != "darwin": raise AuditError("macOS packaging requires macOS command-line tools")
    if a.output.exists() or a.output.is_symlink(): raise AuditError("output directory already exists; choose a fresh staging root")
    app = a.app.absolute()
    build = a.build.resolve()
    info, _, _, _ = inspect_bundle(app)
    license_file = sdl_license(build)
    game = read_game(a.game_file) if a.game_file else None
    # Everything below is created under a new caller-selected directory. Never remove a preexisting tree.
    a.output.mkdir(parents=True)
    stage = a.output / "staging/AlleyCat"
    stage.mkdir(parents=True)
    staged_app = stage / "AlleyCat.app"
    shutil.copytree(app, staged_app)
    shutil.copy2(ROOT / "release/macos/README.txt", stage / "README.txt")
    licenses = stage / "LICENSES"
    licenses.mkdir()
    shutil.copy2(ROOT / "LICENSE", licenses / "AlleyCat-port-LICENSE.txt")
    shutil.copy2(license_file, licenses / "SDL2-LICENSE.txt")
    signing = sign_bundle(staged_app, a.sign_identity)
    info, exe, arch, deps = inspect_bundle(staged_app)
    if game is not None and byte_matches(exe.read_bytes(), game):
        raise AuditError("release executable matches filtered 32-byte content from CAT.EXE")
    files = []
    for p in sorted(stage.rglob("*")):
        if p.is_file():
            files.append({"path": p.relative_to(stage.parent).as_posix(), "sha256": sha256(p),
                          "size": p.stat().st_size, "mode": oct(stat.S_IMODE(p.stat().st_mode))})
    name = f"AlleyCat-{a.version}-macOS-{arch}.zip"
    archive = a.output / name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(stage, "AlleyCat/")
        for p in sorted(stage.rglob("*")): z.write(p, p.relative_to(stage.parent).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise AuditError("archive CRC verification failed")
        actual = {i.filename for i in z.infolist() if not i.is_dir()}
        if actual != {f["path"] for f in files}: raise AuditError("archive inventory differs from staging")
        mode = z.getinfo("AlleyCat/AlleyCat.app/Contents/MacOS/AlleyCat").external_attr >> 16
        if not mode & stat.S_IXUSR: raise AuditError("archive lost executable permission")
    with tempfile.TemporaryDirectory(prefix="extract-", dir=a.output) as tmp:
        run(["ditto", "-x", "-k", archive, tmp])
        extracted = Path(tmp) / "AlleyCat/AlleyCat.app"
        inspect_bundle(extracted)
        run(["codesign", "--verify", "--strict", extracted])
        for entry in files:
            if sha256(Path(tmp) / entry["path"]) != entry["sha256"]:
                raise AuditError("extracted file checksum differs from staging")
    manifest = {"schema_version": 1, "source_revision": a.source_revision, "version": a.version,
                "architecture": arch, "deployment_target": info["LSMinimumSystemVersion"],
                "sdl": {"version": SDL_VERSION, "archive_sha256": SDL_SHA256},
                "signing": signing, "content_audit": "PASS" if game is not None else "NOT_RUN",
                "archive": {"name": name, "sha256": sha256(archive)}, "files": files,
                "bundle": {"name": "AlleyCat.app", "identifier": info["CFBundleIdentifier"], "executable": "AlleyCat"},
                "dependencies": deps}
    manifest_path = a.output / f"{archive.stem}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"archive": str(archive.resolve()), "manifest": str(manifest_path.resolve())}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--version", required=True, type=safe_version)
    ap.add_argument("--source-revision", required=True, type=revision)
    audit = ap.add_mutually_exclusive_group(required=True)
    audit.add_argument("--game-file", type=Path)
    audit.add_argument("--skip-game-audit", action="store_true")
    ap.add_argument("--sign-identity", default="-", help="codesign identity; default '-' is local ad-hoc signing, never notarized")
    a = ap.parse_args(argv)
    try:
        print(json.dumps(package(a)))
    except (AuditError, OSError, ValueError, plistlib.InvalidFileException, zipfile.BadZipFile) as e:
        print(f"packaging failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
