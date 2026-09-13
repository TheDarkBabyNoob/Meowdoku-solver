"""Foreground (cat sprite / X mark) detection, kept separate from region
color classification. Detection is conservative: anything not clearly one
kind or the other is reported at low confidence rather than guessed, so the
caller can surface it as CAT_UNCERTAIN for the user to confirm or correct
instead of silently becoming a hard constraint or an empty cell.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from meowdoku.models import CalibrationTemplate

FOREGROUND_DIFF_THRESHOLD = 32.0
FOREGROUND_MIN_RATIO = 0.05
# Shape discriminator: a filled cat blob's foreground mask is close to its
# own convex hull (solidity near 1.0); an X mark is two thin crossing
# strokes, so its mask covers only a fraction of the diamond-shaped hull
# around it (empirically ~0.35-0.56 against synthetic fixtures, vs ~1.0-1.04
# for cats). This was measured directly against tests/fixtures/*.png rather
# than assumed -- an earlier bounding-box fill-ratio heuristic overlapped
# too much between the two classes and misclassified X marks as cats.
SOLIDITY_THRESHOLD = 0.7


def _center_patch(crop_bgr: np.ndarray, box, frac: float = 0.62) -> np.ndarray:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    cx0 = x0 + w * (1 - frac) / 2
    cy0 = y0 + h * (1 - frac) / 2
    cx1 = x1 - w * (1 - frac) / 2
    cy1 = y1 - h * (1 - frac) / 2
    return crop_bgr[int(round(cy0)):int(round(cy1)), int(round(cx0)):int(round(cx1))]


def detect_foreground(
    crop_bgr: np.ndarray,
    box,
    background_bgr: np.ndarray,
    templates: Optional[list] = None,
):
    """Returns (has_foreground: bool, kind: 'cat'|'x'|None, confidence: float).

    confidence is a heuristic in [0, 1], not a calibrated probability.
    """
    patch = _center_patch(crop_bgr, box)
    if patch.size == 0:
        return False, None, 0.0

    diff = np.linalg.norm(patch.astype(np.float64) - np.asarray(background_bgr, dtype=np.float64), axis=2)
    fg_mask = diff > FOREGROUND_DIFF_THRESHOLD
    fg_ratio = float(fg_mask.mean())

    if fg_ratio < FOREGROUND_MIN_RATIO:
        return False, None, float(min(1.0, 1.0 - fg_ratio))

    mask8 = (fg_mask * 255).astype(np.uint8)
    contours, _ = cv2.findContours(mask8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solidity = 1.0
    if contours:
        hull = cv2.convexHull(np.vstack(contours))
        hull_area = cv2.contourArea(hull)
        if hull_area > 0:
            solidity = float(fg_mask.sum()) / hull_area

    kind = "cat" if solidity > SOLIDITY_THRESHOLD else "x"
    # Confidence grows with distance from the cat/x decision boundary.
    base_conf = float(min(1.0, 0.45 + abs(solidity - SOLIDITY_THRESHOLD)))

    if templates:
        gray_patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        best_score, best_kind = 0.0, kind
        for tpl in templates:
            th, tw = tpl.patch_gray.shape[:2]
            if th < 4 or tw < 4:
                continue
            resized = cv2.resize(gray_patch, (tw, th))
            result = cv2.matchTemplate(resized, tpl.patch_gray, cv2.TM_CCOEFF_NORMED)
            score = float(result.max())
            if score > best_score:
                best_score, best_kind = score, tpl.kind
        if best_score > 0.5:
            kind = best_kind
            base_conf = max(base_conf, best_score)

    return True, kind, float(min(1.0, base_conf))


def make_calibration_template(crop_bgr: np.ndarray, box, kind: str) -> CalibrationTemplate:
    """Build a calibration template from a cell the user has identified as a
    cat or an X, for local storage and future template-matching boosts."""
    patch = _center_patch(crop_bgr, box, frac=0.62)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if patch.size else np.zeros((8, 8), dtype=np.uint8)
    x0, y0, x1, y1 = box
    return CalibrationTemplate(kind=kind, patch_gray=gray, source_cell_px=int(round(x1 - x0)))
