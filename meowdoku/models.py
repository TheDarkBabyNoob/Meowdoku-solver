"""Core data models shared across capture, recognition, solver, and GUI code.

This module has no dependency on Qt, OpenCV, or mss so it can be imported
(and unit tested) in any context.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

MIN_BOARD_SIZE = 2
MAX_BOARD_SIZE = 20


class CellState(Enum):
    """The state of a single board cell, independent of solver semantics.

    CAT_UNCERTAIN exists so recognition can flag a detection that is not
    confident without silently treating it as either a hard constraint or an
    empty cell. It must be resolved (confirmed or corrected) by the user or
    explicitly left as-is before it is used by the solver, at which point it
    is treated the same as EMPTY (i.e. not a hard placement) until confirmed.
    """

    EMPTY = "empty"
    CAT_CONFIRMED = "cat_confirmed"
    CAT_UNCERTAIN = "cat_uncertain"
    X_MARK = "x_mark"
    BLOCKED = "blocked"


class SolveStatus(Enum):
    READY = "ready"
    SCANNING = "scanning"
    NEEDS_REVIEW = "needs_review"
    UNIQUE_SOLUTION = "unique_solution"
    MULTIPLE_SOLUTIONS = "multiple_solutions"
    NO_SOLUTION = "no_solution"
    SOLUTION_FOUND_UNIQUENESS_UNVERIFIED = "solution_found_uniqueness_unverified"
    SEARCH_INCOMPLETE = "search_incomplete"
    MODEL_UNSUPPORTED = "model_unsupported"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class MonitorInfo:
    """A display's geometry, in capture-backend (points/logical) coordinates.

    ``index`` follows the capture backend's own numbering (mss uses 1-based
    indices with 0 reserved for the "all monitors" virtual bounding box).
    left/top may be negative for monitors positioned above or to the left of
    the primary display.
    """

    index: int
    left: int
    top: int
    width: int
    height: int
    name: str = ""

    def contains_point(self, x: int, y: int) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height

    def geometry_matches(self, other: "MonitorInfo") -> bool:
        return (
            self.left == other.left
            and self.top == other.top
            and self.width == other.width
            and self.height == other.height
        )


@dataclass(frozen=True)
class SelectionRect:
    """A saved screen-area selection, in absolute capture-backend coordinates
    (points, not pixels -- see meowdoku.coords for the pixel mapping)."""

    monitor_index: int
    left: int
    top: int
    width: int
    height: int
    saved_monitor_geometry: Optional[MonitorInfo] = None

    def as_mss_dict(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    def to_json(self) -> dict:
        d = {
            "monitor_index": self.monitor_index,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }
        if self.saved_monitor_geometry is not None:
            m = self.saved_monitor_geometry
            d["saved_monitor_geometry"] = {
                "index": m.index,
                "left": m.left,
                "top": m.top,
                "width": m.width,
                "height": m.height,
                "name": m.name,
            }
        return d

    @staticmethod
    def from_json(d: dict) -> "SelectionRect":
        geom = None
        if d.get("saved_monitor_geometry"):
            g = d["saved_monitor_geometry"]
            geom = MonitorInfo(
                index=g["index"], left=g["left"], top=g["top"],
                width=g["width"], height=g["height"], name=g.get("name", ""),
            )
        return SelectionRect(
            monitor_index=d["monitor_index"], left=d["left"], top=d["top"],
            width=d["width"], height=d["height"], saved_monitor_geometry=geom,
        )


@dataclass
class Board:
    """The logical Meowdoku puzzle model: an N x N grid of region ids and
    per-cell states. region_ids need not be 0-indexed or contiguous; the
    solver normalizes them. Two boards are considered "the same puzzle" by
    the GUI only after explicit region-label-normalized comparison -- Board
    equality here is structural, not puzzle-identity.
    """

    size: int
    region_ids: list  # size x size, arbitrary hashable region id per cell
    region_colors: dict  # region_id -> (r, g, b)
    cell_states: list  # size x size of CellState
    revision: int = 0

    def region_count(self) -> int:
        return len(set(v for row in self.region_ids for v in row))

    def cells_with_state(self, state: CellState) -> list:
        return [
            (r, c)
            for r in range(self.size)
            for c in range(self.size)
            if self.cell_states[r][c] == state
        ]

    def confirmed_cats(self) -> list:
        return self.cells_with_state(CellState.CAT_CONFIRMED)

    def uncertain_cats(self) -> list:
        return self.cells_with_state(CellState.CAT_UNCERTAIN)

    def blocked_cells(self) -> list:
        return self.cells_with_state(CellState.BLOCKED)

    def x_marks(self) -> list:
        return self.cells_with_state(CellState.X_MARK)

    def with_cell_state(self, row: int, col: int, state: CellState) -> "Board":
        """Return a new Board with a single cell's state replaced. Does not
        mutate self; used by hint-proving and editor undo stacks."""
        new_states = [list(r) for r in self.cell_states]
        new_states[row][col] = state
        return Board(
            size=self.size,
            region_ids=[list(r) for r in self.region_ids],
            region_colors=dict(self.region_colors),
            cell_states=new_states,
            revision=self.revision,
        )

    def clone(self) -> "Board":
        return copy.deepcopy(self)

    @staticmethod
    def empty(size: int) -> "Board":
        return Board(
            size=size,
            region_ids=[[0] * size for _ in range(size)],
            region_colors={0: (200, 200, 200)},
            cell_states=[[CellState.EMPTY] * size for _ in range(size)],
        )

    def to_json(self) -> dict:
        return {
            "size": self.size,
            "region_ids": self.region_ids,
            "region_colors": {str(k): list(v) for k, v in self.region_colors.items()},
            "cell_states": [[s.value for s in row] for row in self.cell_states],
            "revision": self.revision,
        }

    @staticmethod
    def from_json(d: dict) -> "Board":
        return Board(
            size=d["size"],
            region_ids=[list(row) for row in d["region_ids"]],
            region_colors={int(k): tuple(v) for k, v in d["region_colors"].items()},
            cell_states=[[CellState(v) for v in row] for row in d["cell_states"]],
            revision=d.get("revision", 0),
        )


@dataclass
class GridGeometry:
    """Pixel-space geometry of the detected grid within the recognition crop.

    x_edges/y_edges have length size+1 and are in crop-local pixel
    coordinates (origin at the crop's top-left, row 1 / column 1 at index 0).
    ``confidence`` is a heuristic score in [0, 1], not a calibrated
    probability.
    """

    size: int
    x_edges: list
    y_edges: list
    confidence: float = 0.0

    def cell_box(self, row: int, col: int) -> tuple:
        x0, x1 = self.x_edges[col], self.x_edges[col + 1]
        y0, y1 = self.y_edges[row], self.y_edges[row + 1]
        return (x0, y0, x1, y1)


@dataclass
class CellConfidence:
    region_confidence: float = 1.0
    foreground_confidence: float = 1.0
    foreground_kind: Optional[str] = None  # "cat" | "x" | None


@dataclass
class RecognitionResult:
    """Structured output of the recognition pipeline. Never presented as an
    authoritative board without checking ``needs_review``."""

    success: bool
    failure_reason: Optional[str] = None
    board: Optional[Board] = None
    grid: Optional[GridGeometry] = None
    cell_confidence: Optional[list] = None
    needs_review: bool = False
    review_cells: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    crop_image: object = None
    detected_at: float = field(default_factory=time.time)


@dataclass
class SolveOutcome:
    status: SolveStatus
    solutions: list = field(default_factory=list)  # list of list[int], column per row
    elapsed_seconds: float = 0.0
    nodes_explored: int = 0
    message: str = ""


@dataclass
class HintResult:
    found: bool
    row: Optional[int] = None
    col: Optional[int] = None
    explanation: str = ""


@dataclass
class CalibrationTemplate:
    kind: str  # "cat" | "x"
    patch_gray: object  # small normalized grayscale numpy array
    source_cell_px: int
