# Meowdoku Companion

A local, offline screen-scan-and-solve companion for **Oakever's Meowdoku**,
played on a Mac via **iPhone Mirroring**. Select the screen rectangle
containing the mirrored puzzle, click **Scan & Solve**, and the app
recreates the board and shows you where the cats go. Everything — capture,
image recognition, and the constraint solver — runs locally. There are no
API keys, accounts, hosted services, LLM calls, downloaded AI models, or
runtime internet access.

## Game rules this app implements

Per Oakever's official App Store listing: each colored region needs exactly
one cat; cats cannot share a row or column; cats cannot touch, **including
diagonally, but only at immediate distance-1** (a chess-queen-style "whole
diagonal" rule is deliberately *not* implemented — two cats two rows apart
on the same diagonal are legal).

For a validated N-by-N board with exactly N regions, those constraints
force exactly one cat per row and per column, which is the model the
solver implements. Boards that aren't square, or don't have exactly N
regions, are reported as **unsupported** rather than silently solved under
the wrong model.

## Exact launch command

```
./launch.command
```

Double-click `launch.command` in Finder, or run it from Terminal. First run
creates a local virtual environment and installs dependencies (needs
internet once); every later launch is fully offline. See **Setup** below
for details, and **Packaging** for an alternative double-clickable `.app`.

## Tested environment / versions

Developed and verified on:

- **Apple Silicon Mac** (M1, `arm64`), **macOS 26.6**
- **Python 3.14.2** (satisfies the `>=3.11` requirement; see note below)
- `PySide6==6.11.2`
- `opencv-python-headless==5.0.0.93`
- `numpy==2.5.3`
- `mss==10.2.0`
- `pytest==9.1.1` (dev/test only)

These are pinned in `requirements.txt` and are the exact versions installed
and exercised during development, confirmed to install and import cleanly
together (only one OpenCV distribution is installed — the headless build —
so it never conflicts with a GUI build of OpenCV).

**Why Python 3.14 instead of 3.11/3.12:** this machine's only available
`python3` is the python.org 3.14 install; no 3.11/3.12/3.13 interpreter was
present and this project does not install a different Python version for
you (per the "no sudo, don't touch the system Python" constraint). 3.14
satisfies the stated `>=3.11` requirement and every dependency above
publishes a compatible wheel for it on this platform, verified directly
before writing any code. If you have Python 3.11–3.13 on your `PATH`
instead, `launch.command` will use whichever `python3` it finds, as long as
it's 3.11+.

## Why mss for capture

`mss` wraps macOS CoreGraphics screenshot APIs, requires only the
**Screen Recording** permission (not Accessibility), and needs no compiled
extension beyond its bundled `ctypes` bindings. It was verified directly in
this environment (Apple Silicon, macOS 26.6) to return real, non-blank
pixel data. Capture sits behind a small `CaptureBackend` interface
(`meowdoku/capture/base.py`); if a future macOS release breaks mss's
CoreGraphics calls, a ScreenCaptureKit-based backend can be written against
the same interface without touching the rest of the app.

## Setup

