import pytest

from meowdoku import coords
from meowdoku.models import MonitorInfo


def test_capture_scale_derives_from_actual_returned_dimensions_not_assumed():
    # A Retina-like 2x scale, but derived, never hardcoded.
    scale = coords.CaptureScale.derive(400, 300, 800, 600)
    assert scale.scale_x == pytest.approx(2.0)
    assert scale.scale_y == pytest.approx(2.0)

    # A non-2x scale (e.g. a hypothetical 1.5x or 1x display) must also work
    # -- proving the code does not special-case 2.0.
    scale_1x = coords.CaptureScale.derive(400, 300, 400, 300)
    assert scale_1x.scale_x == pytest.approx(1.0)
    assert scale_1x.scale_y == pytest.approx(1.0)

    scale_1_5x = coords.CaptureScale.derive(200, 100, 300, 150)
    assert scale_1_5x.scale_x == pytest.approx(1.5)
    assert scale_1_5x.scale_y == pytest.approx(1.5)


def test_qt_global_to_monitor_local_handles_negative_origin():
    # A monitor positioned above/left of the primary display has a negative
    # origin in the global desktop coordinate space.
    monitor = MonitorInfo(index=2, left=-1440, top=-200, width=1440, height=900)
    local_x, local_y = coords.qt_global_to_monitor_local(-1440, -200, monitor)
    assert (local_x, local_y) == (0, 0)

    local_x2, local_y2 = coords.qt_global_to_monitor_local(-1000, -100, monitor)
    assert (local_x2, local_y2) == (440, 100)

    back_x, back_y = coords.monitor_local_to_qt_global(local_x2, local_y2, monitor)
    assert (back_x, back_y) == (-1000, -100)


def test_crop_full_frame_for_rect_with_retina_scale_and_negative_origin():
    # Monitor at a negative origin, reported at 1440x900 points, but the
    # backend's full-frame capture actually returns 2880x1800 pixels (2x) --
    # the scale must be derived from that mismatch, not assumed.
    monitor = MonitorInfo(index=1, left=-1440, top=0, width=1440, height=900)
    full_w_px, full_h_px = 2880, 1800

    # Selection: monitor-local rect (100, 50, 200, 150) in points -> absolute
    # coordinates are monitor.left + local.
    abs_left = monitor.left + 100
    abs_top = monitor.top + 50
    x0, y0, x1, y1 = coords.crop_full_frame_for_rect(full_w_px, full_h_px, monitor, abs_left, abs_top, 200, 150)

    # Expected: local (100,50)-(300,200) points * 2x scale = (200,100)-(600,400) px.
    assert (x0, y0, x1, y1) == (200, 100, 600, 400)


def test_crop_full_frame_for_rect_clamped_to_frame_bounds():
    monitor = MonitorInfo(index=1, left=0, top=0, width=100, height=100)
    # A rect that (due to a rounding/off-by-one selection) extends past the
    # monitor bounds must be clamped, never produce an out-of-range crop.
    x0, y0, x1, y1 = coords.crop_full_frame_for_rect(100, 100, monitor, 90, 90, 50, 50)
    assert 0 <= x0 <= x1 <= 100
    assert 0 <= y0 <= y1 <= 100


def test_normalize_rect_handles_any_drag_direction():
    assert coords.normalize_rect(10, 10, 50, 60) == (10, 10, 40, 50)
    assert coords.normalize_rect(50, 60, 10, 10) == (10, 10, 40, 50)
    assert coords.normalize_rect(10, 60, 50, 10) == (10, 10, 40, 50)


def test_find_monitor_for_point_and_rect_spans_monitors():
    m1 = MonitorInfo(index=1, left=0, top=0, width=1000, height=800)
    m2 = MonitorInfo(index=2, left=1000, top=0, width=1000, height=800)
    monitors = [m1, m2]

    assert coords.find_monitor_for_point(500, 400, monitors).index == 1
    assert coords.find_monitor_for_point(1500, 400, monitors).index == 2
    assert coords.find_monitor_for_point(5000, 5000, monitors) is None

    assert not coords.rect_spans_monitors(10, 10, 100, 100, monitors)
    assert coords.rect_spans_monitors(950, 10, 100, 100, monitors)  # crosses from m1 into m2


def test_monitor_local_rect_to_absolute_roundtrip():
    monitor = MonitorInfo(index=1, left=-500, top=300, width=1000, height=800)
    abs_left, abs_top, w, h = coords.monitor_local_rect_to_absolute(20, 30, 100, 50, monitor)
    assert (abs_left, abs_top, w, h) == (-480, 330, 100, 50)
