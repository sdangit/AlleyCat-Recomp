# macOS implementation validation

Status: **ENGINEERING_COMPLETE** (G01–G09 passed); distribution qualification remains **NOT_RUN**.

Validation date: 21 November 2026. The implementation is on `macos`; `main` remains at upstream
revision `ed19308f2e73100fbe4fb09dd3585f083ff7361b`. No branch, artifact, or game data was pushed
or published. See the [execution plan](MACOS_PLAN.md) and [task ledger](macos/tasks.json).

## Scope and environment

The initial artifact is a native Apple Silicon application. Validation used macOS 27.3 on arm64,
Apple Clang 21.0.0, SDK 27.2, CMake 4.5.1, Python 3.14, and the pinned SDL2 2.30.9 source.
The app and Mach-O deployment target are 11.0. That setting is not evidence of testing on macOS 11.
The handwritten game, CPU model, and PC behavior were preserved.

Release-only builds need no original game file or generated reference code. Reference comparisons
used a privately supplied 55,067-byte file with SHA-256
`4979c8867826e08881d1d4bec95c95d6bc1ac70fd21050ccdb4f733a50d7bfdd`.
The original file was read only. Disposable copies, settings, raw logs, generated images/audio,
and reference code remain in ignored build directories; none are in the release archive or Git.

## Results

| Gate | Result and evidence |
|---|---|
| G01 Build separation | All four reference/app option combinations passed. Release builds configure without game data; reference builds reject absent or incorrect data. Python 3.9 is rejected. Explicit deployment-target overrides work. A fresh integrated ARM64 release build passed. |
| G02 Checker integrity | Capability queries work without assets. Release runners reject generated/check/unknown modes. All 21 shared Python tests passed. Negative fixtures cover failed processes, timeouts, incomplete/malformed output, missing comparisons, schema/identity errors, inconsistent schedules/counts, and report-write failures. |
| G03 Game comparisons | All 41 all-rooms jobs completed: **40,937,961 direct comparisons, zero mismatches**. See coverage details below. |
| G04 Deterministic release | All six baseline video hashes matched; zero interpreted instructions. Saved PNG structure/content and WAV format/nonzero samples passed. |
| G05 Native interaction | First-launch picker, cancellation, invalid-file retry, valid selection, persisted relaunch, missing-file recovery, keyboard/menu/gameplay input, fullscreen toggling, screenshot saving, and window close passed through native desktop automation and process/file checks. |
| G06 Storage/relocation | Paths containing spaces and accented characters passed. A relocated, read-only bundle ran successfully and remained byte-for-byte unchanged. State and screenshots were written outside the bundle. Explicit CLI input was not persisted. A screenshot destination that could not be written produced exit status 1. |
| G07 Package | Allowlist, private byte audit, icon/plist, arm64 and system dependencies, licenses, ZIP checksums/permissions, and strict ad-hoc signature passed. The extracted archive launched through macOS Launch Services, rendered the game, saved a PNG outside the bundle, and closed normally. File hashes and signature still matched afterward. |
| G08 Windows preservation | Release GUI and headless runner compiled successfully to x86-64 PE executables using official LLVM-MinGW 20261117 on the Mac host. Shared Python checks passed. This is cross-compilation evidence; Windows GUI/runtime execution was not performed. |
| G09 Independent review | Passed at implementation revision `f5ce0eb`. A fresh reviewer independently checked all 21 Python tests, archive inventory/hashes/permissions, plist, architecture, dependencies, strict signature, preserved comparison evidence, and final docs. All findings were resolved; no release blockers remain. |
| G10 Distribution | **NOT_RUN**. Local artifacts use ad-hoc signing. No usable Developer ID Application identity was found; notarization/stapling and external publication were not performed. |

The full comparison report was produced from `f7fa8cf78df0362e55131dc5478f5608265e270e` and is
bound to reference-runner SHA-256 `a731ac3d3a231ce39e267f38a5b540402696b577cdc40b14166881e2f2632b6e`.
Later changes concern packaging, the icon, SDL diagnostic source-path removal, CI, validation
automation, and documentation. They do not change the compared game routines or reference runner;
the expensive suite is retained rather than relabeled as a run on another commit.

Of 260 instrumented routines, 63 had direct comparisons and 184 others were counted inside checked
callers. Thirteen remained uncounted: `0000`, `10DD`, `1166`, `1799`, `1D6E`, `2706`, `3BA3`,
`56F4`, `5704`, `597F`, `5A1C`, `5A90`, `5C9E`. Zero mismatches applies to exercised paths;
it does not prove exhaustive equivalence or coverage of every input.

The seed-1, 6,000-frame release run with room autoplay matched these video-memory hashes at each
1,000-frame interval: `e594e876`, `6ab7983c`, `a8cd91e7`, `d3d5664c`, `259e94eb`, `04d420cc`.
Audio samples were generated and validated automatically. The user's earlier observation of audible
sound is separate evidence; a nonzero WAV alone does not establish physical speaker playback.

## Local artifact

Implementation revision: `f5ce0eb6088c7b57495fbfe1f8309cd7180cc537`. Documentation/evidence commits
may follow without changing the artifact source. The fresh release build used `072bab78499cd1b6abc6710e1eef0bb21be737cb`; its build/runtime/resource inputs were verified unchanged through the implementation revision.

- App: `dist/macos-local/staging/AlleyCat/AlleyCat.app`
- Archive: `dist/macos-local/AlleyCat-1.0-macos-local-macOS-arm64.zip`
- External manifest: `dist/macos-local/AlleyCat-1.0-macos-local-macOS-arm64.manifest.json`
- ZIP SHA-256: `4e351c7d498f22b4476e7d569c70b4facc98614706108aeb4a4ddf34537c9c93`
- Signing: ad-hoc; notarization: `NOT_RUN`; private content audit: `PASS`.

The manifest lists each shipped file with its hash, size, and mode. The content comparison uses
a filtered 32-byte heuristic and is not a proof of provenance. The exact allowlist and
repository-owned icon checks provide separate structural evidence.

## Reproduction and evidence

Use the build, checker, and packaging commands in [DEVELOPMENT.md](DEVELOPMENT.md). The local
`tools/validate_macos.py` report covers only its requested automated checks. It deliberately leaves
native UI, independent review, and distribution gates unclaimed. The coordinator combines that
report with the separate evidence below and updates the task ledger.

Private evidence in this checkout is under `build/macos-agent/evidence/`:

- `check-all-rooms.json` and its log: complete reference comparisons and coverage.
- `native-ui.json`: native desktop observations and process exit checks.
- `runtime-automated.json` and named logs: persistence, relocation, and write-error checks.
- `windows-crosscompile.json`, configure/build logs: Windows toolchain and executable results.
- `signing-availability.json`: identity availability without private credential material.
- `final-automated.json` and its logs: final checks, 21 tests, media, and private packaging audit.
- `extracted-launch.json`: final archive launch and unchanged-file verification.
- `aggregate.json`: coordinator-combined gate results and build provenance.
- `independent-review.json`: independent review and resolved findings.

Agent worktrees retain their focused build-matrix, CLI, PNG failure, and negative-test evidence.
These local paths are operational evidence, not dependencies required to build the project.

## Limits

Older macOS releases, physical Intel Macs, universal binaries, physical controllers/Bluetooth,
Windows gameplay, and a separate clean Mac were not tested. Hosted GitHub Actions jobs are configured
but have not been run remotely because this branch has not been pushed. Ad-hoc signing is suitable
for local testing and does not make the archive Developer ID signed, notarized, or distribution-ready.