1. Make sure you have Python 3.11+ (check with `python3 --version`; if
   missing, install from [python.org](https://www.python.org/downloads/macos/)
   or `brew install python@3.12`).
2. Double-click `launch.command` in Finder (or run `./launch.command` from
   Terminal). It will:
   - Resolve its own directory (works even though this folder's name has a
     space in it).
   - Create a project-local virtual environment at `.venv` (never touches
     your system Python, never uses `sudo`).
   - Install the pinned dependencies from `requirements.txt` — **only** the
     first time, or after `requirements.txt` changes (checked via a sha256
     stamp file, so normal relaunches need no network access).
   - Launch the app.
3. Grant **Screen Recording** permission when macOS asks (see below).

## Permissions

**Screen Recording** (required for capture): System Settings → Privacy &
Security → Screen Recording. Grant it to:
- **Terminal** (or iTerm2, whichever you launched `launch.command` from) —
  if running from source.
- **Meowdoku Companion** itself — if running the packaged `.app` (see
  Packaging below). macOS grants this permission per launching-process
  identity, so the source and packaged paths need it granted separately.

This app **never** requests Accessibility access. It only reads pixels; it
never simulates clicks, key presses, or mouse movement, and there is no
background/continuous screen monitoring — a capture only happens when you
click **Scan & Solve** or **Import Screenshot**.

## Using it with iPhone Mirroring

1. Open the Meowdoku puzzle on your iPhone, viewed on your Mac through
   Apple's iPhone Mirroring.
2. Click **Select Screen Area**, then drag a rectangle around the puzzle
   board (on any attached monitor). Escape cancels. The selection and which
   monitor it's on are remembered between scans *and* app launches.
   - A selection is restricted to the single monitor you started dragging
     on; if your drag crosses into another display it's clamped back, with
     a message telling you so.
   - If your display arrangement changes after selecting (e.g. you unplug
     a monitor), the app detects the mismatch and asks you to
     **Reselect Area** rather than silently capturing the wrong region.
3. Click **Scan & Solve**. The app hides its own window, waits briefly for
   the compositor to update, captures just that rectangle, then restores
   itself — so it never accidentally recognizes its own UI as the board.
4. Inspect the recreated board next to the captured crop. If recognition
   flagged anything for review (ambiguous region colors, low-confidence
   cat/X detections, a region-count mismatch, a non-square crop, low grid
   confidence), the status will read **Needs Review** — fix flagged cells
   in **Edit Board** before trusting the result.
5. Once confident, the solver runs automatically and the status shows one
   of: **Unique Solution**, **Multiple Solutions**, **No Solution**,
   **Solution Found, Uniqueness Unverified** (timed out with one solution),
   or **Search Incomplete** (timed out with none). A multiple-solutions
   result is explicitly labeled as *one possible* arrangement, not
   necessarily the game's intended one.
6. Use **Show All Cats** / **Next Cat** to see recommended placements, and
   the copyable `R1 C4`-style list to place them yourself in iPhone
   Mirroring. **Next Cat** only advances the on-screen guidance — it never
   claims you placed anything in the real game. **Next Hint** proves one
   placement is logically guaranteed (by showing that excluding it makes
   the board unsolvable) and gives a short, honest explanation — never a
   fabricated human deduction trace.
7. When you're ready for the next board, click **Scan & Solve** again — no
   restart or reselect needed for an unchanged screen area. Each new scan
   (or edit) immediately invalidates the previous solution via a
   monotonically increasing board revision; a slow background worker for a
   superseded board can never overwrite what you're looking at (see
   `meowdoku/session.py`, and `tests/test_session.py` /
   `tests/test_gui_integration.py` for the tests that prove this,
   including a real race between two actual `QThread` workers). By design,
   manual edits/hints from one board are **not** carried over to the next
   scan — same-board matching across rescans (region-label normalization +
   geometry checks) was judged out of scope for this version; every new
   scan starts clean.

## Correcting recognition (Edit Board)

Click **Edit Board** to reveal the editor panel:
- **Set cat/X/blocked** (click to cycle; right-click cycles the other way) —
  corrects a cell's state. An uncertain cat detection resolves via a single
  left-click (confirm) or right-click (reject to empty).
- **Paint region** — pick a region from the palette (or **+ New Region**)
  and click cells to reassign them.
- **Merge regions** — click two cells; the first cell's region merges into
  the second's.
- **Mark placed** — click a cell currently showing a green recommendation
  ring to mark it as a confirmed cat in *this app's* local bookkeeping
  only; it never touches the real game.
