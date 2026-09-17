"""
Panel自定义面板 - 用户可搭建的自定义界面

两种模式: 编辑模式 / 运行模式
编辑模式: 控件面板 + 画布 + 属性面板
运行模式: 只显示画布(用户交互界面)
"""

import json
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QToolBar,
    QLabel, QStackedWidget, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QFormLayout, QSpinBox,
    QLineEdit, QCheckBox, QGroupBox, QScrollArea, QFileDialog,
    QPlainTextEdit
)
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QFont, QColor

from app.core.variable_system import VariableRegistry

logger = logging.getLogger(__name__)

# 可拖拽控件类型
PALETTE_WIDGETS = {
    "Label": "QLabel",
    "Button": "QPushButton",
    "LineEdit": "QLineEdit",
    "SpinBox": "QSpinBox",
    "CheckBox": "QCheckBox",
    "ComboBox": "QComboBox",
    "ProgressBar": "QProgressBar",
    "LED": "QLabel",
}


class CanvasWidget(QWidget):
    """画布 - 可放置控件的设计区域"""

    widget_placed = Signal(str, str, int, int)  # widget_type, name, x, y
    widget_selected = Signal(object)  # selected widget

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(800, 600)
        self.setStyleSheet("background-color: #1e1e2e; border: 1px solid #313244;")
        self.setMouseTracking(True)
        self._placed_widgets: list[QWidget] = []
        self._selected: Optional[QWidget] = None
        self._dragging = False
        self._drag_offset = QPoint()
        self._edit_mode = True

    def place_widget(self, widget_type: str, name: str, x: int, y: int):
        """在画布上放置控件"""
        cls_name = PALETTE_WIDGETS.get(widget_type)
        if not cls_name:
            return

        if widget_type == "Label":
            w = QLabel(name, self)
        elif widget_type == "Button":
            w = QPushButton(name, self)
        elif widget_type == "LineEdit":
            w = QLineEdit(self)
            w.setPlaceholderText(name)
        elif widget_type == "SpinBox":
            w = QSpinBox(self)
        elif widget_type == "CheckBox":
            w = QCheckBox(name, self)
        elif widget_type == "ComboBox":
            w = QComboBox(self)
            w.addItems(["选项1", "选项2", "选项3"])
        elif widget_type == "ProgressBar":
            from PySide6.QtWidgets import QProgressBar
            w = QProgressBar(self)
        elif widget_type == "LED":
            w = QLabel("●", self)
            w.setStyleSheet("color: #a6e3a1; font-size: 24px;")
        else:
            return

        w.move(x, y)
        w.setProperty("canvas_name", name)
        w.setProperty("canvas_type", widget_type)
        w.show()
        self._placed_widgets.append(w)

        if self._edit_mode:
            w.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_edit_mode(self, edit: bool):
        self._edit_mode = edit
        for w in self._placed_widgets:
            if edit:
                w.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                w.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if not self._edit_mode:
            return
        # 检查是否点击了控件
        for w in reversed(self._placed_widgets):
            if w.geometry().contains(event.position().toPoint()):
                self._selected = w
                self._dragging = True
                self._drag_offset = event.position().toPoint() - w.pos()
                self.widget_selected.emit(w)
                w.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        self._selected = None
        self.widget_selected.emit(None)

    def mouseMoveEvent(self, event):
        if self._dragging and self._selected and self._edit_mode:
            new_pos = event.position().toPoint() - self._drag_offset
            self._selected.move(new_pos)

    def mouseReleaseEvent(self, event):
        if self._selected and self._edit_mode:
            self._selected.setCursor(Qt.CursorShape.OpenHandCursor)
        self._dragging = False

    def delete_selected(self):
        if self._selected:
            self._placed_widgets.remove(self._selected)
            self._selected.deleteLater()
            self._selected = None
            self.widget_selected.emit(None)

    def get_config(self) -> list[dict]:
        """获取画布配置"""
        config = []
        for w in self._placed_widgets:
            config.append({
                'type': w.property("canvas_type"),
                'name': w.property("canvas_name"),
                'x': w.x(),
                'y': w.y(),
                'w': w.width(),
                'h': w.height(),
            })
        return config

    def load_config(self, config: list[dict]):
        """加载画布配置"""
        # 清除现有控件
        for w in self._placed_widgets:
            w.deleteLater()
        self._placed_widgets.clear()

        # 重新创建
        for item in config:
            self.place_widget(
                item.get('type', 'Label'),
                item.get('name', ''),
                item.get('x', 0),
                item.get('y', 0)
            )


