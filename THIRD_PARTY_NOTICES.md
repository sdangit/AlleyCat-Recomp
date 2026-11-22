# Third-party notices

## This project

All code in this repository is © 2026 Syncr0ndi and released under the [MIT licence](LICENSE).
Every source file carries an `SPDX-License-Identifier: MIT` header. That includes:
- the CPU core (`src/cpu/`) and the decoder and recompiler tools, adapted from the author's own
  [LOHT-Recomp](https://github.com/Syncr0ndi/LOHT-Recomp) (MIT);
- the 8×8 font in `src/pc/font8x8.c`, drawn for this project. It's not a copy of the IBM ROM font.

## The game

*Alley Cat* &copy; 1983–84 Bill Williams / SynSoft, published by IBM. **No part of the game is in this
repository or in the release download:** no program code, graphics, sound or data. Players provide
their own `CAT.EXE`, which the program reads at start-up. Reference-enabled development builds recompile the game's code
into the build folder only; that output is never committed. Release-only builds skip this step. The MIT licence covers only this
project's own code, not the game.

This is an unofficial, non-commercial fan project, not affiliated with or endorsed by the
copyright holders. Product names are used only to identify the game this project works with.

## Libraries used by the release

| Component | Use | Licence | How it's included |
|---|---|---|---|
| [SDL2](https://www.libsdl.org/) 2.30.9 | Window, input, audio | zlib | Downloaded by CMake at build time and linked statically. Licence text shipped as `LICENSES/SDL2-LICENSE.txt` in the release. |
| LLVM-MinGW runtime (mingw-w64 CRT, compiler-rt) | C runtime startup code | mingw-w64: ZPL / public domain; compiler-rt: Apache-2.0 WITH LLVM-exception | Linked by the toolchain. Neither requires a notice in binary form. |

The Windows release uses the Windows Universal C Runtime (part of Windows 10/11) and the standard
Windows system libraries, so no other DLLs are shipped. The macOS release links SDL2 statically
and uses Apple system frameworks for its window, file picker, input, and audio. It does not include
the LLVM-MinGW runtime; Apple system frameworks are supplied by macOS rather than bundled.
