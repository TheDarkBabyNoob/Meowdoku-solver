"""Coordinate transforms between the four spaces this app has to reconcile:

  1. Qt logical coordinates  -- device-independent points from the overlay
     widget's mouse events / QScreen.geometry(), origin can be anywhere
     (multi-monitor desktops commonly have negative-origin screens).
  2. Monitor origin           -- a display's (left, top) in the capture
     backend's own coordinate space (mss reports this in points, matching
     Qt's logical space on macOS).
  3. Capture-backend coordinates -- the absolute {left, top, width, height}
     rect (in points) passed to the capture backend's grab call.
  4. Image pixels             -- the actual width/height of the ndarray the
     backend returns, which can differ from the requested point-size by any
     scale factor (2.0 on Retina, but this is NEVER assumed -- it is always
     derived from the real returned image dimensions).

This module is pure Python/dataclasses with no Qt, mss, or OpenCV import so
it can be unit tested without a display or camera permissions.
"""
from __future__ import annotations

from dataclasses import dataclass

from meowdoku.models import MonitorInfo


@dataclass(frozen=True)
class CaptureScale:
    """An empirically-derived mapping between requested point-space size and
    the pixels actually returned by a capture call. Never hardcode this --
    always build it from a real (requested, returned) pair."""

    scale_x: float
    scale_y: float

    @staticmethod
    def derive(requested_width_pts: float, requested_height_pts: float, returned_width_px: int, returned_height_px: int) -> "CaptureScale":
        if requested_width_pts <= 0 or requested_height_pts <= 0:
            raise ValueError("requested width/height must be positive")
        return CaptureScale(
            scale_x=returned_width_px / requested_width_pts,
            scale_y=returned_height_px / requested_height_pts,
        )


def qt_global_to_monitor_local(qt_x: float, qt_y: float, monitor: MonitorInfo) -> tuple:
    """Convert a Qt-global logical point to coordinates local to a monitor's
    own origin (which may itself be negative)."""
    return qt_x - monitor.left, qt_y - monitor.top


def monitor_local_to_qt_global(local_x: float, local_y: float, monitor: MonitorInfo) -> tuple:
    return local_x + monitor.left, local_y + monitor.top


def normalize_rect(x0: float, y0: float, x1: float, y1: float) -> tuple:
    """Order two corner points into (left, top, width, height), handling a
    drag performed in any direction."""
    left, right = (x0, x1) if x0 <= x1 else (x1, x0)
    top, bottom = (y0, y1) if y0 <= y1 else (y1, y0)
    return left, top, right - left, bottom - top


def monitor_local_rect_to_absolute(local_left: float, local_top: float, width: float, height: float, monitor: MonitorInfo) -> tuple:
    """Convert a monitor-local logical rect to absolute capture-backend
    (points) coordinates, i.e. the rect stored in SelectionRect."""
    abs_left, abs_top = monitor_local_to_qt_global(local_left, local_top, monitor)
    return abs_left, abs_top, width, height


def find_monitor_for_point(x: float, y: float, monitors) -> MonitorInfo:
    """Return the monitor containing a Qt-global point, or None."""
    for m in monitors:
        if m.contains_point(int(x), int(y)):
            return m
    return None


def rect_spans_monitors(left: float, top: float, width: float, height: float, monitors) -> bool:
    """True if the given absolute rect's four corners do not all fall on the
    same single monitor (used to reject cross-display selections in v1)."""
    corners = [(left, top), (left + width, top), (left, top + height), (left + width, top + height)]
    owning = set()
    for cx, cy in corners:
        # Nudge corners inward by a hair so exact-boundary coordinates count
        # as belonging to the monitor they are the edge of.
        m = find_monitor_for_point(min(cx, left + width - 1), min(cy, top + height - 1), monitors)
        if m is None:
            return True
        owning.add(m.index)
    return len(owning) != 1


def image_px_to_monitor_local(px: float, py: float, scale: CaptureScale) -> tuple:
    return px / scale.scale_x, py / scale.scale_y


def monitor_local_to_image_px(local_x: float, local_y: float, scale: CaptureScale) -> tuple:
    return local_x * scale.scale_x, local_y * scale.scale_y


def crop_full_frame_for_rect(
    full_frame_width_px: int,
    full_frame_height_px: int,
    monitor: MonitorInfo,
    abs_rect_left: float,
    abs_rect_top: float,
    abs_rect_width: float,
    abs_rect_height: float,
) -> tuple:
    """Given a full-monitor capture (returned at ``full_frame_width_px`` x
    ``full_frame_height_px`` pixels) and an absolute selection rect in
    points, return the pixel-space (x0, y0, x1, y1) box to crop.

    Used by any capture backend that can only grab a whole display (the
    "discard the unused pixels" path). The scale factor is derived from the
    monitor's own reported point size vs. the actual returned frame size --
    never assumed to be 2.0 -- and negative monitor origins are handled
    since all offsets are simple subtraction.
    """
    scale = CaptureScale.derive(monitor.width, monitor.height, full_frame_width_px, full_frame_height_px)
    local_left = abs_rect_left - monitor.left
    local_top = abs_rect_top - monitor.top
    x0, y0 = monitor_local_to_image_px(local_left, local_top, scale)
    x1, y1 = monitor_local_to_image_px(local_left + abs_rect_width, local_top + abs_rect_height, scale)
    ix0, iy0 = max(0, round(x0)), max(0, round(y0))
    ix1, iy1 = min(full_frame_width_px, round(x1)), min(full_frame_height_px, round(y1))
    return ix0, iy0, max(ix0, ix1), max(iy0, iy1)
