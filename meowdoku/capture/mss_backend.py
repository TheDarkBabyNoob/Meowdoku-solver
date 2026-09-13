"""mss-based capture backend for Apple Silicon Macs.

Why mss: it wraps CoreGraphics' display-stream/screenshot APIs, requires no
Accessibility permission (only Screen Recording, which is the correct macOS
permission for pixel capture), needs no compiled extension beyond its
bundled ctypes bindings, and -- verified directly in this environment during
implementation -- successfully grabs real, non-blank pixel data on this
machine (Apple Silicon M1, macOS 26.6, mss 10.2.0). If a future macOS
release breaks mss's CoreGraphics calls, implement a ScreenCaptureKit-based
CaptureBackend and swap it in behind this same interface; nothing else in
the app depends on mss directly.
"""
from __future__ import annotations

import numpy as np

from meowdoku.capture.base import CaptureBackend, CaptureError
from meowdoku.models import MonitorInfo

PERMISSION_INSTRUCTIONS = (
    "Meowdoku Companion could not capture the screen. On macOS, screen "
    "capture requires the 'Screen Recording' permission:\n\n"
    "  1. Open System Settings > Privacy & Security > Screen Recording.\n"
    "  2. Enable the checkbox for the app that is actually running this "
    "process:\n"
    "       - If you launched via launch.command from Terminal, grant the "
    "permission to Terminal (or iTerm2, whichever you used).\n"
    "       - If you launched the packaged Meowdoku Companion.app, grant "
    "the permission to 'Meowdoku Companion' itself.\n"
    "  3. You may need to quit and relaunch the app (or Terminal) after "
    "granting permission.\n\n"
    "This app never requests Accessibility access -- it only reads pixels, "
    "it never simulates clicks or key presses."
)


def is_probably_blank(image: np.ndarray) -> bool:
    """Heuristic: near-zero variance and near-zero mean usually means the OS
    silently returned black pixels because Screen Recording permission is
    missing, rather than a legitimately all-dark board. Not a certainty --
    callers should present this as a possible permission issue, not a hard
    failure, since a real screenshot of a dark region is possible."""
    if image.size == 0:
        return True
    return bool(image.std() < 1.0 and image.mean() < 2.0)


class MSSCaptureBackend(CaptureBackend):
    def __init__(self):
        self._mss = None

    def _get_mss(self):
        import mss  # local import: keep mss out of modules that must stay import-light

        if self._mss is None:
            self._mss = mss.mss()
        return self._mss

    def list_monitors(self) -> list:
        try:
            sct = self._get_mss()
            monitors = sct.monitors
        except Exception as exc:  # pragma: no cover - defensive, backend-specific
            raise CaptureError("backend_error", f"Could not enumerate displays: {exc}") from exc

        result = []
        # monitors[0] is mss's synthetic "all displays" bounding box; real
        # displays start at index 1.
        for idx in range(1, len(monitors)):
            m = monitors[idx]
            result.append(MonitorInfo(index=idx, left=m["left"], top=m["top"], width=m["width"], height=m["height"], name=f"Display {idx}"))
        return result

    def grab_region(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        if width <= 0 or height <= 0:
            raise CaptureError("invalid_region", f"Selected region has non-positive size ({width}x{height}).")
        try:
            sct = self._get_mss()
            shot = sct.grab({"left": int(left), "top": int(top), "width": int(width), "height": int(height)})
        except Exception as exc:
            msg = str(exc).lower()
            if "not authorized" in msg or "permission" in msg or "denied" in msg:
                raise CaptureError("permission_denied", PERMISSION_INSTRUCTIONS) from exc
            raise CaptureError("backend_error", f"Screen capture failed: {exc}") from exc

        arr = np.asarray(shot)  # BGRA, shape (H, W, 4)
        if arr.size == 0:
            raise CaptureError("backend_error", "Capture returned an empty image.")
        bgr = arr[:, :, :3].copy()
        return bgr
