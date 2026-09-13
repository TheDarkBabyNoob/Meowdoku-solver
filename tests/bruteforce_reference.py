"""An intentionally independent, unoptimized reference solver used only by
tests to check the real solver's answers. Does not share any code with
meowdoku/solver.py (no shared helper functions, no shared bitmask tricks) so
a bug common to both would be a coincidence, not a shared blind spot.
"""
from __future__ import annotations

from itertools import permutations

from meowdoku.models import Board, CellState


def brute_force_all_solutions(board: Board, respect_x_marks: bool = False, limit: int = 10_000):
    """Try every permutation of columns (one cat per row, all columns
    distinct by construction) and keep the ones satisfying every rule,
    checked from scratch against the raw Board -- no PuzzleModel, no
    bitmasks, no shared helpers with the real solver."""
    n = board.size
    confirmed = {}
    forbidden = set()
    for r in range(n):
        for c in range(n):
            state = board.cell_states[r][c]
            if state == CellState.CAT_CONFIRMED:
                confirmed[r] = c
            elif state == CellState.BLOCKED:
                forbidden.add((r, c))
            elif state == CellState.X_MARK and respect_x_marks:
                forbidden.add((r, c))

    solutions = []
    for perm in permutations(range(n)):
        if len(solutions) >= limit:
            break
        ok = True
        for r in range(n):
            if r in confirmed and perm[r] != confirmed[r]:
                ok = False
                break
            if (r, perm[r]) in forbidden:
                ok = False
                break
        if not ok:
            continue
        regions_seen = set()
        for r in range(n):
            region = board.region_ids[r][perm[r]]
            if region in regions_seen:
                ok = False
                break
            regions_seen.add(region)
        if not ok:
            continue
        for r in range(1, n):
            if abs(perm[r] - perm[r - 1]) <= 1:
                ok = False
                break
        if ok:
            solutions.append(list(perm))
    return solutions
