"""Generates deterministic synthetic Meowdoku-style board images with known
ground truth, used by tests/test_recognition.py. These are clearly-labeled
SYNTHETIC verification images, not real Meowdoku screenshots (see README for
the distinction) -- they exist so the recognition pipeline (grid detection,
region-color clustering, foreground detection) can be exercised end-to-end
and checked against a known-correct answer even without a real screenshot
available in the workspace.

Run with: python3 scripts/gen_recognition_fixtures.py
Writes PNGs and *.ground_truth.json files into tests/fixtures/.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# BGR colors (perceptually distinct), deliberately not matching any real
# game's palette -- recognition must not depend on a hardcoded palette.
PALETTE_BGR = [
    (60, 60, 220), (80, 200, 90), (30, 210, 230), (200, 120, 30),
    (180, 60, 190), (40, 180, 180), (150, 150, 240), (90, 90, 90),
    (60, 130, 220), (200, 200, 60),
]


def _region_color_map(region_ids):
    distinct = sorted(set(v for row in region_ids for v in row))
    return {rid: PALETTE_BGR[i % len(PALETTE_BGR)] for i, rid in enumerate(distinct)}


def render_board(
    region_ids,
    cell_states,
    cell_px: int,
    pad_left: int = 0,
    pad_top: int = 0,
    pad_right: int = 0,
    pad_bottom: int = 0,
    noise_std: float = 0.0,
    seed: int = 0,
    border_px: int = 2,
):
    """cell_states: dict {(r, c): "cat" | "x"}. Returns a BGR uint8 image."""
    size = len(region_ids)
    board_w = board_h = size * cell_px
    total_w = board_w + pad_left + pad_right
    total_h = board_h + pad_top + pad_bottom

    img = np.full((total_h, total_w, 3), (35, 35, 35), dtype=np.uint8)
    region_color = _region_color_map(region_ids)

    for r in range(size):
        for c in range(size):
            x0, y0 = pad_left + c * cell_px, pad_top + r * cell_px
            x1, y1 = x0 + cell_px, y0 + cell_px
            cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), region_color[region_ids[r][c]], thickness=-1)

    for i in range(size + 1):
        x = pad_left + i * cell_px
        y = pad_top + i * cell_px
        cv2.line(img, (x, pad_top), (x, pad_top + board_h), (15, 15, 15), border_px)
        cv2.line(img, (pad_left, y), (pad_left + board_w, y), (15, 15, 15), border_px)

    for (r, c), kind in cell_states.items():
        cx = pad_left + c * cell_px + cell_px // 2
        cy = pad_top + r * cell_px + cell_px // 2
        if kind == "cat":
            radius = max(4, int(cell_px * 0.30))
            cv2.circle(img, (cx, cy), radius, (25, 25, 25), -1)
            eye_r = max(1, int(cell_px * 0.05))
            cv2.circle(img, (cx - radius // 2, cy - radius // 3), eye_r, (235, 235, 235), -1)
            cv2.circle(img, (cx + radius // 2, cy - radius // 3), eye_r, (235, 235, 235), -1)
        elif kind == "x":
            d = max(3, int(cell_px * 0.22))
            thickness = max(2, cell_px // 12)
            cv2.line(img, (cx - d, cy - d), (cx + d, cy + d), (50, 50, 60), thickness)
            cv2.line(img, (cx - d, cy + d), (cx + d, cy - d), (50, 50, 60), thickness)

    if noise_std > 0:
        rng = np.random.RandomState(seed)
        noise = rng.normal(0, noise_std, img.shape)
        img = np.clip(img.astype(np.float64) + noise, 0, 255).astype(np.uint8)

    return img


FIXTURES = []


def _fixture(name, region_ids, cell_states, **kwargs):
    FIXTURES.append({"name": name, "region_ids": region_ids, "cell_states": cell_states, "kwargs": kwargs})


# 1. Basic 5x5, non-trivial (non-diagonal) region shapes, clean, medium cells.
_fixture(
    "basic_5x5",
    region_ids=[
        [0, 0, 1, 1, 1],
        [0, 0, 1, 2, 2],
        [3, 0, 1, 2, 2],
        [3, 3, 4, 4, 2],
        [3, 3, 4, 4, 4],
    ],
    cell_states={(0, 0): "cat", (2, 3): "x"},
    cell_px=50,
)

# 2. Noisy 6x6 with small cells and Gaussian pixel noise.
_fixture(
    "noisy_6x6",
    region_ids=[
        [0, 0, 0, 1, 1, 1],
        [2, 2, 0, 1, 3, 3],
        [2, 2, 0, 1, 3, 3],
        [2, 4, 4, 1, 3, 5],
        [4, 4, 4, 5, 5, 5],
        [4, 4, 5, 5, 5, 5],
    ],
    cell_states={(1, 1): "cat", (3, 3): "cat", (0, 4): "x"},
    cell_px=34,
    noise_std=7.0,
    seed=42,
)

# 3. Large cells, 4x4, to check robustness to cell-size variation.
_fixture(
    "large_cells_4x4",
    region_ids=[
        [0, 0, 1, 1],
        [0, 2, 2, 1],
        [3, 2, 2, 1],
        [3, 3, 3, 1],
    ],
    cell_states={(0, 3): "cat", (2, 0): "x"},
    cell_px=90,
)

# 4. Asymmetric crop offset/padding, 7x7, moderate noise -- simulates a
# sloppy manual screen-area selection that includes surrounding UI margin.
_fixture(
    "offset_crop_7x7",
    region_ids=[
        [0, 0, 0, 1, 1, 2, 2],
        [0, 0, 3, 1, 1, 2, 2],
        [3, 3, 3, 3, 4, 4, 2],
        [3, 5, 5, 4, 4, 4, 6],
        [5, 5, 5, 4, 6, 6, 6],
        [5, 5, 6, 6, 6, 6, 6],
        [5, 6, 6, 6, 6, 6, 6],
    ],
    cell_states={(0, 0): "cat", (4, 4): "cat", (6, 6): "x"},
    cell_px=40,
    pad_left=23,
    pad_top=11,
    pad_right=9,
    pad_bottom=17,
    noise_std=4.0,
    seed=7,
)


def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for fixture in FIXTURES:
        img = render_board(fixture["region_ids"], fixture["cell_states"], **fixture["kwargs"])
        png_path = FIXTURES_DIR / f"{fixture['name']}.png"
        cv2.imwrite(str(png_path), img)

        ground_truth = {
            "size": len(fixture["region_ids"]),
            "region_ids": fixture["region_ids"],
            "cell_states": {f"{r},{c}": kind for (r, c), kind in fixture["cell_states"].items()},
            "cell_px": fixture["kwargs"].get("cell_px"),
            "pad_left": fixture["kwargs"].get("pad_left", 0),
            "pad_top": fixture["kwargs"].get("pad_top", 0),
        }
        gt_path = FIXTURES_DIR / f"{fixture['name']}.ground_truth.json"
        with open(gt_path, "w") as f:
            json.dump(ground_truth, f, indent=2)
        print(f"Wrote {png_path} and {gt_path}")


if __name__ == "__main__":
    main()
