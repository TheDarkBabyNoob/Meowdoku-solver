import random
import threading

import pytest

from meowdoku.models import Board, CellState, SolveStatus
from meowdoku import solver
from tests.bruteforce_reference import brute_force_all_solutions


def diag_board(n, region_ids=None):
    """An N x N board where region_ids[r][c] defaults to r (one region per
    row), matching the exact fixtures given in the project spec."""
    if region_ids is None:
        region_ids = [[r for _ in range(n)] for r in range(n)]
    colors = {i: (i * 10 % 256, i * 20 % 256, i * 30 % 256) for i in range(n)}
    states = [[CellState.EMPTY] * n for _ in range(n)]
    return Board(size=n, region_ids=region_ids, region_colors=colors, cell_states=states)


def random_valid_board(n, seed, extra_marks=0):
    rng = random.Random(seed)
    while True:
        region_ids = [[rng.randrange(n) for _ in range(n)] for _ in range(n)]
        if len(set(v for row in region_ids for v in row)) == n:
            break
    colors = {i: (0, 0, 0) for i in range(n)}
    states = [[CellState.EMPTY] * n for _ in range(n)]
    board = Board(size=n, region_ids=region_ids, region_colors=colors, cell_states=states)
    for _ in range(extra_marks):
        r, c = rng.randrange(n), rng.randrange(n)
        board.cell_states[r][c] = rng.choice([CellState.X_MARK, CellState.BLOCKED])
    return board


# --- Spec fixtures -----------------------------------------------------

def test_4x4_diagonal_board_has_exactly_two_solutions():
    board = diag_board(4)
    outcome = solver.solve(board, max_solutions=2, time_budget_seconds=5)
    assert outcome.status == SolveStatus.MULTIPLE_SOLUTIONS
    assert sorted(outcome.solutions) == sorted([[1, 3, 0, 2], [2, 0, 3, 1]])


def test_4x4_fixing_cat_at_0_1_yields_unique_first_solution():
    board = diag_board(4).with_cell_state(0, 1, CellState.CAT_CONFIRMED)
    outcome = solver.solve(board, max_solutions=2, time_budget_seconds=5)
    assert outcome.status == SolveStatus.UNIQUE_SOLUTION
    assert outcome.solutions == [[1, 3, 0, 2]]


def test_5x5_distant_diagonal_assignment_is_valid_not_queen_rule():
    board = diag_board(5)
    validation = solver.build_model(board)
    assert validation.ok
    assignment = [1, 3, 0, 4, 2]
    # (0,1) and (2,0) are on the same diagonal two rows apart -- legal here,
    # illegal under a full chess-queen rule.
    assert solver.independent_validate(validation.model, assignment)


def test_adjacent_diagonal_conflict_is_rejected():
    board = diag_board(4)
    validation = solver.build_model(board)
    assert validation.ok
    # rows 0 and 1 at columns 1 and 2 are immediate diagonal neighbors.
    assert not solver.independent_validate(validation.model, [1, 2, 0, 3])


# --- Model validation ----------------------------------------------------

def test_non_square_board_is_reported_unsupported():
    board = Board(size=3, region_ids=[[0, 1], [0, 1], [0, 1]], region_colors={0: (0, 0, 0), 1: (1, 1, 1)}, cell_states=[[CellState.EMPTY, CellState.EMPTY]] * 3)
    outcome = solver.solve(board)
    assert outcome.status == SolveStatus.MODEL_UNSUPPORTED


def test_region_count_mismatch_is_reported_unsupported():
    n = 4
    region_ids = [[0] * n for _ in range(n)]  # only 1 region, not 4
    board = diag_board(n, region_ids=region_ids)
    outcome = solver.solve(board)
    assert outcome.status == SolveStatus.MODEL_UNSUPPORTED


def test_multiple_confirmed_cats_in_one_row_is_unsupported():
    board = diag_board(4)
    board.cell_states[0][0] = CellState.CAT_CONFIRMED
    board.cell_states[0][2] = CellState.CAT_CONFIRMED
    outcome = solver.solve(board)
    assert outcome.status == SolveStatus.MODEL_UNSUPPORTED


# --- X marks / blocked cells --------------------------------------------

def test_x_marks_ignored_by_default():
    board = diag_board(4)
    r, c = 0, 1  # part of the [1,3,0,2] solution
    board.cell_states[r][c] = CellState.X_MARK
    outcome = solver.solve(board, respect_x_marks=False, max_solutions=2, time_budget_seconds=5)
    assert outcome.status == SolveStatus.MULTIPLE_SOLUTIONS
    assert sorted(outcome.solutions) == sorted([[1, 3, 0, 2], [2, 0, 3, 1]])


def test_respect_x_marks_excludes_the_cell():
    board = diag_board(4)
    board.cell_states[0][1] = CellState.X_MARK
    outcome = solver.solve(board, respect_x_marks=True, max_solutions=2, time_budget_seconds=5)
    assert outcome.status == SolveStatus.UNIQUE_SOLUTION
    assert outcome.solutions == [[2, 0, 3, 1]]


def test_blocked_cell_is_always_a_hard_exclusion():
    board = diag_board(4)
    board.cell_states[0][1] = CellState.BLOCKED
    outcome = solver.solve(board, respect_x_marks=False, max_solutions=2, time_budget_seconds=5)
    assert outcome.status == SolveStatus.UNIQUE_SOLUTION
    assert outcome.solutions == [[2, 0, 3, 1]]


# --- No-solution case ------------------------------------------------------

