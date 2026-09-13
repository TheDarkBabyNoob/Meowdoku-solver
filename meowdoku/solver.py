"""Pure-Python constraint solver for the Meowdoku one-cat-per-row/column/region
puzzle model. No GUI, capture, or image-processing imports.

Game rules encoded (see README for the App Store source):
  - Each colored region holds exactly one cat.
  - No two cats share a row or a column.
  - Cats cannot touch, including diagonally -- but ONLY immediate (distance-1)
    diagonal neighbors conflict. Distant cats on the same diagonal are legal.
    This is intentionally weaker than the chess-queen diagonal rule.

For a validated N-by-N board with exactly N regions, the row/column rule
forces exactly one cat per row and exactly one cat per column, so the model
uses one variable c[r] (the column of row r's cat) per row. Boards that are
not square or do not have exactly N regions are reported as unsupported by
``build_model`` rather than silently solved under a wrong model.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from meowdoku.models import (
    MAX_BOARD_SIZE,
    MIN_BOARD_SIZE,
    Board,
    CellState,
    HintResult,
    SolveOutcome,
    SolveStatus,
)


class ModelIssue(Enum):
    OK = "ok"
    NOT_SQUARE = "not_square"
    SIZE_OUT_OF_RANGE = "size_out_of_range"
    REGION_COUNT_MISMATCH = "region_count_mismatch"
    MULTIPLE_FIXED_IN_ROW = "multiple_fixed_in_row"
    CONTRADICTORY_FIXED_CAT = "contradictory_fixed_cat"


@dataclass(frozen=True)
class PuzzleModel:
    """Normalized, solver-ready puzzle model.

    ``region_of[r][c]`` is a region index in ``0..size-1`` (region ids from
    the Board are remapped to a dense index range here; the mapping has no
    bearing on gameplay). ``row_domains[r]`` is a bitmask over columns
    ``0..size-1`` that already accounts for blocked cells, opted-in X marks,
    and confirmed cats (a confirmed cat collapses that row's domain to a
    single bit). ``fixed_rows[r]`` records which rows had a confirmed cat,
    for hint bookkeeping.
    """

    size: int
    region_of: tuple
    row_domains: tuple
    fixed_rows: tuple


@dataclass
class ModelValidation:
    ok: bool
    issue: ModelIssue
    message: str
    model: Optional[PuzzleModel] = None


class _TimeoutSignal(Exception):
    pass


class _CancelledSignal(Exception):
    pass


def build_model(board: Board, respect_x_marks: bool = False) -> ModelValidation:
    """Validate board dimensions/region count and build a PuzzleModel.

    Returns ok=False (never raises) for any layout that does not match the
    "N-by-N board, N regions" formulation this solver implements, so callers
    can surface a clear "needs correction / unsupported" message instead of
    guessing.
    """
    n = board.size
    if not (MIN_BOARD_SIZE <= n <= MAX_BOARD_SIZE):
        return ModelValidation(
            False, ModelIssue.SIZE_OUT_OF_RANGE,
            f"Board size {n} is outside the supported range "
            f"{MIN_BOARD_SIZE}-{MAX_BOARD_SIZE}.",
        )
    if len(board.region_ids) != n or any(len(row) != n for row in board.region_ids):
        return ModelValidation(
            False, ModelIssue.NOT_SQUARE,
            "Board is not an N-by-N grid; this solver only implements the "
            "square one-region-per-row/column formulation.",
        )
    if len(board.cell_states) != n or any(len(row) != n for row in board.cell_states):
        return ModelValidation(False, ModelIssue.NOT_SQUARE, "Cell state grid does not match board size.")

    distinct_regions = sorted(set(v for row in board.region_ids for v in row), key=repr)
    if len(distinct_regions) != n:
        return ModelValidation(
            False, ModelIssue.REGION_COUNT_MISMATCH,
            f"Detected {len(distinct_regions)} region(s) but the board is "
            f"{n}x{n}; the one-cat-per-region model requires exactly {n} "
            "regions. Correct the region map before solving.",
        )
    region_index = {rid: i for i, rid in enumerate(distinct_regions)}
    region_of = tuple(
        tuple(region_index[board.region_ids[r][c]] for c in range(n)) for r in range(n)
    )

    forbidden_mask = [0] * n
    for r in range(n):
        for c in range(n):
            st = board.cell_states[r][c]
            if st == CellState.BLOCKED:
                forbidden_mask[r] |= 1 << c
            elif st == CellState.X_MARK and respect_x_marks:
                forbidden_mask[r] |= 1 << c

    fixed_rows = [None] * n
    for r in range(n):
        confirmed_cols = [c for c in range(n) if board.cell_states[r][c] == CellState.CAT_CONFIRMED]
        if len(confirmed_cols) > 1:
            return ModelValidation(
                False, ModelIssue.MULTIPLE_FIXED_IN_ROW,
                f"Row {r + 1} has more than one confirmed cat; correct the board.",
            )
        if confirmed_cols:
            col = confirmed_cols[0]
            if forbidden_mask[r] & (1 << col):
                return ModelValidation(
                    False, ModelIssue.CONTRADICTORY_FIXED_CAT,
                    f"Row {r + 1}, column {col + 1} is both a confirmed cat "
                    "and excluded (blocked or X mark); correct the board.",
                )
            fixed_rows[r] = col

    full_mask = (1 << n) - 1
    row_domains = []
    for r in range(n):
        if fixed_rows[r] is not None:
            row_domains.append(1 << fixed_rows[r])
        else:
            row_domains.append(full_mask & ~forbidden_mask[r])

    return ModelValidation(
        True, ModelIssue.OK, "OK",
        PuzzleModel(size=n, region_of=region_of, row_domains=tuple(row_domains), fixed_rows=tuple(fixed_rows)),
    )


def _row_domain(model: PuzzleModel, used_cols: int, used_regions: int, assigned, row: int) -> int:
    mask = model.row_domains[row] & ~used_cols
    m = mask
    kept = 0
    while m:
        low = m & (-m)
        c = low.bit_length() - 1
        if not (used_regions & (1 << model.region_of[row][c])):
            kept |= low
        m ^= low
    mask = kept
    n = model.size
    for nb in (row - 1, row + 1):
        if 0 <= nb < n and assigned[nb] is not None:
            col_nb = assigned[nb]
            excl = 0
            for dc in (-1, 0, 1):
                cc = col_nb + dc
                if 0 <= cc < n:
                    excl |= 1 << cc
            mask &= ~excl
    return mask


def independent_validate(model: PuzzleModel, assignment) -> bool:
    """Re-derive every constraint from the static model and a candidate
    complete assignment, independent of the search's own bookkeeping. Used
    as a safety net before any solution is ever returned to a caller."""
    n = model.size
    if len(assignment) != n:
        return False
    if any(a is None or not (0 <= a < n) for a in assignment):
        return False
    if len(set(assignment)) != n:
        return False
    regions_used = [model.region_of[r][assignment[r]] for r in range(n)]
    if len(set(regions_used)) != n:
        return False
    for r in range(1, n):
        if abs(assignment[r] - assignment[r - 1]) <= 1:
            return False
    for r in range(n):
        if not (model.row_domains[r] >> assignment[r]) & 1:
            return False
    return True


def _backtrack(model, used_cols, used_regions, assigned, solutions, deadline, cancel_event, nodes, max_solutions):
    if deadline is not None and time.monotonic() > deadline:
        raise _TimeoutSignal()
    if cancel_event is not None and cancel_event.is_set():
        raise _CancelledSignal()
    nodes[0] += 1

    n = model.size
    best_row = -1
    best_mask = 0
    best_count = None
    for r in range(n):
        if assigned[r] is None:
            mask = _row_domain(model, used_cols, used_regions, assigned, r)
            cnt = bin(mask).count("1")
            if cnt == 0:
                return False
            if best_count is None or cnt < best_count:
                best_count = cnt
                best_row = r
                best_mask = mask
                if cnt == 1:
                    break  # can't do better than a forced move

    if best_row == -1:
        solution = list(assigned)
        if not independent_validate(model, solution):
            raise AssertionError("solver produced an arrangement that fails independent validation")
        solutions.append(solution)
        return len(solutions) >= max_solutions

    row = best_row
    m = best_mask
    while m:
        low = m & (-m)
        col = low.bit_length() - 1
        m ^= low
        assigned[row] = col
        stop = _backtrack(
            model, used_cols | (1 << col), used_regions | (1 << model.region_of[row][col]),
            assigned, solutions, deadline, cancel_event, nodes, max_solutions,
        )
        assigned[row] = None
        if stop:
            return True
    return False


def solve(
    board: Board,
    respect_x_marks: bool = False,
    max_solutions: int = 2,
    time_budget_seconds: float = 5.0,
    cancel_event: Optional[threading.Event] = None,
) -> SolveOutcome:
    """Search for up to ``max_solutions`` distinct solutions.

    Status semantics:
      MODEL_UNSUPPORTED       -- board is not a valid N-by-N / N-region model
      NO_SOLUTION             -- search exhausted, zero solutions exist
      UNIQUE_SOLUTION         -- search exhausted, exactly one solution exists
      MULTIPLE_SOLUTIONS      -- search exhausted, >= 2 solutions exist (not
                                  necessarily the total count)
      SOLUTION_FOUND_UNIQUENESS_UNVERIFIED -- timed out with exactly one
                                  solution found so far
      SEARCH_INCOMPLETE       -- timed out with zero solutions found so far
      CANCELLED               -- cancel_event was set before completion
    """
    validation = build_model(board, respect_x_marks=respect_x_marks)
    if not validation.ok:
        return SolveOutcome(status=SolveStatus.MODEL_UNSUPPORTED, message=validation.message)
    model = validation.model
    n = model.size

    start = time.monotonic()
    deadline = start + time_budget_seconds if time_budget_seconds is not None else None
    solutions: list = []
    nodes = [0]
    assigned = [None] * n
    timed_out = False
    cancelled = False
    try:
        _backtrack(model, 0, 0, assigned, solutions, deadline, cancel_event, nodes, max_solutions)
    except _TimeoutSignal:
        timed_out = True
    except _CancelledSignal:
        cancelled = True
    elapsed = time.monotonic() - start

    if cancelled:
        status = SolveStatus.CANCELLED
    elif timed_out:
        status = (
            SolveStatus.SOLUTION_FOUND_UNIQUENESS_UNVERIFIED if len(solutions) == 1 else SolveStatus.SEARCH_INCOMPLETE
        )
    else:
        if len(solutions) == 0:
            status = SolveStatus.NO_SOLUTION
        elif len(solutions) == 1:
            # Only a search that was allowed to look for a second solution
            # (max_solutions >= 2) and still found just one proves
            # uniqueness -- with max_solutions == 1 the search deliberately
            # stopped at the first hit and never looked further, so
            # uniqueness was never actually checked.
            status = SolveStatus.UNIQUE_SOLUTION if max_solutions >= 2 else SolveStatus.SOLUTION_FOUND_UNIQUENESS_UNVERIFIED
        else:
            status = SolveStatus.MULTIPLE_SOLUTIONS

    return SolveOutcome(status=status, solutions=solutions, elapsed_seconds=elapsed, nodes_explored=nodes[0])


def find_guaranteed_hint(
    board: Board,
    respect_x_marks: bool = False,
    time_budget_seconds: float = 5.0,
    cancel_event: Optional[threading.Event] = None,
) -> HintResult:
    """Find one cell that must hold a cat in every valid solution.

    A cell (r, c) is proven guaranteed by forbidding it and showing the
    resulting board is exhaustively unsatisfiable (i.e. every solution to
    the original board must place a cat at (r, c)). This is a stronger and
    more honest guarantee than "the first two solutions happen to agree" --
    it holds even when the board is not fully known to be unique. A timed
    out proof attempt never yields a hint.
    """
    validation = build_model(board, respect_x_marks=respect_x_marks)
    if not validation.ok:
        return HintResult(found=False, explanation=validation.message)
    model = validation.model
    n = model.size

    deadline_total = time.monotonic() + time_budget_seconds
    first = solve(
        board, respect_x_marks=respect_x_marks, max_solutions=1,
        time_budget_seconds=max(0.0, deadline_total - time.monotonic()), cancel_event=cancel_event,
    )
    if first.status == SolveStatus.NO_SOLUTION:
        return HintResult(found=False, explanation="This board has no valid solution, so no hint can be given.")
    if not first.solutions:
        return HintResult(found=False, explanation="The search did not finish in time; no guaranteed hint is available yet.")

    candidate = first.solutions[0]
    for r in range(n):
        c = candidate[r]
        if model.fixed_rows[r] == c:
            continue
        remaining = deadline_total - time.monotonic()
        if remaining <= 0:
            return HintResult(found=False, explanation="Ran out of time proving a guaranteed placement.")
        trial_board = board.with_cell_state(r, c, CellState.BLOCKED)
        outcome = solve(
            trial_board, respect_x_marks=respect_x_marks, max_solutions=1,
            time_budget_seconds=remaining, cancel_event=cancel_event,
        )
        if outcome.status == SolveStatus.NO_SOLUTION:
            return HintResult(
                found=True, row=r, col=c,
                explanation=(
                    f"Excluding row {r + 1}, column {c + 1} leaves no valid "
                    "completion of the board, so a cat must go there."
                ),
            )
        if outcome.status == SolveStatus.CANCELLED:
            return HintResult(found=False, explanation="Hint search was cancelled.")
    return HintResult(found=False, explanation="No cell could be proven guaranteed within the time budget.")
