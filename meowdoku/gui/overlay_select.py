"""Drag-to-select screen-area overlay. One SelectionOverlay is created per
attached QScreen so the user can drag on whatever monitor shows the
mirrored iPhone; whichever overlay actually receives a drag reports the
selection, and the coordinator (MainWindow) closes all of them. Escape
cancels. The overlay never simulates input -- it only reads mouse/keyboard
events targeted at itself.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


class SelectionOverlay(QWidget):
    # rect is in Qt global logical coordinates, already clamped to this
    # overlay's own screen; clamped=True if the raw drag left that screen.
    selection_made = Signal(QRect, bool)
    cancelled = Signal()

    def __init__(self, screen):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.screen_ref = screen
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(screen.geometry())
        self._origin: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self._dragging = False

    def start(self):
        self.setWindowOpacity(1.0)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._current = self._origin
            self._dragging = True
            self.grabMouse()
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._current = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.releaseMouse()
            raw = QRect(self._origin, self._current).normalized()
            screen_geom = self.screen_ref.geometry()
            clamped_rect = raw.intersected(screen_geom)
            was_clamped = clamped_rect != raw
            self._origin = None
            self._current = None
            if clamped_rect.width() < 4 or clamped_rect.height() < 4:
                self.cancelled.emit()
                return
            self.selection_made.emit(clamped_rect, was_clamped)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self._dragging:
                self.releaseMouse()
                self._dragging = False
            self.cancelled.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._origin and self._current:
            raw = QRect(self._origin, self._current).normalized()
            local_rect = QRect(self.mapFromGlobal(raw.topLeft()), raw.size())
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(local_rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(80, 200, 255), 2))
            painter.drawRect(local_rect)
            size_text = f"{local_rect.width()} x {local_rect.height()}"
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(local_rect.bottomLeft() + QPoint(4, 18), size_text)
