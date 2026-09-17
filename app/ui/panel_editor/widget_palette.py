"""
控件面板 - 可拖拽的控件列表
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel
from PySide6.QtCore import Qt


# 可用控件定义
WIDGET_DEFS = [
    ("Label", "标签", "基础"),
    ("Button", "按钮", "基础"),
    ("LineEdit", "输入框", "基础"),
    ("SpinBox", "数值框", "基础"),
    ("CheckBox", "复选框", "基础"),
    ("ComboBox", "下拉框", "基础"),
    ("ProgressBar", "进度条", "数据"),
    ("LED", "LED指示灯", "数据"),
]


class WidgetPalette(QWidget):
    """控件面板 - 拖拽源"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("  控件库"))

        self._list = QListWidget()
        self._list.setDragEnabled(True)

        for widget_type, display_name, category in WIDGET_DEFS:
            item = QListWidgetItem(f"[{category}] {display_name}")
            item.setData(Qt.ItemDataRole.UserRole, widget_type)
            self._list.addItem(item)

        layout.addWidget(self._list)

    def get_selected_type(self) -> str:
        item = self._list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return ""
