ALLEY CAT for macOS
==================

Open AlleyCat.app and choose your own original 1984 IBM CAT.EXE (55,067 bytes).
The filename may be lowercase or different; the contents must match the known
original. The game file is not included, copied into the app, or modified.
If the selected file moves, the application asks you to select it again.

This initial Mac build is for Apple Silicon. Its compilation deployment target
is macOS 11.0; see the source validation report for the OS versions actually
exercised. It does not claim testing on every version since macOS 11.

SETTINGS AND OUTPUT
Settings use SDL's per-user application directory, normally:
  ~/Library/Application Support/AlleyCat/
Screenshots are in its screenshots/ folder; diagnostic reports are in logs/.
The application does not need to write inside its .app bundle.

CONTROLS
  Arrow keys           Move / climb / jump
  Option               Special action (the original game's Alt key)
  Esc                  Pause
  Control-S            Sound on / off
  Control-R            Restart
  Control-M            Back to the menu
  Option-Return / F11   Fullscreen
  F12                  Screenshot (Fn may be required on some keyboards)
  Window close         Quit
The SDL game-controller mapping is retained; physical-controller compatibility
is limited to the devices actually tested, as recorded in source documentation.

SIGNING
The archive's external manifest states its signing and notarization status.
An ad-hoc signature is for local validation and does not identify a Developer ID
publisher. An archive marked NOT_RUN for notarization is not notarized. The
packaging tool never submits software to Apple automatically.

CREDITS AND LICENSES
Alley Cat (c) 1983-84 Bill Williams / SynSoft, published by IBM. This is an
unofficial fan project. Players supply the original game and its assets.
This project's code is MIT licensed; see LICENSES/AlleyCat-port-LICENSE.txt.
SDL2 2.30.9 is statically linked; see LICENSES/SDL2-LICENSE.txt.
Apple system frameworks are provided by macOS, not included in this archive.
The application icon uses the repository's own logo artwork, not game assets.

Original project: https://github.com/Syncr0ndi/AlleyCat-Recomp
Mac branch: https://github.com/sdangit/AlleyCat-Recomp/tree/macos
