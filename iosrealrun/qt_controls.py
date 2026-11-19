"""Common Qt controls for the desktop and route editor."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox


class ComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#587495"), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 15, self.height() / 2
        painter.drawLine(QPointF(x - 3.1, y - 1.5), QPointF(x, y + 1.8))
        painter.drawLine(QPointF(x, y + 1.8), QPointF(x + 3.1, y - 1.5))

    def wheelEvent(self, event):
        if self.hasFocus() and self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class CheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = "#ffffff" if self.isEnabled() else "#778aa4"
        painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        y = self.height() / 2
        painter.drawLine(QPointF(5, y), QPointF(8, y + 3))
        painter.drawLine(QPointF(8, y + 3), QPointF(13, y - 3))
