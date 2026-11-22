# macOS port feasibility assessment

Assessment date: 21 November 2026. Repository revision: `ed19308f2e73100fbe4fb09dd3585f083ff7361b`.

A native macOS port is technically feasible. The existing handwritten game, PC hardware model, and SDL2 front end can compile into an Apple Silicon executable and display the game without changing their implementation. The current checkout nevertheless has build defects and lacks the file selection, writable storage locations, application packaging, and distribution support expected of a Mac application.

This assessment records source findings and local experiments. It does not establish an implementation schedule, select a minimum macOS version, or authorize a porting plan. All compilation workarounds and generated artifacts were confined to a temporary audit directory; the repository's implementation remains unchanged.

## Evidence and scope

The audit covered the CMake build, all C source compilation units, the Python generation and verification tools, release packaging, and existing documentation. The host reported macOS 27.3 on `arm64`, Apple Clang 21.0.0, and CMake 4.5.1. The default Python was 3.9.6; Python 3.14.10 was also available.

The build experiments used `-include stddef.h` to work around the missing declaration described below and Python 3.14.10 for generation. These are diagnostic overrides, not committed fixes. The exact SDL2 2.30.9 archive specified by CMake was downloaded and its SHA-256 verified against the repository's pin.

| Experiment | Result | What it establishes |
|---|---|---|
| Original CMake configuration without a game file | Failed at `CMakeLists.txt:21` | All configurations currently require the original executable. |
| Compile representative original files with Apple Clang | Failed at `src/pc/pc.h:74`, unknown `size_t` | The checkout does not compile unchanged with this toolchain. |
| Generate the release routine table using Python 3.9.6 | Failed on `Path.write_text(..., newline=...)` | The declared Python 3.8 minimum is insufficient. |
| Generate the same table using Python 3.14.10 | Passed; 260 entries | The release table can be generated independently of the original game file. |
| Syntax-check all 41 repository C files in release mode with `-Wall -Wextra` and the header override | Passed without diagnostics | No additional source compile problems appeared in that configuration. |
| Build the headless release directly for `arm64` and `x86_64` | Both linked as Mach-O executables | The handwritten game and machine code compile for both Mac architectures. |
| Build all four repository executable targets with the exact SDL2 pin and diagnostic overrides | Passed | The development build, generated C, release build, and both test runners build on this Apple Silicon host. |
| Run 6,000 frames of seeded room autoplay on the ARM release runner | Passed; zero interpreted instructions | The handwritten game executes through a substantial scripted run. |
| Repeat the same run using the Intel binary on the ARM host | Passed; all six sampled video-memory hashes matched | The tested paths agree across ARM execution and macOS Intel translation; physical Intel hardware remains untested. |
| Run the pinned-SDL graphical release probe with `--selftest 120` | Passed; screenshot saved and inspected | A real macOS window renders the recognizable title screen at 4:3. |
| User observation of the graphical launch test | User confirmed both graphics and sound | Audible output worked during that launch on the tested Mac. |
| All-room generated-versus-handwritten checker on ARM | Passed; 40,937,961 calls checked, zero mismatches; 13 routines reported never called | Strong agreement on exercised routines, with specific coverage limits below. |

The initial GUI launch inside the execution sandbox failed because SDL could not discover a display. The same probe succeeded outside the sandbox. That first failure was an environment restriction, not evidence of a game rendering defect.

An initial link probe used the installed `sdl2-compat` library. The later static SDL2 2.30.9 build supersedes that dependency evidence: `otool -L` on the pinned probe showed Apple system libraries and frameworks, with no Homebrew or SDL dynamic-library dependency.

## Architecture and portability

The most favorable feature is the separation between the game and host services:

| Component | Current responsibility | macOS implication |
|---|---|---|
| `src/game/` | Handwritten C routines using emulated registers and game memory | Reusable; there is no Windows API dependency in the game routines. |
| `src/cpu/` | CPU state, instruction semantics, dispatch, BIOS transitions, interpreter fallback | Compiles for ARM and Intel. The model represents the guest PC rather than requiring an x86 host. |
| `src/pc/` | CGA graphics, timer, speaker synthesis, keyboard, joystick, executable loading | Host-independent C with callbacks for presentation and pacing. |
| `src/app/main.c` | Window, renderer, events, controllers, audio, paths, file selection | SDL2 already supplies most host functionality. File selection and storage policy are the main platform gaps. |
| `src/app/test_main.c` | Deterministic scripted execution, hashes, screenshots, WAV output | Provides a useful way to verify the game independently of the desktop UI. |
| `tools/` | Static recompilation, comparison, coverage, release assembly | Mostly portable Python, with version and executable-name assumptions. |

