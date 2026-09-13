"""End-to-end recognition pipeline: crop -> grid -> regions -> foreground ->
RecognitionResult. This is the single entry point both the screen-capture
path and the Import Screenshot path call, so both go through identical
recognition logic.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from meowdoku.models import Board, CellConfidence, CellState, RecognitionResult
from meowdoku.recognition import foreground, grid_detect, region_detect

CAT_CONFIRM_THRESHOLD = 0.55
GRID_CONFIDENCE_REVIEW_THRESHOLD = 0.35
MIN_CROP_DIMENSION = 40


def _is_probably_empty_capture(crop_bgr: Optional[np.ndarray]) -> bool:
    if crop_bgr is None or crop_bgr.size == 0:
        return True
    return bool(crop_bgr.std() < 1.0)


def recognize(
    crop_bgr: np.ndarray,
    size_override: Optional[int] = None,
    templates: Optional[dict] = None,
) -> RecognitionResult:
    if _is_probably_empty_capture(crop_bgr):
        return RecognitionResult(
            success=False,
            failure_reason="empty_capture",
            crop_image=crop_bgr,
            warnings=[
                "The captured image is blank. This can mean Screen Recording "
                "permission is missing, or the selected area is off-screen."
            ],
        )

    h, w = crop_bgr.shape[:2]
    if min(h, w) < MIN_CROP_DIMENSION:
        return RecognitionResult(
            success=False,
            failure_reason="clipped_grid",
            crop_image=crop_bgr,
            warnings=["The selected area is too small to contain a board. Reselect a larger area."],
        )

    grid = grid_detect.detect_grid(crop_bgr, size_override=size_override)
    if grid is None:
        return RecognitionResult(
            success=False,
            failure_reason="no_grid_found",
            crop_image=crop_bgr,
            warnings=[
                "Could not find a square grid in the selected area. Try "
                "Reselect Area, adjust the crop, or set a board-size override."
            ],
        )

    warnings: list = []
    needs_review = False

    aspect = w / h
    if abs(aspect - 1.0) > 0.12:
        needs_review = True
        warnings.append("The selected crop is not square, which is unusual for this board; consider adjusting the crop.")

    n = grid.size
    cell_colors = [[region_detect.estimate_cell_background(crop_bgr, grid.cell_box(r, c)) for c in range(n)] for r in range(n)]

    region_ids_grid, region_colors_rgb, cluster_count = region_detect.cluster_regions(cell_colors, n)
    ambiguous_cells = region_detect.refine_ambiguous_cells(cell_colors, region_ids_grid, n)

    if cluster_count != n:
        needs_review = True
        warnings.append(
            f"Detected {cluster_count} distinct region color group(s) but the "
            f"board is {n}x{n}; review and correct the region map in the "
            "editor before solving."
        )
    if ambiguous_cells:
        needs_review = True
        warnings.append(f"{len(ambiguous_cells)} cell(s) had an ambiguous region color and should be reviewed.")

    ambiguous_set = set(ambiguous_cells)
    cell_states = [[CellState.EMPTY] * n for _ in range(n)]
    cell_confidence = [[CellConfidence() for _ in range(n)] for _ in range(n)]
    review_cells = list(ambiguous_cells)

    cat_templates = list(templates.get("cat", [])) if templates else []
    x_templates = list(templates.get("x", [])) if templates else []
    all_templates = cat_templates + x_templates

    for r in range(n):
        for c in range(n):
            box = grid.cell_box(r, c)
            has_fg, kind, conf = foreground.detect_foreground(crop_bgr, box, cell_colors[r][c], templates=all_templates)
            region_conf = 0.4 if (r, c) in ambiguous_set else 1.0
            cell_confidence[r][c] = CellConfidence(region_confidence=region_conf, foreground_confidence=conf, foreground_kind=kind)

            if not has_fg:
                continue
            if kind == "cat":
                if conf < CAT_CONFIRM_THRESHOLD:
                    cell_states[r][c] = CellState.CAT_UNCERTAIN
                    needs_review = True
                    if (r, c) not in review_cells:
                        review_cells.append((r, c))
                else:
                    cell_states[r][c] = CellState.CAT_CONFIRMED
            else:
                cell_states[r][c] = CellState.X_MARK

    if grid.confidence < GRID_CONFIDENCE_REVIEW_THRESHOLD:
        needs_review = True
        warnings.append("Grid-detection confidence is low; verify the board in the editor before trusting the automatic result.")

    board = Board(size=n, region_ids=region_ids_grid, region_colors=region_colors_rgb, cell_states=cell_states, revision=0)

    return RecognitionResult(
        success=True,
        board=board,
        grid=grid,
        cell_confidence=cell_confidence,
        needs_review=needs_review,
        review_cells=review_cells,
        warnings=warnings,
        crop_image=crop_bgr,
    )
