"""Capture backend interface. Keeping this a small ABC lets the GUI depend on
an interface rather than mss directly, and lets a native backend be swapped
in later if a target macOS/mss combination cannot capture (see
mss_backend.py for the concrete reasoning about why mss is used here)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from meowdoku.models import MonitorInfo


class CaptureError(Exception):
    """reason is one of: 'permission_denied', 'invalid_region', 'backend_error'."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


class CaptureBackend(ABC):
    @abstractmethod
    def list_monitors(self) -> list:
        """Return MonitorInfo for every attached display, in the backend's
        own coordinate space (points)."""

    @abstractmethod
    def grab_region(self, left: int, top: int, width: int, height: int):
        """Capture the given absolute region (in points) and return an
        HxWx3 BGR uint8 numpy array at whatever pixel resolution the OS
        actually returns (never assume a fixed scale factor)."""
