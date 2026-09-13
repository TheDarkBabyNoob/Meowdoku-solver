"""Tests for BoardSession's revision-based staleness guard -- the mechanism
that ensures a slow scan/solve worker for a superseded board can never
overwrite state for the board the user is currently looking at. Pure
Python, no Qt/threading needed to exercise the logic itself; the ordering
being tested (start a new scan/edit before a prior worker's result arrives)
is exactly what happens when a user rescans or edits while a background
QThread is still finishing.
"""
from __future__ import annotations

from meowdoku.models import Board, CellState, RecognitionResult, SolveOutcome, SolveStatus
from meowdoku.session import BoardSession


def make_board(size=4):
    region_ids = [[r for _ in range(size)] for r in range(size)]
    colors = {i: (0, 0, 0) for i in range(size)}
    states = [[CellState.EMPTY] * size for _ in range(size)]
    return Board(size=size, region_ids=region_ids, region_colors=colors, cell_states=states)


def test_rescan_invalidates_a_slower_earlier_scan_worker():
    session = BoardSession()
    rev1 = session.start_new_scan()  # user clicks Scan & Solve
    # Before the slow worker for rev1 finishes, the user clicks it again.
    rev2 = session.start_new_scan()
    assert rev2 == rev1 + 1

    # The slow rev1 worker finally finishes and tries to report its result.
    stale_result = RecognitionResult(success=True, board=make_board())
    accepted = session.accept_recognition_result(rev1, stale_result)
    assert accepted is False
    assert session.board is None  # stale result must not have been applied

    # The rev2 worker (the current one) finishes afterwards and IS applied.
    fresh_result = RecognitionResult(success=True, board=make_board())
    accepted2 = session.accept_recognition_result(rev2, fresh_result)
    assert accepted2 is True
    assert session.board is fresh_result.board
    assert session.board.revision == rev2


def test_edit_invalidates_an_in_flight_solve_for_the_pre_edit_board():
    session = BoardSession()
    rev1 = session.start_new_scan()
    session.accept_recognition_result(rev1, RecognitionResult(success=True, board=make_board()))

    # A solve worker is launched for rev1's board...
    # ...but before it returns, the user edits the board (e.g. paints a
    # region), which bumps the revision.
    rev2 = session.start_edit()
    assert rev2 == rev1 + 1

    # The old solve worker's result must be discarded even though it is a
    # "successful" outcome, because it answers a question about a board
    # state that no longer exists.
    stale_outcome = SolveOutcome(status=SolveStatus.UNIQUE_SOLUTION, solutions=[[1, 3, 0, 2]])
    accepted = session.accept_solve_result(rev1, stale_outcome)
    assert accepted is False
    assert session.last_solve is None
    assert not session.solve_is_current()

    fresh_outcome = SolveOutcome(status=SolveStatus.MULTIPLE_SOLUTIONS, solutions=[[1, 3, 0, 2], [2, 0, 3, 1]])
    accepted2 = session.accept_solve_result(rev2, fresh_outcome)
    assert accepted2 is True
    assert session.last_solve is fresh_outcome
    assert session.solve_is_current()


def test_multiple_stale_workers_all_rejected_only_current_one_wins():
    session = BoardSession()
    revisions = [session.start_new_scan() for _ in range(5)]  # 5 rapid rescans
    current = revisions[-1]

    for rev in revisions[:-1]:
        assert session.accept_recognition_result(rev, RecognitionResult(success=True, board=make_board())) is False

    final_board = make_board()
    assert session.accept_recognition_result(current, RecognitionResult(success=True, board=final_board)) is True
    assert session.board is final_board


def test_failed_recognition_result_does_not_touch_existing_board():
    session = BoardSession()
    rev1 = session.start_new_scan()
    board = make_board()
    session.accept_recognition_result(rev1, RecognitionResult(success=True, board=board))

    rev2 = session.start_new_scan()
    failure = RecognitionResult(success=False, failure_reason="empty_capture")
    accepted = session.accept_recognition_result(rev2, failure)
    assert accepted is True  # the (failure) result for the current revision is recorded...
    assert session.board is board  # ...but the board itself is left untouched, not wiped to None
