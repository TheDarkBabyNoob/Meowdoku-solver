"""Interactive board view: renders the recreated grid with region colors,
visible region borders, row/column labels (row 1 top, column 1 left), and
cat/X/blocked markers, and reports cell clicks for the editor to interpret.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from meowdoku.models import Board, CellState

DEFAULT_CELL_PX = 48
MIN_CELL_PX = 18
MAX_CELL_PX = 96


class BoardView(QWidget):
    cell_clicked = Signal(int, int, Qt.MouseButton)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.board: Optional[Board] = None
        self.solution: Optional[list] = None
        self.revealed_rows: set = set()
        self.show_all_solution = False
        self.hint_cell: Optional[tuple] = None
        self.cell_px = DEFAULT_CELL_PX
        self.setMouseTracking(True)

    @property
    def label_margin(self) -> int:
        return max(22, self.cell_px // 2)

    def set_board(self, board: Optional[Board]):
        self.board = board
        self.solution = None
        self.revealed_rows = set()
        self.show_all_solution = False
        self.hint_cell = None
        self._update_size()
        self.update()

    def set_solution(self, solution: Optional[list]):
        self.solution = solution
        self.revealed_rows = set()
        self.show_all_solution = False
        self.hint_cell = None
        self.update()

    def set_hint_cell(self, cell: Optional[tuple]):
        self.hint_cell = cell
        self.update()

    def reveal_all(self):
        if self.solution:
            self.show_all_solution = True
            self.update()

    def reveal_next(self) -> Optional[tuple]:
        if not self.solution or not self.board:
            return None
        n = self.board.size
        if self.show_all_solution:
            return None
        for r in range(n):
            col = self.solution[r]
            if self.board.cell_states[r][col] == CellState.CAT_CONFIRMED:
                continue
            if r in self.revealed_rows:
                continue
            self.revealed_rows.add(r)
            return (r, col)
        return None

    def set_zoom(self, cell_px: int):
        self.cell_px = max(MIN_CELL_PX, min(MAX_CELL_PX, cell_px))
        self._update_size()
        self.update()

    def _update_size(self):
        if not self.board:
            self.setMinimumSize(200, 200)
            return
        n = self.board.size
        side = n * self.cell_px + self.label_margin
        self.setMinimumSize(side, side)
        self.resize(side, side)

    def _cell_rect(self, row: int, col: int) -> QRect:
        m = self.label_margin
        return QRect(m + col * self.cell_px, m + row * self.cell_px, self.cell_px, self.cell_px)

    def cell_at(self, x: float, y: float):
        if not self.board:
            return None
        m = self.label_margin
        col = int((x - m) // self.cell_px)
        row = int((y - m) // self.cell_px)
        n = self.board.size
        if 0 <= row < n and 0 <= col < n:
            return row, col
        return None

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()
        cell = self.cell_at(pos.x(), pos.y())
        if cell is not None:
            self.cell_clicked.emit(cell[0], cell[1], event.button())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if not self.board:
            return
        n = self.board.size
        m = self.label_margin

        font = QFont()
        font.setPointSize(max(8, self.cell_px // 5))
        painter.setFont(font)
        painter.setPen(QPen(QColor("#dddddd")))
        for i in range(n):
            painter.drawText(QRect(m + i * self.cell_px, 0, self.cell_px, m), Qt.AlignmentFlag.AlignCenter, str(i + 1))
            painter.drawText(QRect(0, m + i * self.cell_px, m, self.cell_px), Qt.AlignmentFlag.AlignCenter, str(i + 1))

        for r in range(n):
            for c in range(n):
                rect = self._cell_rect(r, c)
                region_id = self.board.region_ids[r][c]
                color = self.board.region_colors.get(region_id, (150, 150, 150))
                painter.fillRect(rect, QColor(*color))

                state = self.board.cell_states[r][c]
                if state == CellState.CAT_CONFIRMED:
                    self._draw_cat(painter, rect, uncertain=False)
                elif state == CellState.CAT_UNCERTAIN:
                    self._draw_cat(painter, rect, uncertain=True)
                elif state == CellState.X_MARK:
                    self._draw_x(painter, rect, QColor(90, 90, 90), width=3)
                elif state == CellState.BLOCKED:
                    painter.fillRect(rect.adjusted(3, 3, -3, -3), QColor(30, 30, 30, 190))
                    self._draw_x(painter, rect, QColor(230, 70, 70), width=4)

        if self.solution and self.board:
            for r in range(n):
                col = self.solution[r]
                if self.board.cell_states[r][col] == CellState.CAT_CONFIRMED:
                    continue
                if self.show_all_solution or r in self.revealed_rows:
                    self._draw_recommendation(painter, self._cell_rect(r, col))

        if self.hint_cell is not None:
            self._draw_hint(painter, self._cell_rect(*self.hint_cell))

        pen = QPen(QColor("#000000"), 1)
        painter.setPen(pen)
        for r in range(n):
            for c in range(n):
                painter.drawRect(self._cell_rect(r, c))

        thick_pen = QPen(QColor("#000000"), 3)
        painter.setPen(thick_pen)
        for r in range(n):
            for c in range(n):
                rect = self._cell_rect(r, c)
                region_id = self.board.region_ids[r][c]
                if c == n - 1 or self.board.region_ids[r][c + 1] != region_id:
                    painter.drawLine(rect.topRight(), rect.bottomRight())
                if r == n - 1 or self.board.region_ids[r + 1][c] != region_id:
                    painter.drawLine(rect.bottomLeft(), rect.bottomRight())
                if c == 0 or self.board.region_ids[r][c - 1] != region_id:
                    painter.drawLine(rect.topLeft(), rect.bottomLeft())
                if r == 0 or self.board.region_ids[r - 1][c] != region_id:
                    painter.drawLine(rect.topLeft(), rect.topRight())

    def _draw_cat(self, painter: QPainter, rect: QRect, uncertain: bool):
        fill = QColor(255, 170, 40, 150 if uncertain else 255)
        painter.setBrush(fill)
        pen_color = QColor(150, 110, 0) if uncertain else QColor(0, 0, 0)
        pen = QPen(pen_color, 2)
        if uncertain:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        inset = rect.adjusted(5, 5, -5, -5)
        painter.drawEllipse(inset)

    def _draw_x(self, painter: QPainter, rect: QRect, color: QColor, width: int = 3):
        painter.setPen(QPen(color, width))
        inset = rect.adjusted(9, 9, -9, -9)
        painter.drawLine(inset.topLeft(), inset.bottomRight())
        painter.drawLine(inset.topRight(), inset.bottomLeft())

    def _draw_recommendation(self, painter: QPainter, rect: QRect):
        painter.setPen(QPen(QColor(60, 230, 100), 4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect.adjusted(3, 3, -3, -3))

    def _draw_hint(self, painter: QPainter, rect: QRect):
        painter.setPen(QPen(QColor(255, 215, 0), 4, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(2, 2, -2, -2))