- **Undo**, **Change Grid Size...**, **Manual Empty Board...** (a fully
  manual entry route if automatic recognition fails entirely), **Calibrate
  Cat/X Template...** (teach the app your game's exact cat/X art from a
  cell you identify — stored locally under `~/Library/Application
  Support/MeowdokuCompanion/calibration/`), and **Export Debug Bundle...**
  (writes the captured crop, a detected-grid overlay, and the board JSON to
  a folder you choose, for reproducing a failed recognition case).

Any edit re-solves automatically — you never need another screenshot after
a correction.

## Recognition pipeline (how it works)

1. **Grid detection** (`meowdoku/recognition/grid_detect.py`): projects
   Canny edge energy onto both axes, estimates cell spacing from the actual
   gaps between strong edge peaks (not a hardcoded size), refines against
   neighboring sizes to fix off-by-one errors, then locates the board's
   real bounding box within the crop (so a sloppy selection with extra
   margin around the board doesn't misalign every cell). Supports sizes
   2–20; a board-size override and draggable crop adjustment are always
   available if auto-detection gets it wrong.
2. **Region reconstruction** (`region_detect.py`): samples several inset
   background patches per cell (avoiding grid lines and the center, where
   cat art/X marks live), takes a median-of-medians as a robust per-cell
   background estimate, converts to Lab, and clusters cells by perceptual
   color distance. The cluster count is reported honestly — if it doesn't
   match the board's region count, this is surfaced as **Needs Review**,
   never silently forced to fit. Ambiguous cells (near-equidistant between
   two clusters) are resolved using neighbor/boundary evidence where
   possible and always flagged for review either way.
3. **Foreground detection** (`foreground.py`): compares each cell's center
   against its own estimated background to find a foreground mask, then
   classifies cat vs. X by **contour solidity** (mask area ÷ convex-hull
   area) — a filled cat blob is close to its own hull (~1.0), while a thin
   crossing X mark covers much less of its hull (~0.35–0.56, measured
   directly against `tests/fixtures/*.png`; an earlier bounding-box
   fill-ratio heuristic was found to overlap between the two classes and
   was replaced). Low-confidence detections become `CAT_UNCERTAIN` — shown
   distinctly and requiring your confirmation, never silently treated as a
   hard constraint or as empty. Optional per-user calibration templates
   (see above) boost confidence via template matching.
4. Existing confirmed cats become required solver placements; X marks are
   treated as player notes and **ignored** by the solver by default (an
   explicit **Respect X Marks** checkbox opts into treating them as hard
   exclusions); a separate **Blocked** cell state is always a hard
   exclusion regardless of that setting.

Recognition confidence is a heuristic score, never presented as a
calibrated probability, and is kept entirely separate from solver
certainty — a unique solver answer does not prove the screenshot was read
correctly, and the app never modifies the perceived region map just to
force a unique solution.

## The solver

Pure Python, zero GUI/capture/OpenCV imports (`meowdoku/solver.py`), so it's
independently testable and reusable. For the validated N×N/N-region model:

- One variable per row (its chosen column), domains as integer bitmasks.
- Deterministic backtracking with **minimum-remaining-values** variable
  selection and **forward checking** (a row's live domain is recomputed
  against every currently-assigned row, checking **both** neighbor rows —
  not just "the previous recursion level" — for the adjacent-diagonal
  rule).
- Confirmed cats are required assignments; blocked cells and (if opted in)
  X marks are forbidden assignments; contradictions are caught before
  search starts.
- Searches for up to **two** distinct solutions to distinguish
  **Unique Solution** from **Multiple Solutions** (two solutions prove
  multiplicity, not the total count); reports **No Solution** only after
  exhaustive failure.
- Configurable time budget and cooperative cancellation
  (`threading.Event`), run off the GUI thread via `QThread` workers that
  deliver immutable results through Qt signals. A timeout with exactly one
  solution found is reported as **Solution Found, Uniqueness Unverified**
  (never as Unique); a timeout with none is **Search Incomplete**. Calling
  the solver with `max_solutions=1` is *also* never reported as unique —
  it deliberately never looked for a second solution, so uniqueness was
  never checked (a real gap this project caught and fixed during test
  development; see `test_capped_single_solution_search_is_uniqueness_unverified_not_unique`
  in `tests/test_solver.py`).
- Every complete arrangement is independently re-validated against the raw
  puzzle model before being returned (`independent_validate`), as a safety
  net separate from the search's own bookkeeping.
- **Guaranteed hints**: a cell is proven required by re-solving with that
  cell forbidden and showing the result is exhaustively unsatisfiable (or
  by exhaustive enumeration) — this holds even when the board isn't known
  to be fully unique. A timed-out proof attempt never produces a hint.

## Project layout

```
meowdoku/
  models.py            data classes: Board, CellState, GridGeometry, ...
  solver.py             pure-Python constraint solver
  coords.py              Qt-logical / monitor / capture-pixel transforms
  session.py             revision-based staleness guard
  persistence.py          local settings, saved selection, calibration
  capture/
    base.py                CaptureBackend interface
    mss_backend.py           mss-based implementation + permission text
  recognition/
    grid_detect.py           board-bounds + size detection
    region_detect.py          region-color reconstruction/clustering
    foreground.py              cat/X detection + calibration
    pipeline.py                 orchestrates the above into RecognitionResult
  gui/
    main_window.py             wires everything together
    board_view.py               the recreated-board widget
    overlay_select.py            drag-to-select screen overlay
    workers.py                    QThread workers for scan/solve/hint
    palette.py                     region color palette
  app.py                entry point
tests/                 pytest suite (67 tests; see below)
scripts/
  gen_recognition_fixtures.py   generates tests/fixtures/*.png + ground truth
packaging/
  make_icon.py            draws the app icon from scratch (no external art)
  build_app.sh              builds a double-clickable .app via PyInstaller
launch.command          the primary, reliable source launcher
requirements.txt / pyproject.toml   dependency metadata
```

## Packaging (optional `.app` build)

After the source launcher works, `packaging/build_app.sh` builds a
double-clickable **Meowdoku Companion.app** (via PyInstaller) and places it
at the project root, next to `launch.command`, with an original,
programmatically-drawn icon (`packaging/make_icon.py` — a cat silhouette
over a puzzle-grid motif; no downloaded or copied artwork). Run it with:

```
./packaging/build_app.sh
```

This never delays or replaces the source launcher — `launch.command` is
always the reliable fallback. Notes:

- **Unsigned/non-notarized**: no paid Apple Developer account was used or
  is required. On first launch, Gatekeeper will warn that the developer
  can't be verified — right-click (Control-click) the app, choose **Open**,
  confirm once; this is only needed the first time.
- **Screen Recording permission is separate from the source launcher's**:
  grant it to **Meowdoku Companion** specifically (System Settings →
  Privacy & Security → Screen Recording), since macOS grants this
  permission per launching-process identity, not per Python script.

## Tests

```
source .venv/bin/activate  # or: .venv/bin/python3 -m pytest
python3 -m pytest tests/ -v
```

**67 tests, all passing** on this machine (Apple Silicon M1, macOS 26.6,
Python 3.14.2), covering:

- **Solver correctness** (`test_solver.py`, 38 tests): the exact fixtures
  from the spec — a 4×4 diagonal-region board has exactly two solutions
  `[1,3,0,2]` and `[2,0,3,1]`, fixing a cat at (row 0, col 1) leaves only
  the first; a 5×5 board's `[1,3,0,4,2]` is valid and is *not* rejected by
  a chess-queen check. Also: non-square/region-count-mismatch/multiple-
  fixed-cats-per-row reported as unsupported; X marks ignored by default
  but excludable via an opt-in; blocked cells always hard exclusions;
  impossible boards reported as No Solution; deterministic zero-budget
  timeout behavior; the `max_solutions=1` uniqueness-labeling fix above;
  cancellation via a pre-set `threading.Event`; guaranteed hints checked
  against full brute-force solution sets on small ambiguous fixtures; and
  **68 randomized small boards (3×3–6×6, parametrized) cross-checked
  against an independent brute-force reference solver**
  (`tests/bruteforce_reference.py`, sharing no code with the real solver).
- **Coordinate transforms** (`test_coords.py`, 7 tests): scale derived from
  actual returned pixel dimensions for 1×, 1.5×, and 2× (never assuming
  2.0), negative monitor origins, full-frame-crop math, drag-direction
  normalization, and monitor-spanning detection.
- **Recognition pipeline** (`test_recognition.py`, 17 tests, parametrized
  over 4 synthetic fixtures with varied region shapes, cell sizes 34–90px,
  Gaussian pixel noise, grid borders, and an asymmetric crop offset):
  board-size detection, region-partition equivalence *independent of
  arbitrary region-label numbering*, exact cat/X placement, and clean
  failure classification for blank/tiny/featureless captures plus honest
  region-count-mismatch review flagging (not silent forcing).
- **Staleness guarantees** (`test_session.py`, 4 tests + `test_gui_integration.py`,
  1 test): a rescan or edit invalidates an in-flight worker's result even
  if it returns later; the GUI-integration test runs two **real**
  `QThread` scan workers with an artificially slowed first call so the
  second (current) scan genuinely finishes first, and asserts the stale
  4×4 result never overwrites the current 5×5 board. Building this test
  also surfaced and fixed a real bug in `main_window.py`, where a
  superseded worker's only Python reference was being dropped while its
  `QThread` could still be running.

### Synthetic vs. real-game verification

**No real Meowdoku screenshot was available in this workspace or provided**,
so recognition is verified against `tests/fixtures/*.png` — clearly
synthetic images with known ground truth, generated by
`scripts/gen_recognition_fixtures.py` (not real game screenshots, and not
claimed to be). The **Import Screenshot** button uses the exact same
recognition pipeline as live capture, so it's the way to validate against
a real screenshot yourself: take one during actual iPhone Mirroring play,
import it, and correct anything the editor flags.

### What was and wasn't verified on this machine

This session ran on a real Apple Silicon Mac (macOS 26.6) with Screen
Recording permission already available to this process, so the following
were verified directly, for real: `mss` capturing genuine non-blank screen
pixels; the full `launch.command` first-run flow (venv creation, dependency
install, launch) and the offline-capable second-launch flow (dependency
install skipped, confirmed via the sha256 stamp file); the `MainWindow`
constructing and running under Qt's offscreen platform; and the packaged
`.app` build via `packaging/build_app.sh`.

**Not verified**, and not claimed: an actual capture-and-solve run against
a real, visible iPhone Mirroring window showing a live Meowdoku board —
this automated session had no such window on screen to capture. The
recognition pipeline's accuracy against the real game's actual color
palette, exact cat/X sprite art, and any chrome/dialogs around the board is
therefore unverified beyond the synthetic fixtures above; use **Import
Screenshot** with a real capture and the editor's review/correction tools
to close that gap yourself. Similarly, no visual/interactive click-through
of the GUI was possible from this non-interactive session (verified
instead via headless Qt construction and the QThread integration test) —
please do a first real click-through yourself and use **Edit Board** to
correct anything recognition gets wrong.

## Known limitations

- Region clustering uses single-linkage (threshold-based) clustering,
  which can in principle chain together a gradient of similar colors; the
  editor's merge/paint tools are the correction path if this ever happens
  on a real board.
- The cat/X shape classifier is a solidity-based heuristic, not a trained
  model; per-user calibration templates help but recognition can still get
  a cell wrong — always check **Needs Review** before trusting a scan.
- Manual edits, hints, and confirmations are **not** carried across a
  rescan by design (see above); every new scan starts clean.
- The packaged `.app` is unsigned/non-notarized (see Packaging).
- No telemetry, accounts, or cloud services of any kind; the only network
  access this project ever needs is the one-time dependency install.
