"""Board-bounds and grid-size detection within a captured crop.

Approach: project Canny edge energy onto the x and y axes, then estimate the
cell spacing directly from the gaps between strong edge peaks in each
projection (rather than testing every candidate board size top-down and
picking the highest average score). The direct-spacing approach was chosen
after the top-down scoring method was found, during development against
tests/fixtures/*.png, to be vulnerable to aliasing: a small candidate N
whose few grid lines happen to land on a SUBSET of the true grid lines (a
divisor of the real N, e.g. testing N=2 against a true 4x4 or 6x6 board)
can score deceptively well since it only has to match one or two lines
instead of many. Measuring the actual peak-to-peak spacing and dividing it
into the crop length avoids that trap. The peak-spacing estimate is then
refined by comparing it against its immediate neighbors (N-1, N, N+1) using
average-line-strength scoring, to correct simple off-by-one errors (e.g. a
peak detector missing the very first or last line).

This never hardcodes one board size, screen location, or palette -- it only
assumes the board is a roughly square grid with visible cell boundaries.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from meowdoku.models import MAX_BOARD_SIZE, MIN_BOARD_SIZE, GridGeometry


def _edge_projections(gray: np.ndarray):
    edges = cv2.Canny(gray, 40, 120)
    col_profile = edges.sum(axis=0).astype(np.float64)
    row_profile = edges.sum(axis=1).astype(np.float64)
    return col_profile, row_profile


def _find_peaks(profile: np.ndarray, min_distance: int, threshold_frac: float = 0.25):
    if profile.size == 0:
        return []
    peak_threshold = float(profile.max()) * threshold_frac
    if peak_threshold <= 0:
        return []
    above = np.where(profile >= peak_threshold)[0]
    if len(above) == 0:
        return []
    peaks = []
    cluster = [above[0]]
    for idx in above[1:]:
        if idx - cluster[-1] <= min_distance:
            cluster.append(idx)
        else:
            peaks.append(int(cluster[int(np.argmax(profile[cluster]))]))
            cluster = [idx]
    peaks.append(int(cluster[int(np.argmax(profile[cluster]))]))
    return peaks


def _estimate_size_from_spacing(profile: np.ndarray, length: int):
    """Returns (n_estimate, confidence) or (None, 0.0)."""
    if length <= 0:
        return None, 0.0
    min_distance = max(3, int(length / MAX_BOARD_SIZE / 2))
    peaks = sorted(_find_peaks(profile, min_distance=min_distance))
    if len(peaks) < 2:
        return None, 0.0
    gaps = np.diff(np.asarray(peaks, dtype=np.float64))
    min_plausible_cell = length / MAX_BOARD_SIZE
    gaps = gaps[gaps >= min_plausible_cell * 0.6]
    if len(gaps) == 0:
        return None, 0.0
    median_gap = float(np.median(gaps))
    if median_gap <= 0:
        return None, 0.0
    n_estimate = int(round(length / median_gap))
    n_estimate = max(MIN_BOARD_SIZE, min(MAX_BOARD_SIZE, n_estimate))
    consistency = 1.0 - min(1.0, float(np.std(gaps)) / (median_gap + 1e-6))
    return n_estimate, max(0.0, consistency)


def _score_candidate_size(profile: np.ndarray, length: int, n: int) -> float:
    """Average strong-edge alignment for n evenly-spaced INTERNAL grid
    lines (excluding the crop's own outer edges at i=0 and i=n, since Canny
    often produces a spurious strong edge right at the crop boundary,
    which would otherwise favor small n regardless of actual content)."""
    if n < MIN_BOARD_SIZE or length <= 0:
        return -1.0
    internal_indices = [1] if n == MIN_BOARD_SIZE else range(1, n)
    step = length / n
    window = max(2, int(round(length * 0.01)))
    score = 0.0
    count = 0
    for i in internal_indices:
        p = min(max(int(round(i * step)), 0), length - 1)
        lo, hi = max(0, p - window), min(length, p + window + 1)
        score += float(profile[lo:hi].max()) if hi > lo else 0.0
        count += 1
    return score / max(1, count)


def _locate_bounds(profile: np.ndarray, length: int, n: int):
    """Find the board's actual left/right (or top/bottom) pixel extent
    within the crop, rather than assuming the grid spans the full crop --
    a crop can include surrounding UI margin/padding around the board
    (e.g. an imprecise manual selection), so dividing the whole crop width
    uniformly by n would misalign every cell. If most of the n+1 grid
    lines (including the two outer border lines) were found as peaks, the
    first and last peak are a direct estimate of the board's true bounds;
    otherwise fall back to the full crop span."""
    min_distance = max(3, int(length / MAX_BOARD_SIZE / 2))
    peaks = sorted(_find_peaks(profile, min_distance=min_distance))
    if len(peaks) >= n:
        return peaks[0], peaks[-1]
    return 0, length


def _refine_near(profile_x, w, profile_y, h, n_guess: int) -> int:
    best_n, best_score = n_guess, -1.0
    for n in (n_guess - 1, n_guess, n_guess + 1):
        if n < MIN_BOARD_SIZE or n > MAX_BOARD_SIZE:
            continue
        score = (_score_candidate_size(profile_x, w, n) + _score_candidate_size(profile_y, h, n)) / 2.0
        if score > best_score:
            best_score = score
            best_n = n
    return best_n


def detect_grid(crop_bgr: np.ndarray, size_override: Optional[int] = None) -> Optional[GridGeometry]:
    """Return a GridGeometry for the detected (or overridden) board size, or
    None if no plausible grid could be found at all."""
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    h, w = crop_bgr.shape[:2]
    if h < 20 or w < 20:
        return None

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    col_profile, row_profile = _edge_projections(gray)
    max_possible = max(float(col_profile.max()), float(row_profile.max()), 1.0)

    if size_override is not None:
        n = size_override
    else:
        n_x, conf_x = _estimate_size_from_spacing(col_profile, w)
        n_y, conf_y = _estimate_size_from_spacing(row_profile, h)
        if n_x is None and n_y is None:
            return None
        if n_x is None:
            n_guess = n_y
        elif n_y is None:
            n_guess = n_x
        else:
            n_guess = n_x if conf_x >= conf_y else n_y
        n = _refine_near(col_profile, w, row_profile, h, n_guess)

    x0, x1 = _locate_bounds(col_profile, w, n)
    y0, y1 = _locate_bounds(row_profile, h, n)
    x_edges = [round(x0 + i * (x1 - x0) / n) for i in range(n + 1)]
    y_edges = [round(y0 + i * (y1 - y0) / n) for i in range(n + 1)]
    x_edges[0], y_edges[0] = max(0, x_edges[0]), max(0, y_edges[0])
    x_edges[-1], y_edges[-1] = min(w, x_edges[-1]), min(h, y_edges[-1])

    final_score = (_score_candidate_size(col_profile, w, n) + _score_candidate_size(row_profile, h, n)) / 2.0
    confidence = float(min(1.0, max(0.0, final_score / max_possible)))
    return GridGeometry(size=n, x_edges=x_edges, y_edges=y_edges, confidence=confidence)
