"""Region-color reconstruction from a detected grid.

Per-cell dominant background color is estimated from several inset sample
patches that avoid grid lines and the cell center (where cat art / X marks
live), then cells are clustered by perceptual (Lab) color distance. The
cluster count is reported honestly rather than forced to match the number
of regions the solver expects -- callers decide what to do with a mismatch.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

# Sample points as (fraction_x, fraction_y) within a cell box, chosen to sit
# in the corners/edges of the cell away from central foreground artwork and
# away from the grid border itself.
_SAMPLE_OFFSETS = [(0.22, 0.22), (0.78, 0.22), (0.22, 0.78), (0.78, 0.78), (0.5, 0.20)]


def estimate_cell_background(crop_bgr: np.ndarray, box, patch_radius: int = 2) -> np.ndarray:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    h_img, w_img = crop_bgr.shape[:2]
    samples = []
    for fx, fy in _SAMPLE_OFFSETS:
        px, py = x0 + fx * w, y0 + fy * h
        ix, iy = int(round(px)), int(round(py))
        xa, xb = max(0, ix - patch_radius), min(w_img, ix + patch_radius + 1)
        ya, yb = max(0, iy - patch_radius), min(h_img, iy + patch_radius + 1)
        if xb <= xa or yb <= ya:
            continue
        patch = crop_bgr[ya:yb, xa:xb].reshape(-1, 3)
        samples.append(np.median(patch, axis=0))
    if not samples:
        return np.array([128.0, 128.0, 128.0])
    # Median-of-medians: robust to any single sample patch landing on
    # foreground artwork, without assuming any one center pixel is safe.
    return np.median(np.array(samples), axis=0)


def bgr_to_lab(bgr_color: np.ndarray) -> np.ndarray:
    patch = np.uint8([[np.clip(bgr_color, 0, 255)]])
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)[0, 0].astype(np.float64)
    return lab


def cluster_regions(cell_colors_bgr, size: int, delta_e_threshold: float = 12.0):
    """Union-find (single-linkage) clustering of cell background colors by
    Lab distance. Returns (region_ids_grid, region_colors_rgb, cluster_count).

    Small regions are naturally preserved: a cell that is not within
    delta_e_threshold of anything else simply becomes its own singleton
    cluster, it is never merged or dropped to hit a target count.
    """
    labs = [[bgr_to_lab(cell_colors_bgr[r][c]) for c in range(size)] for r in range(size)]
    cells = [(r, c) for r in range(size) for c in range(size)]

    parent = {rc: rc for rc in cells}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(cells)):
        r1, c1 = cells[i]
        for j in range(i + 1, len(cells)):
            r2, c2 = cells[j]
            if np.linalg.norm(labs[r1][c1] - labs[r2][c2]) < delta_e_threshold:
                union(cells[i], cells[j])

    groups: dict = {}
    for rc in cells:
        groups.setdefault(find(rc), []).append(rc)

    region_ids_grid = [[None] * size for _ in range(size)]
    region_colors_rgb = {}
    for region_id, (_, members) in enumerate(groups.items()):
        for (r, c) in members:
            region_ids_grid[r][c] = region_id
        mean_bgr = np.mean([cell_colors_bgr[r][c] for (r, c) in members], axis=0)
        region_colors_rgb[region_id] = (int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0]))

    return region_ids_grid, region_colors_rgb, len(groups)


def _cluster_lab_means(cell_colors_bgr, region_ids_grid, size: int):
    sums: dict = {}
    counts: dict = {}
    for r in range(size):
        for c in range(size):
            rid = region_ids_grid[r][c]
            lab = bgr_to_lab(cell_colors_bgr[r][c])
            sums[rid] = sums.get(rid, np.zeros(3)) + lab
            counts[rid] = counts.get(rid, 0) + 1
    return {rid: sums[rid] / counts[rid] for rid in sums}


def refine_ambiguous_cells(cell_colors_bgr, region_ids_grid, size: int, ambiguous_ratio: float = 0.75):
    """Flag cells whose color sits nearly equidistant between two region
    clusters. When 3+ of a flagged cell's orthogonal neighbors agree on one
    of the two candidate regions, reassign to that region (neighbor/
    boundary evidence); the cell is still returned for user review either
    way, since the assignment was not made with confidence. Mutates
    region_ids_grid in place for cells resolved by neighbor evidence.
    """
    means = _cluster_lab_means(cell_colors_bgr, region_ids_grid, size)
    ambiguous = []
    for r in range(size):
        for c in range(size):
            lab = bgr_to_lab(cell_colors_bgr[r][c])
            dists = sorted((np.linalg.norm(lab - mean), rid) for rid, mean in means.items())
            if len(dists) < 2:
                continue
            d1, rid1 = dists[0]
            d2, rid2 = dists[1]
            if d2 < 1e-6 or rid1 == rid2:
                continue
            if d1 / d2 > ambiguous_ratio:
                neighbor_regions = []
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < size and 0 <= nc < size:
                        neighbor_regions.append(region_ids_grid[nr][nc])
                count1 = neighbor_regions.count(rid1)
                count2 = neighbor_regions.count(rid2)
                if count1 >= 3 and count1 > count2:
                    region_ids_grid[r][c] = rid1
                elif count2 >= 3 and count2 > count1:
                    region_ids_grid[r][c] = rid2
                ambiguous.append((r, c))
    return ambiguous
