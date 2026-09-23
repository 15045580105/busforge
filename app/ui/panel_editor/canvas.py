"""
画布 - 设计区域 (供panel_editor使用)
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal


class DesignCanvas(QWidget):
    """设计画布 - 可放置/移动/选中控件"""

    widget_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(800, 600)
        self.setStyleSheet("background-color: #1e1e2e; border: 1px solid #313244;")
        self._placed: list[QWidget] = []
        self._selected = None

    def get_widgets(self) -> list[QWidget]:
        return list(self._placed)

    def add_widget(self, w: QWidget):
        w.setParent(self)
        self._placed.append(w)
        w.show()

    def remove_widget(self, w: QWidget):
        if w in self._placed:
            self._placed.remove(w)
            w.deleteLater()
            if self._selected is w:
                self._selected = None
                self.widget_selected.emit(None)

    def select_widget(self, w: QWidget):
        self._selected = w
        self.widget_selected.emit(w)