class CustomPanel(QWidget):
    """用户自定义面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._var_registry = VariableRegistry.instance()
        self._edit_mode = True
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 工具栏
        toolbar = QHBoxLayout()

        self._mode_btn = QPushButton("编辑模式")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setChecked(True)
        self._mode_btn.clicked.connect(self._toggle_mode)
        toolbar.addWidget(self._mode_btn)

        save_btn = QPushButton("保存布局")
        save_btn.clicked.connect(self._save_layout)
        toolbar.addWidget(save_btn)

        load_btn = QPushButton("加载布局")
        load_btn.clicked.connect(self._load_layout)
        toolbar.addWidget(load_btn)

        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("dangerBtn")
        # 画布在下方才创建, 这里惰性访问避免构造期 AttributeError
        del_btn.clicked.connect(lambda: self._canvas.delete_selected())
        toolbar.addWidget(del_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # 主区域
        self._main_stack = QStackedWidget()
        layout.addWidget(self._main_stack)

        # 编辑模式页面
        edit_widget = QWidget()
        edit_layout = QHBoxLayout(edit_widget)
        edit_layout.setContentsMargins(0, 0, 0, 0)

        edit_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 控件面板(左侧)
        palette = QGroupBox("控件库")
        palette_layout = QVBoxLayout(palette)
        self._palette_list = QListWidget()
        for name in PALETTE_WIDGETS:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._palette_list.addItem(item)
        self._palette_list.itemDoubleClicked.connect(self._on_palette_double_click)
        palette_layout.addWidget(self._palette_list)

        # 放置位置
        pos_layout = QFormLayout()
        self._pos_x = QSpinBox()
        self._pos_x.setRange(0, 800)
        self._pos_x.setValue(50)
        pos_layout.addRow("X:", self._pos_x)
        self._pos_y = QSpinBox()
        self._pos_y.setRange(0, 600)
        self._pos_y.setValue(50)
        pos_layout.addRow("Y:", self._pos_y)
        palette_layout.addLayout(pos_layout)

        add_btn = QPushButton("添加控件")
        add_btn.clicked.connect(self._add_selected_widget)
        palette_layout.addWidget(add_btn)

        edit_splitter.addWidget(palette)

        # 画布(中间)
        canvas_scroll = QScrollArea()
        self._canvas = CanvasWidget()
        self._canvas.widget_selected.connect(self._on_widget_selected)
        canvas_scroll.setWidget(self._canvas)
        canvas_scroll.setWidgetResizable(True)
        edit_splitter.addWidget(canvas_scroll)

        # 属性面板(右侧)
        props = QGroupBox("属性")
        self._props_layout = QFormLayout(props)
        self._prop_name = QLineEdit()
        self._props_layout.addRow("名称:", self._prop_name)
        self._prop_var = QComboBox()
        self._prop_var.setEditable(True)
        self._props_layout.addRow("绑定变量:", self._prop_var)
        self._prop_bind_dir = QComboBox()
        self._prop_bind_dir.addItems(["双向", "控件->变量", "变量->控件"])
        self._props_layout.addRow("绑定方向:", self._prop_bind_dir)
        edit_splitter.addWidget(props)

        edit_splitter.setStretchFactor(0, 1)
        edit_splitter.setStretchFactor(1, 3)
        edit_splitter.setStretchFactor(2, 1)

        edit_layout.addWidget(edit_splitter)
        self._main_stack.addWidget(edit_widget)

        # 运行模式页面(只有画布)
        run_scroll = QScrollArea()
        self._run_canvas = CanvasWidget()
        self._run_canvas.set_edit_mode(False)
        run_scroll.setWidget(self._run_canvas)
        run_scroll.setWidgetResizable(True)
        self._main_stack.addWidget(run_scroll)

        self._main_stack.setCurrentIndex(0)

        # 刷新变量列表
        self._refresh_var_list()

    def _toggle_mode(self, checked):
        self._edit_mode = checked
        if checked:
            self._mode_btn.setText("编辑模式")
            self._main_stack.setCurrentIndex(0)
        else:
            self._mode_btn.setText("运行模式")
            # 同步到运行画布
            config = self._canvas.get_config()
            self._run_canvas.load_config(config)
            self._main_stack.setCurrentIndex(1)

    def _on_palette_double_click(self, item: QListWidgetItem):
        self._add_selected_widget()

    def _add_selected_widget(self):
        item = self._palette_list.currentItem()
        if not item:
            return
        widget_type = item.data(Qt.ItemDataRole.UserRole)
        name = f"{widget_type}_{len(self._canvas._placed_widgets) + 1}"
        x = self._pos_x.value()
        y = self._pos_y.value()
        self._canvas.place_widget(widget_type, name, x, y)

    def _on_widget_selected(self, widget):
        if widget:
            self._prop_name.setText(widget.property("canvas_name") or "")
            # 刷新变量列表
            self._refresh_var_list()
        else:
            self._prop_name.clear()

    def _refresh_var_list(self):
        self._prop_var.clear()
        for name in self._var_registry.list_names():
            self._prop_var.addItem(name)

    def _save_layout(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存布局", "", "JSON Files (*.json)")
        if path:
            config = {
                'widgets': self._canvas.get_config(),
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.info(f"布局已保存: {path}")

    def _load_layout(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载布局", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self._canvas.load_config(config.get('widgets', []))
                logger.info(f"布局已加载: {path}")
            except Exception as e:
                logger.error(f"加载布局失败: {e}")
