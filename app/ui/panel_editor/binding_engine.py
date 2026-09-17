"""
变量绑定引擎 - 控件属性到变量的绑定

支持双向绑定:
- 控件值变化 -> 写入变量
- 变量值变化 -> 更新控件显示
"""

import logging
from typing import Any, Optional

from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QComboBox, QLabel, QPushButton, QProgressBar
)

from app.core.variable_system import VariableRegistry

logger = logging.getLogger(__name__)


class Binding:
    """单个绑定关系"""

    def __init__(self, widget, attr: str, var_name: str,
                 direction: str = "bidirectional"):
        self.widget = widget
        self.attr = attr           # "text", "value", "checked"
        self.var_name = var_name
        self.direction = direction  # "bidirectional", "widget_to_var", "var_to_widget"
        self._updating = False

    def read_widget(self) -> Any:
        """从控件读取值"""
        if isinstance(self.widget, QLineEdit):
            return self.widget.text()
        elif isinstance(self.widget, (QSpinBox, QDoubleSpinBox)):
            return self.widget.value()
        elif isinstance(self.widget, QCheckBox):
            return self.widget.isChecked()
        elif isinstance(self.widget, QComboBox):
            return self.widget.currentText()
        return None

    def write_widget(self, value: Any):
        """向控件写入值"""
        if self._updating:
            return
        self._updating = True
        try:
            if isinstance(self.widget, QLineEdit):
                self.widget.setText(str(value) if value is not None else "")
            elif isinstance(self.widget, (QSpinBox, QDoubleSpinBox)):
                try:
                    self.widget.setValue(float(value) if value is not None else 0)
                except (ValueError, TypeError):
                    pass
            elif isinstance(self.widget, QCheckBox):
                self.widget.setChecked(bool(value))
            elif isinstance(self.widget, QComboBox):
                idx = self.widget.findText(str(value))
                if idx >= 0:
                    self.widget.setCurrentIndex(idx)
            elif isinstance(self.widget, QLabel):
                self.widget.setText(str(value) if value is not None else "")
            elif isinstance(self.widget, QProgressBar):
                try:
                    self.widget.setValue(int(value))
                except (ValueError, TypeError):
                    pass
        finally:
            self._updating = False


class BindingEngine(QObject):
    """变量绑定引擎"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._var_registry = VariableRegistry.instance()
        self._bindings: list[Binding] = []

    def bind(self, widget, attr: str, var_name: str,
             direction: str = "bidirectional") -> Binding:
        """创建绑定"""
        # 确保变量存在
        if not self._var_registry.exists(var_name):
            self._var_registry.create(var_name)

        binding = Binding(widget, attr, var_name, direction)
        self._bindings.append(binding)

        # 注册变量变化回调
        if direction in ("bidirectional", "var_to_widget"):
            var = self._var_registry.get(var_name)
            if var:
                var.on_change(lambda name, old, new: self._on_var_changed(binding))

        # 初始同步
        var = self._var_registry.get(var_name)
        if var and var.value is not None:
            binding.write_widget(var.value)

        logger.debug(f"绑定创建: {var_name} <-> {attr}")
        return binding

    def unbind(self, binding: Binding):
        """移除绑定"""
        if binding in self._bindings:
            self._bindings.remove(binding)

    def unbind_all(self):
        """移除所有绑定"""
        self._bindings.clear()

    def _on_var_changed(self, binding: Binding):
        """变量值变化 -> 更新控件"""
        if binding.direction in ("bidirectional", "var_to_widget"):
            var = self._var_registry.get(binding.var_name)
            if var:
                binding.write_widget(var.value)

    def sync_widget_to_var(self, binding: Binding):
        """控件值变化 -> 写入变量"""
        if binding.direction in ("bidirectional", "widget_to_var"):
            value = binding.read_widget()
            self._var_registry.set_value(binding.var_name, value)

    def sync_all(self):
        """同步所有绑定"""
        for binding in self._bindings:
            if binding.direction in ("bidirectional", "widget_to_var"):
                value = binding.read_widget()
                self._var_registry.set_value(binding.var_name, value)

    def get_bindings(self) -> list[Binding]:
        return list(self._bindings)
