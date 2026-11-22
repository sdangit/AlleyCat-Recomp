# Mac application icon

`AlleyCat.svg` reuses the cat shape and eyes from this repository's `docs/images/logo.svg`,
placing them on a square background. It contains no artwork extracted from CAT.EXE.
It follows the project's MIT license.

`AlleyCat.icns` contains 16, 32, 128, 256, and 512 point images at 1x and 2x. Regenerate
those PNGs from the SVG with `rsvg-convert`, name them according to Apple's `.iconset`
convention, and assemble with `iconutil -c icns`. The checked-in ICNS means building
and packaging do not require the SVG converter.
