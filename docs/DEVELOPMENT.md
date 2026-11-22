# Development guide

## Requirements

- Python 3.10+ and CMake 3.20+.
- macOS: Apple Command Line Tools (`clang` and a macOS SDK). A native Makefiles build is sufficient.
- Windows: [LLVM-MinGW](https://github.com/mstorsjo/llvm-mingw) and Ninja.
- Your own `CAT.EXE` (55,067 bytes, SHA-256 `4979c886…7bfdd`) for playing or reference comparisons.
  Release-only compilation does not need it.

CMake downloads SDL2 2.30.9 itself, pinned by hash.

## Building

### macOS release

```sh
cmake -S . -B build/macos-release \
  -DCAT_BUILD_REFERENCE=OFF -DCAT_BUILD_APP=ON \
  -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0
cmake --build build/macos-release --parallel 4
open build/macos-release/AlleyCat.app
```

If CMake selects an older Python, add `-DPython3_EXECUTABLE=/absolute/path/to/python3.10-or-newer`.
macOS 11.0 is the default deployment target for native Mac builds; explicit toolchain, environment,
and command-line settings take precedence. This does not imply every OS version has been tested.

### Windows reference and release targets

```powershell
cmake -S . -B build/rel -G Ninja -DCMAKE_C_COMPILER=clang -DCAT_EXE="C:/path/to/CAT.EXE"
cmake --build build/rel
```

For Windows release-only compilation, replace `-DCAT_EXE=...` with `-DCAT_BUILD_REFERENCE=OFF`.
The default reference option remains ON for compatibility with the original development workflow.

| Target | What it is |
|---|---|
| `alleycat_release` | The game, built from the hand-written C only. This is what ships. |
| `alleycat` | The development build: hand-written and recompiled code together, so either can run. |
| `cat_test` | Headless test runner (scripted keys, PNG screenshots, WAV audio, the checker). |
| `cat_test_release` | The test runner built like the release, without the recompiled code. |

`CAT_BUILD_APP=OFF` skips SDL and both GUI targets. `CAT_BUILD_REFERENCE=OFF` skips generation,
`cat_test`, and the development GUI. `cat_test_release` is available in all four combinations.
Only the Mac release GUI is a bundle; the development GUI and test runners remain plain executables.

The recompiled C is generated from `CAT.EXE` into the build folder. It's derived from the game, so
it's never committed (`.gitignore` excludes `build/`, `dist/` and every `.exe`).

## Making a release

### Windows

```powershell
python tools/make_release.py C:/path/to/CAT.EXE
```

This writes `dist/AlleyCat/` and `dist/AlleyCat-Windows.zip`:
- `alleycat.exe`
- `README.txt`
- `LICENSES/`, with this port's MIT licence and SDL2's zlib licence

It refuses to build the zip if its filtered 32-byte audit finds a match against `CAT.EXE`.

### macOS

Use a fresh staging directory and the release `.app`, not the reference GUI. Set `CAT_EXE` to
your private game-file path and `SOURCE_REVISION` to the commit used for the build.

```sh
python3 tools/make_macos_release.py \
  --app build/macos-release/AlleyCat.app --build build/macos-release \
  --output dist/macos-local --version 1.0-macos \
  --source-revision "$SOURCE_REVISION" --game-file "$CAT_EXE"
```

The packager prints the archive and external checksum-manifest paths. It validates allowed
contents, architecture, system-library dependencies, plist metadata, and a filtered 32-byte
comparison against the original game file. The byte comparison is a heuristic, not a provenance
proof. `--skip-game-audit` is for asset-free structural checks and records that audit as not run.
The script does not overwrite an existing staging root and never submits for notarization.
It ad-hoc signs the staged copy by default. `--sign-identity "Developer ID Application: ..."`
selects an available identity and hardened runtime; notarization/stapling remain separate release steps.

Local unsigned/ad-hoc artifacts and Developer ID distribution artifacts have different signing
states. Inspect the manifest; do not describe a local build as notarized. The Windows packager
and release filenames are unchanged.

## Checking the hand-written code

For macOS, build the reference headless runner with the exact original file:

```sh
cmake -S . -B build/macos-check -DCAT_BUILD_APP=OFF \
  -DCAT_BUILD_REFERENCE=ON -DCAT_EXE="$CAT_EXE"
cmake --build build/macos-check --parallel 4
python3 tools/check.py "$CAT_EXE" --all-rooms \
  --exe build/macos-check/cat_test --jobs 4 --timeout 120 \
  --source-revision "$SOURCE_REVISION" \
  --json-report build/macos-agent/evidence/check.json
```

The Windows equivalent retains the original default executable location:

```powershell
python tools/check.py C:/path/to/CAT.EXE --all-rooms
```

This runs many autoplayed games in check mode. For every call to a hand-written routine, the
recompiled original runs too, from the same state, and the two are compared:
- registers and flags, limited to the ones still used afterwards (`tools/liveness.py`);
- memory;
- port I/O and BIOS timer calls, recorded and replayed;
- interrupts, replayed at the same point.

The report lists calls checked and mismatches per routine. [REWRITE.md](REWRITE.md) describes the
method.

The checker verifies the runner's `--capabilities` before starting. Release runners reject check
mode; unknown modes, process failures, timeouts, incomplete output, and zero aggregate comparisons
fail the run. JSON reports include the executable digest and caller-supplied source revision;
the latter is metadata rather than a revision inferred from the binary. Coverage gaps are reported
separately from a zero-mismatch result. Keep generated sources, PNGs, WAVs, and private logs in
ignored build directories; public CI uses no game file.

Run the asset-free Python tests with `python3 -m unittest discover -s tests`. The coverage tool's
`--help` describes explicit build/runner paths and toolchain-specific LLVM tool selection.

## Test runner

```powershell
build/rel/cat_test.exe C:/path/to/CAT.EXE --frames 600 --key 100:39 --shot 300:title.png --status 60
```

| Option | Meaning |
|---|---|
| `--frames N` | Stop after N frames. |
| `--key FRAME:SC[:LEN]` | Press XT scancode `SC` (hex) at `FRAME` for `LEN` frames. |
| `--shot FRAME:FILE.png` | Save a screenshot. |
| `--wav FILE.wav` | Record the speaker. |
| `--status N` | Print a video-memory hash every N frames. |
| `--autoplay SEED` | Random but plausible play, including menus, pauses and restarts. |
| `--rooms`, `--room N` | Jump into rooms (or always room N) for coverage. |
| `--joystick` | Play with the emulated joystick. |
| `--hand-mode gen\|on\|check` | Recompiled code only, hand-written code (default), or compare both. |
| `--coverage FILE` | Write which recompiled routines ran. |

Both runners support `--capabilities` without a game argument. On macOS, use `cat_test` rather
than `cat_test.exe`. The SDL GUI additionally accepts `CAT.EXE --selftest N` to render N frames,
save a window image, and exit with a failure status if the capture cannot be saved.

## Mac state and isolated testing

The application uses `SDL_GetPrefPath("sdangit", "AlleyCat")` for Mac settings, with `screenshots/`
and `logs/` subdirectories. It never needs to write inside its bundle. A file selected through the
native picker is remembered; an explicit command-line path is used for that invocation only.
Missing saved files return to the picker, and content validation applies to every input path.

For disposable tests, set `ALLEYCAT_STATE_DIR` to an absolute directory. Relative paths and
unusable locations are errors. Keep test state outside your normal preferences. Use
`python3 tools/validate_macos.py --help` for automated build/artifact checks; native picker and
desktop interaction evidence is recorded separately in [MACOS_VALIDATION.md](MACOS_VALIDATION.md).

## Branch maintenance

`main` follows `upstream/main` from Syncr0ndi and contains no port commits. The long-lived `macos`
branch contains this fork's work. Fast-forward `main` when upstream advances, then merge upstream
into `macos` at an integration boundary. Do not reset a divergent main or rewrite a shared macOS
branch. Agent task branches use `macos-task-*`; `macos/task-*` cannot coexist with a branch named
`macos` in Git's ref namespace. See [MACOS_PLAN.md](MACOS_PLAN.md) for ownership and validation gates.

## Source layout

| Path | Contents |
|---|---|
| `src/game/` | The hand-written game, in 30 modules (cat, dog, mice, windows, the rooms, sound, menus, main loop…), plus the check harness `hand.c`. |
| `src/pc/` | The IBM PC model: memory, a small BIOS in C, 8253 timer and speaker, keyboard and 8259, CGA timing and colours, game port. `font8x8.c` is a font drawn for this project. |
| `src/cpu/` | The 8086/V30 CPU core, used by the recompiled code and the checker. |
| `src/app/` | The SDL2 front end (`main.c`), the headless runner (`test_main.c`), the `CAT.EXE` check and the PNG writer. |
| `tools/catmap.py` | Maps the code by recursive descent: 269 routines, 8,482 instructions. |
| `tools/catrecomp.py` | The static recompiler: turns the map into C, and routes calls to the hand-written routines. |
| `tools/v30dec.py` | Instruction decoder. |
| `tools/check.py`, `liveness.py`, `coverage.py`, `hand_coverage.py`, `callgraph.py` | The checker and analysis tools. |
| `tools/hand_entries.py`, `make_release.py` | Release routine table and packaging. |
