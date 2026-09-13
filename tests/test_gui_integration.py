"""Integration-level test that the actual Qt wiring (not just BoardSession
in isolation) discards a stale worker's result. Runs real QThread workers
with an artificially slow first recognition call so the second (current)
scan's worker genuinely finishes first -- a real race, not a simulated one.
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QApplication

from meowdoku.gui.main_window import MainWindow
from meowdoku.models import Board, CellState
from meowdoku.recognition import pipeline as pipeline_module


def _make_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _tiny_board_image(size=4):
    import cv2
    import numpy as np

    from scripts.gen_recognition_fixtures import render_board

    region_ids = [[r for _ in range(size)] for r in range(size)]
    return render_board(region_ids, {}, cell_px=40)


def test_slow_first_scan_worker_result_is_discarded_when_second_scan_started_first(qtbot=None):
    app = _make_app()
    window = MainWindow()

    image_a = _tiny_board_image(4)
    image_b = _tiny_board_image(5)

    real_recognize = pipeline_module.recognize
    call_order = []

    def slow_recognize(crop_bgr, *args, **kwargs):
        # The very first call (for image_a / revision 1) sleeps so that the
        # second scan's worker (image_b / revision 2), started afterwards,
        # genuinely finishes first.
        if crop_bgr is image_a:
            call_order.append("a-start")
            time.sleep(0.3)
            call_order.append("a-end")
        else:
            call_order.append("b-start-and-end")
        return real_recognize(crop_bgr, *args, **kwargs)

    pipeline_module.recognize = slow_recognize
    try:
        rev1 = window.session.start_new_scan()
        window.last_crop_bgr = image_a
        window._launch_scan_worker(rev1, image_a)

        # Immediately start a second scan before the first worker returns --
        # this is exactly "rescanning while an old worker is finishing".
        rev2 = window.session.start_new_scan()
        window.last_crop_bgr = image_b
        window._launch_scan_worker(rev2, image_b)

        deadline = time.monotonic() + 5.0
        while window._scan_worker.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        # Let any queued signal deliveries (including the slow worker's,
        # which may still be finishing) get processed.
        finish_deadline = time.monotonic() + 1.0
        while time.monotonic() < finish_deadline:
            app.processEvents()
            time.sleep(0.01)

        assert window.session.revision == rev2
        assert window.session.board is not None
        # The board actually applied must be the 5x5 one (image_b / rev2),
        # never the slower 4x4 one (image_a / rev1), even though rev1's
        # worker was the first to start and took longer to finish.
        assert window.session.board.size == 5
        assert call_order[0] == "a-start"
    finally:
        pipeline_module.recognize = real_recognize
        window.close()