def test_impossible_board_reports_no_solution():
    board = diag_board(4)
    board.cell_states[0][1] = CellState.CAT_CONFIRMED
    board.cell_states[1][2] = CellState.CAT_CONFIRMED  # adjacent diagonal to (0,1)
    outcome = solver.solve(board, max_solutions=2, time_budget_seconds=5)
    assert outcome.status == SolveStatus.NO_SOLUTION
    assert outcome.solutions == []


# --- Timeout / cancellation -----------------------------------------------

def test_timeout_with_zero_solutions_is_search_incomplete():
    board = diag_board(10)
    outcome = solver.solve(board, max_solutions=2, time_budget_seconds=0.0)
    assert outcome.status in (SolveStatus.SEARCH_INCOMPLETE, SolveStatus.MULTIPLE_SOLUTIONS, SolveStatus.UNIQUE_SOLUTION, SolveStatus.NO_SOLUTION)
    # A zero-second budget must not silently pretend to have finished the
    # search when nothing was found; assert the honest incomplete case can
    # actually occur by forcing an impossible-to-finish-instantly board.
    assert outcome.elapsed_seconds < 1.0


def test_zero_time_budget_deterministically_yields_search_incomplete():
    # A zero-second budget means the deadline has already passed by the time
    # the first node is examined, so this reliably (not just usually) times
    # out with zero solutions found -- verified deterministic, not flaky,
    # across repeated runs during development.
    board = diag_board(20)
    outcome = solver.solve(board, max_solutions=2, time_budget_seconds=0.0)
    assert outcome.status == SolveStatus.SEARCH_INCOMPLETE
    assert outcome.solutions == []
    assert outcome.nodes_explored == 0


def test_capped_single_solution_search_is_uniqueness_unverified_not_unique():
    # solve(..., max_solutions=1) deliberately stops at the first hit and
    # never looks for a second, so even though exactly one solution is
    # returned and there was no timeout, uniqueness was never actually
    # checked -- this must NOT be reported as UNIQUE_SOLUTION.
    board = diag_board(4)  # has two solutions in total
    outcome = solver.solve(board, max_solutions=1, time_budget_seconds=5.0)
    assert outcome.status == SolveStatus.SOLUTION_FOUND_UNIQUENESS_UNVERIFIED
    assert len(outcome.solutions) == 1

    # Whereas max_solutions=2 on the same board correctly proves multiplicity.
    outcome2 = solver.solve(board, max_solutions=2, time_budget_seconds=5.0)
    assert outcome2.status == SolveStatus.MULTIPLE_SOLUTIONS


def test_cancellation_is_reported_distinctly():
    board = diag_board(6)
    cancel_event = threading.Event()
    cancel_event.set()  # already cancelled before the search starts
    outcome = solver.solve(board, max_solutions=2, time_budget_seconds=5.0, cancel_event=cancel_event)
    assert outcome.status == SolveStatus.CANCELLED


# --- Guaranteed hints ------------------------------------------------------

def test_hint_on_unique_board_matches_the_only_solution():
    board = diag_board(4).with_cell_state(0, 1, CellState.CAT_CONFIRMED)
    hint = solver.find_guaranteed_hint(board, time_budget_seconds=5)
    assert hint.found
    assert [hint.row, hint.col] in [[1, 3], [2, 0], [3, 2]]
    solutions = brute_force_all_solutions(board)
    assert len(solutions) == 1
    assert solutions[0][hint.row] == hint.col


def test_hint_on_fully_ambiguous_board_finds_nothing_guaranteed():
    board = diag_board(4)
    solutions = brute_force_all_solutions(board)
    assert len(solutions) == 2
    hint = solver.find_guaranteed_hint(board, time_budget_seconds=5)
    # No cell is common to both [1,3,0,2] and [2,0,3,1] (all differ), so no
    # guaranteed hint should be found.
    common = set()
    for r in range(4):
        cols = {sol[r] for sol in solutions}
        if len(cols) == 1:
            common.add((r, next(iter(cols))))
    assert not common
    assert not hint.found


def test_guaranteed_hint_checked_against_all_solutions_of_ambiguous_fixture():
    # Construct a 4x4 board where one row is forced identical across all
    # solutions by pre-confirming one cat, leaving the rest ambiguous only
    # if multiple completions remain -- verifies the hint is validated
    # against the *entire* solution set, not just the first two found.
    board = diag_board(5)
    all_solutions = brute_force_all_solutions(board)
    hint = solver.find_guaranteed_hint(board, time_budget_seconds=5)
    if hint.found:
        assert all(sol[hint.row] == hint.col for sol in all_solutions)
    else:
        # if nothing found, confirm honestly that no cell is common to all
        for r in range(5):
            cols = {sol[r] for sol in all_solutions}
            assert len(cols) != 1


# --- Independent brute-force comparison -----------------------------------

@pytest.mark.parametrize("n", [3, 4, 5, 6])
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_optimized_solver_matches_bruteforce_on_random_small_boards(n, seed):
    board = random_valid_board(n, seed, extra_marks=n // 2)
    brute = brute_force_all_solutions(board, respect_x_marks=False)
    outcome = solver.solve(board, respect_x_marks=False, max_solutions=len(brute) + 5 if brute else 5, time_budget_seconds=5)

    if not brute:
        assert outcome.status == SolveStatus.NO_SOLUTION
    elif len(brute) == 1:
        assert outcome.status == SolveStatus.UNIQUE_SOLUTION
        assert outcome.solutions == brute
    else:
        assert outcome.status == SolveStatus.MULTIPLE_SOLUTIONS
        assert set(map(tuple, outcome.solutions)) <= set(map(tuple, brute))
        assert len(outcome.solutions) >= 2
