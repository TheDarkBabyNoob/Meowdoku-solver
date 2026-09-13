"""QThread workers keeping recognition and solving off the GUI thread.
Every result is delivered through a Qt signal tagged with the revision it
was computed for; MainWindow / BoardSession discard anything stale."""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from meowdoku import solver as solver_mod
from meowdoku.models import Board
from meowdoku.recognition import pipeline


class ScanWorker(QThread):
    finished_result = Signal(int, object)  # revision, RecognitionResult

    def __init__(self, revision: int, crop_bgr, size_override: Optional[int], templates: dict, parent=None):
        super().__init__(parent)
        self.revision = revision
        self.crop_bgr = crop_bgr
        self.size_override = size_override
        self.templates = templates

    def run(self):
        result = pipeline.recognize(self.crop_bgr, size_override=self.size_override, templates=self.templates)
        self.finished_result.emit(self.revision, result)


class SolveWorker(QThread):
    finished_result = Signal(int, object)  # revision, SolveOutcome

    def __init__(self, revision: int, board: Board, respect_x_marks: bool, time_budget_seconds: float, parent=None):
        super().__init__(parent)
        self.revision = revision
        self.board = board
        self.respect_x_marks = respect_x_marks
        self.time_budget_seconds = time_budget_seconds
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        outcome = solver_mod.solve(
            self.board,
            respect_x_marks=self.respect_x_marks,
            max_solutions=2,
            time_budget_seconds=self.time_budget_seconds,
            cancel_event=self.cancel_event,
        )
        self.finished_result.emit(self.revision, outcome)


class HintWorker(QThread):
    finished_result = Signal(int, object)  # revision, HintResult

    def __init__(self, revision: int, board: Board, respect_x_marks: bool, time_budget_seconds: float, parent=None):
        super().__init__(parent)
        self.revision = revision
        self.board = board
        self.respect_x_marks = respect_x_marks
        self.time_budget_seconds = time_budget_seconds
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        result = solver_mod.find_guaranteed_hint(
            self.board,
            respect_x_marks=self.respect_x_marks,
            time_budget_seconds=self.time_budget_seconds,
            cancel_event=self.cancel_event,
        )
        self.finished_result.emit(self.revision, result)
