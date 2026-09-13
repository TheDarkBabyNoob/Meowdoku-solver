"""Board-session state with monotonically increasing revisions.

This is the mechanism that guarantees a scan or edit immediately invalidates
whatever a slow background worker was still computing for the previous
board: a worker is started with the revision number that was current when
it was launched, and its result is only accepted if that revision is still
current when it finishes. Pure Python, no Qt import, so it's directly unit
testable (including "rescan while an old worker is finishing") without a
running event loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from meowdoku.models import Board, RecognitionResult, SolveOutcome


@dataclass
class BoardSession:
    revision: int = 0
    board: Optional[Board] = None
    last_recognition: Optional[RecognitionResult] = None
    last_solve: Optional[SolveOutcome] = None
    solve_revision: Optional[int] = None

    def start_new_scan(self) -> int:
        """Call the instant Scan & Solve / Import Screenshot begins, before
        any capture or recognition work happens. Returns the revision the
        resulting worker must tag its results with."""
        self.revision += 1
        self.last_solve = None
        self.solve_revision = None
        return self.revision

    def start_edit(self) -> int:
        """Call whenever the user edits the board. An edit invalidates any
        solve in flight for the pre-edit board, but does not require redoing
        recognition -- callers keep last_recognition/board and mutate them,
        then re-solve against the new revision."""
        self.revision += 1
        self.last_solve = None
        self.solve_revision = None
        return self.revision

    def accept_recognition_result(self, revision: int, result: RecognitionResult) -> bool:
        """Returns True if applied (revision still current), False if the
        result was discarded as stale."""
        if revision != self.revision:
            return False
        self.last_recognition = result
        if result.success and result.board is not None:
            result.board.revision = self.revision
            self.board = result.board
        return True

    def accept_solve_result(self, revision: int, outcome: SolveOutcome) -> bool:
        if revision != self.revision:
            return False
        self.last_solve = outcome
        self.solve_revision = revision
        return True

    def solve_is_current(self) -> bool:
        return self.last_solve is not None and self.solve_revision == self.revision
