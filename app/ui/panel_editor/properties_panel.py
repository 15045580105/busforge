"""
属性面板 - 编辑选中控件的属性
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QSpinBox,
    QComboBox, QLabel, QGroupBox
)
from PySide6.QtCore import Qt

from app.core.variable_system import VariableRegistry


class PropertiesPanel(QWidget):
    """属性面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._var_registry = VariableRegistry.instance()
        self._current_widget = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(QLabel("属性"))

        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setReadOnly(True)
        form.addRow("控件名:", self._name_edit)

        self._type_label = QLabel("")
        form.addRow("类型:", self._type_label)

        self._x_spin = QSpinBox()
        self._x_spin.setRange(0, 2000)
        form.addRow("X:", self._x_spin)

        self._y_spin = QSpinBox()
        self._y_spin.setRange(0, 2000)
        form.addRow("Y:", self._y_spin)

        self._w_spin = QSpinBox()
        self._w_spin.setRange(10, 2000)
        form.addRow("宽度:", self._w_spin)

        self._h_spin = QSpinBox()
        self._h_spin.setRange(10, 2000)
        form.addRow("高度:", self._h_spin)

        layout.addLayout(form)

        # 变量绑定
        bind_group = QGroupBox("变量绑定")
        bind_layout = QFormLayout(bind_group)

        self._var_combo = QComboBox()
        self._var_combo.setEditable(True)
        bind_layout.addRow("变量:", self._var_combo)

        self._dir_combo = QComboBox()
        self._dir_combo.addItems(["双向", "控件->变量", "变量->控件"])
        bind_layout.addRow("方向:", self._dir_combo)

        layout.addWidget(bind_group)
        layout.addStretch()

    def set_widget(self, widget):
        """设置选中控件"""
        self._current_widget = widget
        if widget:
            self._name_edit.setText(widget.property("canvas_name") or "")
            self._type_label.setText(widget.property("canvas_type") or type(widget).__name__)
            self._x_spin.setValue(widget.x())
            self._y_spin.setValue(widget.y())
            self._w_spin.setValue(widget.width())
            self._h_spin.setValue(widget.height())
        else:
            self._name_edit.clear()
            self._type_label.clear()

        # 刷新变量列表
        self._var_combo.clear()
        for name in self._var_registry.list_names():
            self._var_combo.addItem(name)
