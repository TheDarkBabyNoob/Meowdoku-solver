"""Main application window: wires screen selection, capture, recognition,
the board editor, and the solver together around a BoardSession so that
stale worker results (from a superseded scan or edit) are never displayed.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from meowdoku import persistence
from meowdoku import solver as solver_mod
from meowdoku.capture.base import CaptureError
from meowdoku.capture.mss_backend import MSSCaptureBackend, is_probably_blank
from meowdoku.gui.board_view import BoardView
from meowdoku.gui.overlay_select import SelectionOverlay
from meowdoku.gui.palette import REGION_PALETTE, color_for_new_region
from meowdoku.gui.workers import HintWorker, ScanWorker, SolveWorker
from meowdoku.models import (
    MAX_BOARD_SIZE, MIN_BOARD_SIZE, Board, CellState, HintResult, MonitorInfo,
    RecognitionResult, SelectionRect, SolveOutcome, SolveStatus,
)
from meowdoku.recognition import foreground as foreground_mod
from meowdoku.session import BoardSession

STATUS_TEXT = {
    SolveStatus.READY: "Ready",
    SolveStatus.SCANNING: "Scanning...",
    SolveStatus.NEEDS_REVIEW: "Needs Review",
    SolveStatus.UNIQUE_SOLUTION: "Unique Solution",
    SolveStatus.MULTIPLE_SOLUTIONS: "Multiple Solutions",
    SolveStatus.NO_SOLUTION: "No Solution",
    SolveStatus.SOLUTION_FOUND_UNIQUENESS_UNVERIFIED: "Solution Found, Uniqueness Unverified",
    SolveStatus.SEARCH_INCOMPLETE: "Search Incomplete",
    SolveStatus.MODEL_UNSUPPORTED: "Board Model Unsupported",
    SolveStatus.CANCELLED: "Cancelled",
}


class EditMode(Enum):
    CYCLE_STATE = "cycle_state"
    PAINT_REGION = "paint_region"
    MERGE_REGIONS = "merge_regions"
    MARK_PLACED = "mark_placed"


def bgr_to_qpixmap(bgr: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    h, w, ch = rgb.shape
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Meowdoku Companion")
        self.resize(1180, 760)

        self.capture_backend = MSSCaptureBackend()
        self.session = BoardSession()
        self.templates = persistence.load_calibration_templates()
        self.selection: Optional[SelectionRect] = persistence.load_selection()
        self.board_size_override: Optional[int] = persistence.load_board_size_override()
        self.respect_x_marks: bool = persistence.load_respect_x_marks()
        self.time_budget_seconds: float = persistence.load_time_budget_seconds()
        self.last_crop_bgr: Optional[np.ndarray] = None
        self.undo_stack: list = []
        self.edit_mode = EditMode.CYCLE_STATE
        self.selected_region_id: Optional[int] = None
        self.merge_first_cell: Optional[tuple] = None
        self._pending_calibration_kind: Optional[str] = None
        self._restore_visible_after_capture = False

        self._scan_worker: Optional[ScanWorker] = None
        self._solve_worker: Optional[SolveWorker] = None
        self._hint_worker: Optional[HintWorker] = None
        # A superseded worker (from a rescan/edit that happened before the
        # old one finished) must stay referenced until it actually
        # completes -- overwriting _scan_worker/_solve_worker/_hint_worker
        # alone would drop the only Python reference to a QThread that may
        # still be running, which is undefined/unsafe in PySide6.
        self._active_workers: set = set()
        self._overlays: list = []

        self._build_ui()
        self._update_selection_label()
        self._set_status(SolveStatus.READY, "Ready. Select the mirrored board's screen area to begin.")

        if self.selection is not None and not self._selection_still_valid():
            self._show_warning_banner(
                "The saved screen selection no longer matches your current display "
                "arrangement. Use Reselect Area before scanning."
            )

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        self.btn_select_area = QPushButton("Select Screen Area")
        self.btn_reselect_area = QPushButton("Reselect Area")
        self.btn_scan_solve = QPushButton("Scan && Solve")
        self.btn_import = QPushButton("Import Screenshot")
        self.btn_edit_toggle = QPushButton("Edit Board")
        self.btn_edit_toggle.setCheckable(True)
        self.btn_show_all = QPushButton("Show All Cats")
        self.btn_next_cat = QPushButton("Next Cat")
        self.btn_next_hint = QPushButton("Next Hint")

        for b in (
            self.btn_select_area, self.btn_reselect_area, self.btn_scan_solve,
            self.btn_import, self.btn_edit_toggle, self.btn_show_all,
            self.btn_next_cat, self.btn_next_hint,
        ):
            toolbar.addWidget(b)
        toolbar.addStretch(1)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-weight: bold; padding: 4px 8px;")
        toolbar.addWidget(self.status_label)
        root.addLayout(toolbar)

        self.selection_label = QLabel("No area selected yet.")
        root.addWidget(self.selection_label)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #b35c00;")
        root.addWidget(self.warning_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("Captured crop"))
        self.crop_scroll = QScrollArea()
        self.crop_label = QLabel("(no capture yet)")
        self.crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop_scroll.setWidget(self.crop_label)
        self.crop_scroll.setWidgetResizable(True)
        left_layout.addWidget(self.crop_scroll, 1)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        board_header = QHBoxLayout()
        board_header.addWidget(QLabel("Recreated board (row 1 top, column 1 left)"))
        board_header.addStretch(1)
        board_header.addWidget(QLabel("Zoom"))
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(18, 96)
        self.zoom_spin.setValue(48)
        self.zoom_spin.valueChanged.connect(lambda v: self.board_view.set_zoom(v))
        board_header.addWidget(self.zoom_spin)
        right_layout.addLayout(board_header)

        self.board_scroll = QScrollArea()
        self.board_view = BoardView()
        self.board_view.cell_clicked.connect(self._on_board_cell_clicked)
        self.board_scroll.setWidget(self.board_view)
        self.board_scroll.setWidgetResizable(False)
        right_layout.addWidget(self.board_scroll, 1)
        splitter.addWidget(right_panel)
        splitter.setSizes([420, 700])

        self.editor_panel = self._build_editor_panel()
        root.addWidget(self.editor_panel)
        self.editor_panel.setVisible(False)

        bottom = QHBoxLayout()
        coord_col = QVBoxLayout()
        coord_col.addWidget(QLabel("Recommended placements (copyable):"))
        self.coord_list_edit = QPlainTextEdit()
        self.coord_list_edit.setReadOnly(True)
        self.coord_list_edit.setMaximumHeight(120)
        coord_col.addWidget(self.coord_list_edit)
        bottom.addLayout(coord_col, 1)

        hint_col = QVBoxLayout()
        hint_col.addWidget(QLabel("Hint explanation:"))
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        hint_col.addWidget(self.hint_label)
        hint_col.addStretch(1)
        bottom.addLayout(hint_col, 1)
        root.addLayout(bottom)

        self.statusBar().showMessage("Ready.")

        self.btn_select_area.clicked.connect(self.on_select_area_clicked)
        self.btn_reselect_area.clicked.connect(self.on_select_area_clicked)
        self.btn_scan_solve.clicked.connect(self.on_scan_and_solve_clicked)
        self.btn_import.clicked.connect(self.on_import_screenshot_clicked)
        self.btn_edit_toggle.toggled.connect(self.editor_panel.setVisible)
        self.btn_show_all.clicked.connect(self.on_show_all_cats_clicked)
        self.btn_next_cat.clicked.connect(self.on_next_cat_clicked)
        self.btn_next_hint.clicked.connect(self.on_next_hint_clicked)

    def _build_editor_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Edit mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Set cat / X / blocked (click to cycle)", EditMode.CYCLE_STATE)
        self.mode_combo.addItem("Paint region", EditMode.PAINT_REGION)
        self.mode_combo.addItem("Merge regions (click two cells)", EditMode.MERGE_REGIONS)
        self.mode_combo.addItem("Mark placed (on recommended cell)", EditMode.MARK_PLACED)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        row1.addWidget(self.mode_combo)

        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(self.on_undo_clicked)
        row1.addWidget(self.undo_btn)

        self.change_size_btn = QPushButton("Change Grid Size...")
        self.change_size_btn.clicked.connect(self.on_change_grid_size_clicked)
        row1.addWidget(self.change_size_btn)

        self.manual_entry_btn = QPushButton("Manual Empty Board...")
        self.manual_entry_btn.clicked.connect(self.on_manual_entry_clicked)
        row1.addWidget(self.manual_entry_btn)

        self.export_debug_btn = QPushButton("Export Debug Bundle...")
        self.export_debug_btn.clicked.connect(self.on_export_debug_clicked)
        row1.addWidget(self.export_debug_btn)
        row1.addStretch(1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Region palette:"))
        self.region_list = QListWidget()
        self.region_list.setFlow(QListWidget.Flow.LeftToRight)
        self.region_list.setFixedHeight(46)
        self.region_list.itemClicked.connect(self._on_region_palette_clicked)
        row2.addWidget(self.region_list, 1)
        self.new_region_btn = QPushButton("+ New Region")
        self.new_region_btn.clicked.connect(self.on_new_region_clicked)
        row2.addWidget(self.new_region_btn)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.calibrate_cat_btn = QPushButton("Calibrate Cat Template...")
        self.calibrate_cat_btn.clicked.connect(lambda: self._arm_calibration("cat"))
        row3.addWidget(self.calibrate_cat_btn)
        self.calibrate_x_btn = QPushButton("Calibrate X Template...")
        self.calibrate_x_btn.clicked.connect(lambda: self._arm_calibration("x"))
        row3.addWidget(self.calibrate_x_btn)

        self.respect_x_checkbox = QCheckBox("Respect X Marks as exclusions")
        self.respect_x_checkbox.setChecked(self.respect_x_marks)
        self.respect_x_checkbox.toggled.connect(self._on_respect_x_toggled)
        row3.addWidget(self.respect_x_checkbox)

        row3.addWidget(QLabel("Time budget (s):"))
        self.time_budget_spin = QDoubleSpinBox()
        self.time_budget_spin.setRange(0.5, 60.0)
        self.time_budget_spin.setSingleStep(0.5)
        self.time_budget_spin.setValue(self.time_budget_seconds)
        self.time_budget_spin.valueChanged.connect(self._on_time_budget_changed)
        row3.addWidget(self.time_budget_spin)

        self.always_on_top_checkbox = QCheckBox("Always on top (compact)")
        self.always_on_top_checkbox.toggled.connect(self._on_always_on_top_toggled)
        row3.addWidget(self.always_on_top_checkbox)
        row3.addStretch(1)
        layout.addLayout(row3)

        return panel

    # ------------------------------------------------------------- status

    def _set_status(self, status: SolveStatus, detail: str = ""):
        self.status_label.setText(STATUS_TEXT.get(status, status.value))
        if detail:
            self.statusBar().showMessage(detail, 8000)

    def _show_warning_banner(self, text: str):
        self.warning_label.setText(text)

    def _show_warnings(self, warnings: list):
        self._show_warning_banner(" | ".join(warnings) if warnings else "")

    # ---------------------------------------------------------- selection

    def _list_monitors_safe(self):
        try:
            return self.capture_backend.list_monitors()
        except CaptureError:
            return []

    def _selection_still_valid(self) -> bool:
        if self.selection is None:
            return False
        monitors = self._list_monitors_safe()
        current = next((m for m in monitors if m.index == self.selection.monitor_index), None)
        saved = self.selection.saved_monitor_geometry
        if current is None or saved is None:
            return False
        return current.geometry_matches(saved)

    def _update_selection_label(self):
        if self.selection is None:
            self.selection_label.setText("No area selected yet.")
            return
        s = self.selection
        self.selection_label.setText(
            f"Selected area: monitor {s.monitor_index}, {s.width}x{s.height} at ({s.left}, {s.top})"
        )

    def on_select_area_clicked(self):
        self._close_overlays()
        self._overlays = []
        for screen in QApplication.screens():
            overlay = SelectionOverlay(screen)
            overlay.selection_made.connect(self._on_overlay_selection_made)
            overlay.cancelled.connect(self._on_overlay_cancelled)
            self._overlays.append(overlay)
        for overlay in self._overlays:
            overlay.start()

    def _close_overlays(self):
        for overlay in self._overlays:
            overlay.close()
            overlay.deleteLater()
        self._overlays = []

    def _on_overlay_cancelled(self):
        self._close_overlays()

    def _match_monitor_for_screen(self, screen, monitors) -> Optional[MonitorInfo]:
        geom = screen.geometry()
        for m in monitors:
            if m.left == geom.left() and m.top == geom.top() and m.width == geom.width() and m.height == geom.height():
                return m
        if not monitors:
            return None
        return min(monitors, key=lambda m: (m.left - geom.left()) ** 2 + (m.top - geom.top()) ** 2)

    def _on_overlay_selection_made(self, rect: QRect, was_clamped: bool):
        self._close_overlays()
        screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
        monitors = self._list_monitors_safe()
        monitor = self._match_monitor_for_screen(screen, monitors) if screen else None
        if monitor is None:
            QMessageBox.warning(self, "Could not identify display", "Could not match the selection to a display for capture.")
            return
        self.selection = SelectionRect(
            monitor_index=monitor.index, left=rect.left(), top=rect.top(),
            width=rect.width(), height=rect.height(), saved_monitor_geometry=monitor,
        )
        persistence.save_selection(self.selection)
        self._update_selection_label()
        self._show_warning_banner("")
        if was_clamped:
            QMessageBox.information(
                self, "Selection restricted to one monitor",
                "Your drag crossed into another display. The selection was clamped "
                "to the monitor where you started dragging.",
            )

    # ------------------------------------------------------------ capture

    def on_scan_and_solve_clicked(self):
        if self.selection is None:
            QMessageBox.information(self, "No area selected", "Use Select Screen Area first.")
            return
        if not self._selection_still_valid():
            QMessageBox.warning(
                self, "Display changed",
                "The display arrangement has changed since this area was selected. Use Reselect Area.",
            )
            return
        self._begin_hidden_capture(self._do_scan_capture)

    def _begin_hidden_capture(self, capture_fn):
        self._close_overlays()
        self._restore_visible_after_capture = self.isVisible()
        if self._restore_visible_after_capture:
            self.hide()
        QTimer.singleShot(160, lambda: self._run_capture_then_restore(capture_fn))

    def _run_capture_then_restore(self, capture_fn):
        try:
            capture_fn()
        finally:
            if self._restore_visible_after_capture:
                self.show()
                self.raise_()
                self.activateWindow()

    def _do_scan_capture(self):
        assert self.selection is not None
        revision = self.session.start_new_scan()
        self._set_status(SolveStatus.SCANNING, "Capturing...")
        try:
            rect = self.selection.as_mss_dict()
            image = self.capture_backend.grab_region(**rect)
        except CaptureError as exc:
            self._handle_capture_error(exc)
            return
        if is_probably_blank(image):
            self._show_warning_banner(
                "Capture looks blank. If this repeats, check System Settings > "
                "Privacy & Security > Screen Recording."
            )
        self.last_crop_bgr = image
        self._update_crop_preview(image)
        self._launch_scan_worker(revision, image)

    def _handle_capture_error(self, exc: CaptureError):
        if exc.reason == "permission_denied":
            self._set_status(SolveStatus.NEEDS_REVIEW, "Screen Recording permission required.")
            QMessageBox.critical(self, "Screen Recording permission needed", exc.message)
        elif exc.reason == "invalid_region":
            self._set_status(SolveStatus.NEEDS_REVIEW, exc.message)
            QMessageBox.warning(self, "Invalid selection", exc.message + "\nUse Reselect Area.")
        else:
            self._set_status(SolveStatus.NEEDS_REVIEW, exc.message)
            QMessageBox.warning(self, "Capture failed", exc.message)

    def _update_crop_preview(self, image: np.ndarray):
        pixmap = bgr_to_qpixmap(image)
        self.crop_label.setPixmap(pixmap)
        self.crop_label.resize(pixmap.size())

    def on_import_screenshot_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Screenshot", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            QMessageBox.warning(self, "Import failed", "Could not read that image file.")
            return
        revision = self.session.start_new_scan()
        self.last_crop_bgr = image
        self._update_crop_preview(image)
        self._launch_scan_worker(revision, image)

    # ------------------------------------------------------------ workers

    def _track_worker(self, worker):
        """Keep a live reference to a worker until its QThread actually
        finishes, even if a newer worker supersedes it as "the current one"
        in self._scan_worker/_solve_worker/_hint_worker before then."""
        self._active_workers.add(worker)
        worker.finished.connect(lambda w=worker: self._active_workers.discard(w))

    # --------------------------------------------------------- recognition

    def _launch_scan_worker(self, revision: int, image: np.ndarray):
        worker = ScanWorker(revision, image, self.board_size_override, self.templates)
        worker.finished_result.connect(self._on_scan_result)
        self._track_worker(worker)
        self._scan_worker = worker
        worker.start()

    def _on_scan_result(self, revision: int, result: RecognitionResult):
        if not self.session.accept_recognition_result(revision, result):
            return
        self.undo_stack = []
        self.merge_first_cell = None
        self.hint_label.setText("")

        if not result.success:
            self._set_status(SolveStatus.NEEDS_REVIEW, f"Recognition failed: {result.failure_reason}")
            self._show_warnings(result.warnings)
            # Clear the session board too, not just the visible board_view --
            # otherwise a stray Next Hint click would silently run against
            # stale board data the user can no longer see on screen.
            self.session.board = None
            self.board_view.set_board(None)
            self._update_coordinate_list(None)
            return

        self.board_view.set_board(result.board)
        self._refresh_region_palette_list()
        self._update_coordinate_list(None)
        self._show_warnings(result.warnings)

        if result.needs_review:
            self._set_status(
                SolveStatus.NEEDS_REVIEW,
                "Recognition needs review before an authoritative solve. Correct flagged cells in Edit Board, then it will solve automatically.",
            )
        else:
            self._launch_solve(revision)

    # -------------------------------------------------------------- solve

    def _launch_solve(self, revision: int):
        board = self.session.board
        if board is None:
            return
        self._set_status(SolveStatus.SCANNING, "Solving...")
        worker = SolveWorker(revision, board, self.respect_x_marks, self.time_budget_seconds)
        worker.finished_result.connect(self._on_solve_result)
        self._track_worker(worker)
        self._solve_worker = worker
        worker.start()

    def _on_solve_result(self, revision: int, outcome: SolveOutcome):
        if not self.session.accept_solve_result(revision, outcome):
            return
        self._apply_solve_outcome(outcome)

    def _apply_solve_outcome(self, outcome: SolveOutcome):
        self._set_status(outcome.status, outcome.message)
        if outcome.solutions:
            self.board_view.set_solution(outcome.solutions[0])
            self._update_coordinate_list(outcome.solutions[0])
            if outcome.status == SolveStatus.MULTIPLE_SOLUTIONS:
                self._show_warning_banner(
                    "Multiple solutions exist; the displayed arrangement is only one possible solution, not necessarily the game's intended one."
                )
        else:
            self.board_view.set_solution(None)
            self._update_coordinate_list(None)

    def _update_coordinate_list(self, solution: Optional[list]):
        board = self.session.board
        if not solution or not board:
            self.coord_list_edit.setPlainText("")
            return
        lines = []
        for r, c in enumerate(solution):
            tag = " (existing)" if board.cell_states[r][c] == CellState.CAT_CONFIRMED else ""
            lines.append(f"R{r + 1} C{c + 1}{tag}")
        self.coord_list_edit.setPlainText("\n".join(lines))

    # --------------------------------------------------------- reveal/hint

    def on_show_all_cats_clicked(self):
        self.board_view.reveal_all()

    def on_next_cat_clicked(self):
        result = self.board_view.reveal_next()
        if result is None:
            self.statusBar().showMessage("No more cats to reveal (or no solution is currently available).", 5000)

    def on_next_hint_clicked(self):
        board = self.session.board
        if board is None:
            return
        revision = self.session.revision
        self.statusBar().showMessage("Proving a guaranteed placement...", 5000)
        worker = HintWorker(revision, board, self.respect_x_marks, self.time_budget_seconds)
        worker.finished_result.connect(self._on_hint_result)
        self._track_worker(worker)
        self._hint_worker = worker
        worker.start()

    def _on_hint_result(self, revision: int, hint: HintResult):
        if revision != self.session.revision:
            return
        if hint.found and hint.row is not None and hint.col is not None:
            self.board_view.set_hint_cell((hint.row, hint.col))
            self.hint_label.setText(hint.explanation)
        else:
            self.board_view.set_hint_cell(None)
            self.hint_label.setText(hint.explanation)

    # ----------------------------------------------------------- editing

    def _on_mode_changed(self, index: int):
        self.edit_mode = self.mode_combo.itemData(index)
        self.merge_first_cell = None

    def _refresh_region_palette_list(self):
        self.region_list.clear()
        board = self.session.board
        if not board:
            return
        for region_id in sorted(board.region_colors.keys()):
            color = board.region_colors[region_id]
            item = QListWidgetItem(f"#{region_id}")
            item.setData(Qt.ItemDataRole.UserRole, region_id)
            item.setBackground(QColor(*color))
            self.region_list.addItem(item)
        if self.selected_region_id is None and board.region_colors:
            self.selected_region_id = sorted(board.region_colors.keys())[0]

    def _on_region_palette_clicked(self, item: QListWidgetItem):
        self.selected_region_id = item.data(Qt.ItemDataRole.UserRole)

    def on_new_region_clicked(self):
        board = self.session.board
        if not board:
            return
        new_id = (max(board.region_colors.keys()) + 1) if board.region_colors else 0
        board.region_colors[new_id] = color_for_new_region(board.region_colors)
        self.selected_region_id = new_id
        self._refresh_region_palette_list()

    def _push_undo(self):
        if self.session.board is not None:
            self.undo_stack.append(self.session.board.clone())
            if len(self.undo_stack) > 50:
                self.undo_stack.pop(0)

    def on_undo_clicked(self):
        if not self.undo_stack:
            return
        prev = self.undo_stack.pop()
        revision = self.session.start_edit()
        prev.revision = revision
        self.session.board = prev
        self.board_view.set_board(prev)
        self._refresh_region_palette_list()
        self._launch_solve(revision)

    def _after_edit(self):
        board = self.session.board
        if board is None:
            return
        revision = self.session.start_edit()
        board.revision = revision
        self.board_view.set_board(board)
        self._refresh_region_palette_list()
        self._launch_solve(revision)

    def _arm_calibration(self, kind: str):
        if self.last_crop_bgr is None or not self.session.last_recognition or not self.session.last_recognition.grid:
            QMessageBox.information(self, "No crop available", "Scan or import a board first, then calibrate.")
            return
        self._pending_calibration_kind = kind
        self.statusBar().showMessage(f"Click a cell containing a{'n' if kind == 'x' else ''} {kind} to calibrate.", 6000)

    def _on_board_cell_clicked(self, row: int, col: int, button):
        board = self.session.board
        if board is None:
            return

        if self._pending_calibration_kind is not None:
            grid = self.session.last_recognition.grid if self.session.last_recognition else None
            if grid is not None and self.last_crop_bgr is not None:
                box = grid.cell_box(row, col)
                template = foreground_mod.make_calibration_template(self.last_crop_bgr, box, self._pending_calibration_kind)
                persistence.save_calibration_template(template)
                self.templates = persistence.load_calibration_templates()
                self.statusBar().showMessage(
                    f"Calibrated {self._pending_calibration_kind} template from R{row + 1} C{col + 1}.", 5000,
                )
            self._pending_calibration_kind = None
            return

        if self.edit_mode == EditMode.PAINT_REGION:
            if self.selected_region_id is None:
                return
            self._push_undo()
            board.region_ids[row][col] = self.selected_region_id
            self._after_edit()

        elif self.edit_mode == EditMode.MERGE_REGIONS:
            if self.merge_first_cell is None:
                self.merge_first_cell = (row, col)
                self.statusBar().showMessage(f"Merge: selected R{row + 1} C{col + 1}. Click the region to merge it into.", 6000)
            else:
                self._push_undo()
                r1, c1 = self.merge_first_cell
                source_region = board.region_ids[r1][c1]
                target_region = board.region_ids[row][col]
                for rr in range(board.size):
                    for cc in range(board.size):
                        if board.region_ids[rr][cc] == source_region:
                            board.region_ids[rr][cc] = target_region
                if source_region in board.region_colors and source_region != target_region:
                    del board.region_colors[source_region]
                self.merge_first_cell = None
                self._after_edit()

        elif self.edit_mode == EditMode.MARK_PLACED:
            sol = self.board_view.solution
            if sol and 0 <= row < len(sol) and sol[row] == col:
                self._push_undo()
                board.cell_states[row][col] = CellState.CAT_CONFIRMED
                self._after_edit()
            else:
                self.statusBar().showMessage("Mark Placed only applies to a currently recommended cell.", 4000)

        else:  # CYCLE_STATE
            self._push_undo()
            current = board.cell_states[row][col]
            if current == CellState.CAT_UNCERTAIN:
                board.cell_states[row][col] = (
                    CellState.EMPTY if button == Qt.MouseButton.RightButton else CellState.CAT_CONFIRMED
                )
            else:
                forward = [CellState.EMPTY, CellState.CAT_CONFIRMED, CellState.X_MARK, CellState.BLOCKED]
                backward = [CellState.EMPTY, CellState.BLOCKED, CellState.X_MARK, CellState.CAT_CONFIRMED]
                order = backward if button == Qt.MouseButton.RightButton else forward
                idx = order.index(current) if current in order else 0
                board.cell_states[row][col] = order[(idx + 1) % len(order)]
            self._after_edit()

    def on_change_grid_size_clicked(self):
        current = self.session.board.size if self.session.board else (self.board_size_override or 6)
        size, ok = QInputDialog.getInt(
            self, "Board size", f"Number of rows/columns ({MIN_BOARD_SIZE}-{MAX_BOARD_SIZE}):",
            current, MIN_BOARD_SIZE, MAX_BOARD_SIZE,
        )
        if not ok:
            return
        self.board_size_override = size
        persistence.save_board_size_override(size)
        revision = self.session.start_new_scan()
        if self.last_crop_bgr is not None:
            self._launch_scan_worker(revision, self.last_crop_bgr)
        else:
            board = Board.empty(size)
            board.revision = revision
            self.session.board = board
            self.board_view.set_board(board)
            self._refresh_region_palette_list()
            self._set_status(SolveStatus.NEEDS_REVIEW, "Manual empty grid created. Paint regions and mark cats, then it will solve automatically.")

    def on_manual_entry_clicked(self):
        size, ok = QInputDialog.getInt(
            self, "Manual board entry", f"Number of rows/columns ({MIN_BOARD_SIZE}-{MAX_BOARD_SIZE}):",
            6, MIN_BOARD_SIZE, MAX_BOARD_SIZE,
        )
        if not ok:
            return
        revision = self.session.start_new_scan()
        self.last_crop_bgr = None
        self.crop_label.setText("(manual entry -- no capture)")
        self.crop_label.setPixmap(QPixmap())
        board = Board.empty(size)
        board.revision = revision
        self.session.board = board
        self.session.last_recognition = None
        self.board_view.set_board(board)
        self._refresh_region_palette_list()
        self._update_coordinate_list(None)
        self._set_status(SolveStatus.NEEDS_REVIEW, "Manual empty grid created. Paint regions and mark cats, then it will solve automatically.")

    def on_export_debug_clicked(self):
        board = self.session.board
        if board is None or self.last_crop_bgr is None:
            QMessageBox.information(self, "Nothing to export", "Scan or import a board with a captured image first.")
            return
        directory = QFileDialog.getExistingDirectory(self, "Choose export folder")
        if not directory:
            return
        grid = self.session.last_recognition.grid if self.session.last_recognition else None
        overlay_img = self._render_grid_overlay(self.last_crop_bgr, grid) if grid is not None else None
        persistence.export_debug_bundle(directory, self.last_crop_bgr, overlay_img, board.to_json())
        QMessageBox.information(self, "Exported", f"Debug bundle written to:\n{directory}")

    def _render_grid_overlay(self, crop_bgr: np.ndarray, grid) -> np.ndarray:
        img = crop_bgr.copy()
        h, w = img.shape[:2]
        for x in grid.x_edges:
            cv2.line(img, (int(x), 0), (int(x), h), (0, 255, 0), 1)
        for y in grid.y_edges:
            cv2.line(img, (0, int(y)), (w, int(y)), (0, 255, 0), 1)
        return img

    # ------------------------------------------------------------ settings

    def _on_respect_x_toggled(self, checked: bool):
        self.respect_x_marks = checked
        persistence.save_respect_x_marks(checked)
        if self.session.board is not None:
            revision = self.session.start_edit()
            self._launch_solve(revision)

    def _on_time_budget_changed(self, value: float):
        self.time_budget_seconds = value
        persistence.save_time_budget_seconds(value)

    def _on_always_on_top_toggled(self, checked: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()
