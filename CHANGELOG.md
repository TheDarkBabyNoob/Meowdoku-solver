# Changelog

The version shown in the app's title bar (**Meowdoku Companion vX.Y.Z**)
matches a heading below — if the newest heading here has a version higher
than what your title bar shows, `git pull` (or rebuild the `.app`) to update.

## 0.2.0

- Fixed the area-selection overlay showing a black screen with no apps
  visible. `showFullScreen()` was pushing the overlay onto its own macOS
  Space, hiding every other window (including iPhone Mirroring) behind it;
  it now stays on the current Space so real windows show through.
- Added drag-and-drop: dropping an image file onto the window imports and
  scans it, the same as the **Import Screenshot** button.

## 0.1.0

- Initial release: screen-area selection, mss-based capture, board
  recognition (grid/region/foreground detection), backtracking solver, and
  the board editor, wired together around a `BoardSession`.