The release is native C, but it still depends on the CPU and PC models. CMake links `cpu86`, including `v30_interp.c`, through `pcmachine`; `v30_dispatch()` can fall back to the interpreter if it has no mapped routine. Consequently, the README's description of native game execution should be distinguished from a claim that no interpreter code exists in the binary. The observed release runs reported zero interpreted instructions. Removing the CPU model is unnecessary for macOS feasibility. See [CMakeLists.txt](../CMakeLists.txt), [v30.c](../src/cpu/v30.c), and [REWRITE.md](REWRITE.md).

No handwritten host assembly, JIT code generation, DirectX, Windows graphics API, or Windows audio API was found in the application's source. The original DOS executable is loaded and validated as input data; macOS does not have to execute it as a Windows or DOS program.

## Confirmed build defects

### Missing standard header

[`src/pc/pc.h:74`](../src/pc/pc.h#L74) declares `pc_init(..., size_t exe_len, ...)`, but the header includes neither `<stddef.h>` nor another header that guarantees `size_t`. Several files include `pc.h` before their standard library headers, so Apple Clang rejects them immediately.

Supplying `-include stddef.h` allowed every repository C file to pass the release-mode compilation probe. This isolates the observed failure to header completeness. A normal port would need a source-level correction; the successful diagnostic build does not mean an unmodified checkout builds today.

### Python minimum does not match the tools

[`CMakeLists.txt:23`](../CMakeLists.txt#L23) accepts Python 3.8 or newer. Both [`tools/hand_entries.py:32`](../tools/hand_entries.py#L32) and [`tools/catrecomp.py:563`](../tools/catrecomp.py#L563) call `Path.write_text` with the `newline` keyword. Python added that parameter in 3.10. The local Python 3.9.6 reproduced the resulting `TypeError`; Python 3.14.10 succeeded. The effective minimum for the current writing calls is therefore Python 3.10. [Python pathlib documentation](https://docs.python.org/3/library/pathlib.html#pathlib.Path.write_text).

### Release compilation is coupled to development generation

CMake validates `CAT_EXE` and runs the static recompiler during configuration, before considering any target. The release executable's sources do not require that generated game code: its separate table generator reads only handwritten function names and addresses. Nevertheless, CMake cannot currently configure even a release-only build without the known original executable.

The `cat_test_release` target is also inside `if(CAT_BUILD_APP)`. Setting `CAT_BUILD_APP=OFF` removes the release runner along with the SDL application, leaving only the development runner. These are build-structure limitations rather than Mac CPU limitations. They matter for automated builds and for separating distributable release code from locally generated reference code. See [CMakeLists.txt:19](../CMakeLists.txt#L19) and [CMakeLists.txt:84](../CMakeLists.txt#L84).

### SDL and compiler compatibility

SDL2 2.30.9 configured and built successfully against the installed Apple SDK. Its CMake targets supplied the necessary Mac frameworks, including Cocoa, CoreAudio, and Metal-related dependencies. No SDL3 migration or replacement renderer was necessary for the observed build and title-screen rendering.

The SDL build emitted warnings about deprecated Apple APIs and some compiler extensions. The full application build also emitted a duplicate-library linker warning. These were nonfatal on the tested toolchain; compatibility with other SDK and OS versions has not been established.

The recompiler emits Clang `musttail` calls. Those generated sources compiled successfully in the full Apple Silicon development build. This directly checks the current compiler path; it does not establish a minimum supported Apple Clang release. See [catrecomp.py:458](../tools/catrecomp.py#L458).

## Game file compatibility

The loader and generator accept one exact byte sequence, not any file named `CAT.EXE`. Both compare SHA-256 against:

```text
4979c8867826e08881d1d4bec95c95d6bc1ac70fd21050ccdb4f733a50d7bfdd
```

Two user-provided candidates were examined without modification:

| Candidate | Size | Result |
|---|---|---|
| First `ALLEYCAT.EXE` | 55,067 bytes | Rejected. SHA-256 was `a8538e4db809fbe01882be43e360e19ebc5571c92fbb98323078817ecc1c2956`. CMake reproduced the generator's hash-mismatch error. |
| Second `cat.exe` | 55,067 bytes | Exact match. Used for generation and runtime validation. |

Renaming the first file would not make it compatible. An explicit path accepts the second file's lowercase name; automatic discovery specifically constructs `CAT.EXE`, which can matter on a case-sensitive volume. See [game_file.c:55](../src/app/game_file.c#L55), [game_file.h](../src/app/game_file.h), and [catmap.py:37](../tools/catmap.py#L37).

The repository's distribution model requires players to supply their own game file and excludes generated game code and original assets from releases. This assessment preserved that model. Generated code, screenshots, and audio remain outside the repository; they are not included with this document. The repository's MIT license applies to its own code, as described in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Mac application gaps

### File selection is absent

[`pick_file()`](../src/app/main.c#L257) uses `GetOpenFileNameA` only under `_WIN32`. On every other platform it immediately returns `false`.

The consequence is definite: if no command-line path, usable INI setting, or automatically discovered `CAT.EXE` is available, the Mac build announces a file-selection window and then exits without opening one. This is the largest first-launch usability gap. A valid command-line path works, as the runtime probes demonstrated, but that path is not saved by the command-line branch of `find_game()`.

The native file-selection interface is a small host-facing boundary. Nothing in this behavior implies a need to rewrite the game or SDL rendering code. The exact interface choice remains undecided.

### Writable files share the application base directory

`main.c` uses `SDL_GetBasePath()` for `alleycat.ini`, screenshots, self-test images, and `alleycat_crash.log`. Under SDL2, a bundled Mac application normally receives its `Contents/Resources/` directory as that base path. Thus creating an `.app` without changing path policy would direct mutable files into its resources and look there for the game file. See [main.c:128](../src/app/main.c#L128), [main.c:226](../src/app/main.c#L226), and [SDL_GetBasePath](https://wiki.libsdl.org/SDL2/SDL_GetBasePath).

SDL already provides a per-user writable path API, `SDL_GetPrefPath()`, with Mac locations under Application Support. The storage requirement is clear even though the eventual screenshot and log destinations have not been selected. [SDL_GetPrefPath documentation](https://wiki.libsdl.org/SDL2/SDL_GetPrefPath).

Current failure reporting would obscure storage problems: `write_ini()` silently returns when opening fails; screenshots ignore the PNG writer's result; the fatal-error dialog says the log was saved even if its `fopen()` failed. This could make a packaged app appear to forget the selected game or lose diagnostic files.

The path buffers are fixed-size, and stored paths are plain text. Long paths, moved game files, and non-ASCII filenames were not exercised in the runtime tests.

### No Mac bundle or distribution artifact

The executable targets specify `WIN32`, which controls Windows entry-point behavior; it does not itself prohibit a Mac executable. CMake's separate `MACOSX_BUNDLE` facility supplies Finder application-bundle behavior. The repository has no bundle configuration, custom `Info.plist`, Mac application icon, or Mac install/release rules. [CMake WIN32_EXECUTABLE](https://cmake.org/cmake/help/latest/prop_tgt/WIN32_EXECUTABLE.html), [CMake MACOSX_BUNDLE](https://cmake.org/cmake/help/latest/prop_tgt/MACOSX_BUNDLE.html).

[`tools/make_release.py`](../tools/make_release.py) specifically expects `alleycat_release.exe`, copies it as `alleycat.exe`, and creates `AlleyCat-Windows.zip`. The included player guide and runtime notices describe Windows. These cannot produce a usable Mac release unchanged.

The script also performs a filtered 32-byte substring scan against the original executable before packaging. That is an existing artifact check, not a comprehensive proof of the provenance of every byte. Its current executable and archive assumptions are Windows-specific.

No signing or notarization process is present. For direct distribution with the normal Mac trust workflow, Apple documents Developer ID signing, hardened-runtime requirements, and notarization. Those are release-readiness concerns; they did not prevent a locally compiled executable from running. App Store distribution and sandboxing are outside the assessed scope. [Apple notarization documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

## Rendering audio and input

The front end already requests a resizable high-DPI window, obtains the renderer's pixel dimensions, and fits the game into a 4:3 rectangle. It renders the 320 by 200 CGA image through SDL textures and a 4x intermediate texture. The real window self-test produced a 2560 by 1920 image from the nominal 1280 by 960 window, consistent with a 2x display scale. The inspected image showed the expected title artwork and aspect ratio. This is useful Retina evidence for one host, not a check of mixed-density displays or full-screen transitions. See [main.c:108](../src/app/main.c#L108).

Renderer selection is delegated to SDL. There is no application-level requirement for DirectX or a particular Apple graphics backend. Texture-creation failures are not checked, and the renderer requests acceleration without an explicit application fallback. These are existing robustness limitations, not failures observed in the successful self-test.

Audio synthesis runs in the portable PC model and queues signed 16-bit mono samples at 44.1 kHz through SDL. The headless run wrote a WAV file, and the user subsequently confirmed seeing graphics and hearing sound during the graphical launch test. Audible output therefore worked on this Mac during that launch. Sustained playback, latency, Bluetooth output, and device switching remain untested. The graphical program can continue silently if `SDL_OpenAudioDevice()` fails, which remains an error-reporting limitation. See [pc.c:28](../src/pc/pc.c#L28) and [main.c:201](../src/app/main.c#L201).

Timing uses SDL's performance counter and an approximately 59.92 Hz software deadline. The game models a 4.77 MHz PC; host CPU speed is not directly used as gameplay speed. The pacing loop sleeps and then spins near the deadline. Battery cost, frame jitter, sleep/wake recovery, and high-refresh displays remain unmeasured.

Keyboard input uses SDL scancodes and maps Alt to the original game's action key. Mac-facing instructions would need to explain Option and the existing Control combinations. F11 and F12 availability depends on keyboard and system configuration; there is no explicit Command-based shortcut handling in application code. Manual key input and full-screen behavior remain untested.

Controller support is already based on SDL's game-controller API. The application handles device addition but has no removal case, and `pc.joy_present` is set only during startup. A controller connected later may therefore not be reflected in the emulated equipment state. These are source-level observations affecting both platforms; no physical Mac controller was tested. See [main.c:162](../src/app/main.c#L162) and [main.c:327](../src/app/main.c#L327).

## Architecture assumptions and validation limits

The CPU register union explicitly assumes little-endian byte order, which matches the tested Apple Silicon and Intel targets. Guest word reads and writes assemble bytes explicitly, avoiding a general dependence on unaligned host word access. Emulated registers and cycle counters predominantly use fixed-width integer types. See [v30.h:34](../src/cpu/v30.h#L34) and [v30.h:62](../src/cpu/v30.h#L62).

The WAV writer copies native integers and samples directly into a little-endian format. This is compatible with these Mac targets but would not be portable unchanged to a big-endian platform. There is no evidence here for supporting historic PowerPC Macs or classic Mac OS.

The headless release run used a fixed clock base and seed. Its video-memory hashes at frames 1,000 through 6,000 were `e594e876`, `6ab7983c`, `a8cd91e7`, `d3d5664c`, `259e94eb`, and `04d420cc` on both architectures. This establishes agreement for the exercised paths, not exhaustive equivalence or bit-identical audio.

The development runner completed `tools/check.py --all-rooms` with exit status zero: 40,937,961 calls checked and zero mismatches across 41 jobs. Of the 260 routine rows, 63 had direct comparisons and 184 were exercised only within compared callers. The default settings use eight general seeds, four seeds for each of seven rooms, four joystick runs, and a quit-key run, each limited to 6,000 frames unless the game exits sooner.

The summary reported 13 routines with no counted calls: `0000`, `10DD`, `1166`, `1799`, `1D6E`, `2706`, `3BA3`, `56F4`, `5704`, `597F`, `5A1C`, `5A90`, and `5C9E`. `0000` has an explicit special case that bypasses comparison, so its counter does not mean the main loop never executed. The remaining gaps prevent claiming complete routine coverage from this run.

The repository has a valuable generated-versus-handwritten comparison harness covering registers, memory, recorded I/O, and interrupts. Its evidence needs careful interpretation:

- `docs/REWRITE.md` excludes the nonreturning main/room loops from direct routine comparison and describes PCjr handlers as outside the supported machine model.
- `tools/check.py` defaults to a Windows `.exe` path, but `--exe` accepts the Mac runner path. Its subprocess return code is not directly checked; it relies on parsed mismatches, stderr, and a completion marker.
- A `CAT_RELEASE` runner has a stub `cat_hand_report()` returning zero. Passing that runner to the comparison script would not compare against generated code. This audit uses the development `cat_test` target for that purpose.
- `tools/hand_coverage.py` hardcodes `cat_test.exe`, the Ninja generator, and bare LLVM coverage-tool commands. No CI workflow or CTest registration is tracked in the repository.

The source and observed builds support native Apple Silicon execution and compilation for Intel. A universal application, physical Intel graphics/audio, older macOS versions, a clean Mac without developer tools, Finder launch, signed distribution, manual play, and controller behavior have not been validated. CMake can select Mac architectures through `CMAKE_OSX_ARCHITECTURES`; the repository currently leaves both architecture selection and deployment target at toolchain defaults. [CMake architecture documentation](https://cmake.org/cmake/help/latest/variable/CMAKE_OSX_ARCHITECTURES.html).

## Feasibility judgment

| Area | Assessment | Basis |
|---|---|---|
| Native game and hardware-model execution | High feasibility | ARM build and scripted execution succeeded; Intel translated execution agreed on sampled state. |
| Existing SDL2 front end | High feasibility | Exact pinned SDL built, linked statically, and rendered a real Mac window. |
| Building an unchanged checkout | Currently blocked on this toolchain | Missing standard header; Python minimum mismatch. |
| Normal first launch from Finder | Incomplete | No Mac picker or application bundle; existing fallback exits. |
| Settings screenshots and logs in a packaged app | Incomplete | Application resource path is used for mutable files, with weak error reporting. |
| Public Mac distribution | Incomplete | Windows-only packaging and no Mac signing/notarization workflow. |
| Broad compatibility claims | Not established | One Apple Silicon host, limited graphical testing, no chosen deployment baseline. |

The evidence supports a bounded platform adaptation centered on build correctness and the application shell. It does not indicate a need to rewrite the game, replace SDL, remove the guest CPU model, or translate an x86 executable at runtime for Apple Silicon. The amount of release work depends on the eventual supported OS/architecture range and distribution expectations, which remain open for later agreement.

## Reproduction details

Audit artifacts are local and temporary under `/private/tmp/alleycat-macos-audit.9Z7cQH`. They include generated code and game-derived media and are intentionally excluded from the documentation change. The original game files were only read.

The complete repository build used the following command shape, with the accepted game path and verified extracted SDL source supplied locally:

```sh
cmake -S . -B "$AUDIT_DIR/full-build" \
  -DPython3_EXECUTABLE=/opt/homebrew/bin/python3.14 \
  -DCAT_EXE="$GAME_FILE" \
  '-DCMAKE_C_FLAGS=-include stddef.h' \
  -DFETCHCONTENT_SOURCE_DIR_SDL2="$AUDIT_DIR/SDL2-2.30.9"
cmake --build "$AUDIT_DIR/full-build" --parallel 6
```

`AUDIT_DIR` denotes the temporary directory above and `GAME_FILE` the accepted original executable. The dependency override supplies the exact pinned source locally; it does not replace the SDL version.

The gameplay and comparison commands were:

```sh
"$AUDIT_DIR/cat_test_release_arm64" "$GAME_FILE" \
  --frames 6000 --autoplay 1 --rooms --status 1000 \
  --wav "$AUDIT_DIR/release-audio.wav" \
  --shot "300:$AUDIT_DIR/release-frame300.png"

"$AUDIT_DIR/cat_test_release_x86_64" "$GAME_FILE" \
  --frames 6000 --autoplay 1 --rooms --status 1000

"$AUDIT_DIR/pinned-build/alleycat_pinned" "$GAME_FILE" --selftest 120

/opt/homebrew/bin/python3.14 tools/check.py "$GAME_FILE" \
  --all-rooms --exe "$AUDIT_DIR/full-build/cat_test"
```

`alleycat_pinned` is an isolated diagnostic target built from the repository's release sources, its generated 260-entry table, and static SDL2 2.30.9. The full repository build was verified separately. The direct headless compilation used Apple Clang, C11, `-O2`, `-DCAT_RELEASE`, the header override, and the same release sources; the Intel build additionally used `-arch x86_64`.
