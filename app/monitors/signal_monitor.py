"""
Signal面板 - 信号值展示 (纯展示层)

左侧: 通道选择 + DBC信号树 (元数据来自DataHub, 只读展示, 可搜索/勾选)
右侧: 勾选信号的实时值 (DataHub 推送 SignalValueDTO, 本面板不做任何解码)
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QSplitter, QLabel, QAbstractItemView, QComboBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from app.datahub.data_hub import DataHub, KIND_SIGNAL
from app.devices.device_manager import DeviceManager
from app.common.variable_system import VariableRegistry
from app.common.ui_settings import UISettings
from app.models.dto import SignalValueDTO

logger = logging.getLogger(__name__)


class SignalMonitorPanel(QWidget):
    """信号监控面板 - 全局统一单实例, 通道可切换"""

    def __init__(self, channel_key: str = "", parent=None):
        super().__init__(parent)
        self._hub = DataHub.instance()
        self._dm = DeviceManager.instance()
        self._var_registry = VariableRegistry.instance()
        self._ui = UISettings.instance()
        self._sub_id = f"signal_{id(self):x}"
        self._channel_key = channel_key or ""
        # signal_name -> 最新DTO (只缓存展示值)
        self._values: dict[str, SignalValueDTO] = {}
        # signal_name -> 表格行号
        self._rows: dict[str, int] = {}
        self._watched: set[str] = set()

        self._setup_ui()
        self._hub.push.connect(self._on_push)
        self._hub.dbc_changed.connect(self._on_dbc_changed)
        self._rebuild_tree()
        self._resubscribe()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self._refresh_values)
        self._refresh_timer.start()

        # 全局进制切换 -> 用缓存重刷原始值列
        # (绑定方法: 工程切换丢弃本面板后 C++ 销毁自动断开;
        #  lambda 连接不会自动断开, 会访问已删除的 C++ 对象)
        self._ui.number_format_changed.connect(
            self._on_number_format_changed)

    def _on_number_format_changed(self, _fmt):
        self._refresh_values()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- 左侧: 通道 + 搜索 + 信号树 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("通道:"))
        self._channel_combo = QComboBox()
        self._refresh_channel_combo()
        self._channel_combo.currentTextChanged.connect(self._on_channel_changed)
        ch_row.addWidget(self._channel_combo)
        left_layout.addLayout(ch_row)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索信号...")
        self._search.setFixedHeight(28)
        self._search.textChanged.connect(self._filter_tree)
        left_layout.addWidget(self._search)

        self._signal_tree = QTreeWidget()
        self._signal_tree.setHeaderHidden(True)
        self._signal_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._signal_tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._signal_tree.itemChanged.connect(self._on_item_changed)
        left_layout.addWidget(self._signal_tree)
        splitter.addWidget(left)

        # ---- 右侧: 值表格 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._value_table = QTableWidget()
        self._value_table.setColumnCount(6)
        self._value_table.setHorizontalHeaderLabels([
            "信号名", "报文名", "物理值", "原始值", "单位", "枚举描述"
        ])
        self._value_table.setAlternatingRowColors(True)
        self._value_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._value_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._value_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._value_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._value_table.verticalHeader().setVisible(False)
        self._value_table.cellDoubleClicked.connect(self._on_cell_double_click)
        right_layout.addWidget(self._value_table)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

    def _refresh_channel_combo(self):
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        for ch in self._dm.list_channels():
            self._channel_combo.addItem(ch.key)
        idx = self._channel_combo.findText(self._channel_key)
        self._channel_combo.setCurrentIndex(idx if idx >= 0 else -1)
        self._channel_combo.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  信号树 (元数据只读展示, 数据源: DataHub)
    # ------------------------------------------------------------------ #

    def _on_dbc_changed(self, channel_key: str, dbc):
        if channel_key == self._channel_key:
            self._rebuild_tree()

    def _rebuild_tree(self):
        self._signal_tree.blockSignals(True)
        self._signal_tree.clear()
        self._watched.clear()
        self._values.clear()
        dbc = self._hub.get_dbc(self._channel_key) if self._channel_key else None
        if dbc:
            for msg in dbc.messages:
                msg_item = QTreeWidgetItem(self._signal_tree, [msg.name])
                msg_item.setData(0, Qt.ItemDataRole.UserRole, "message")
                msg_item.setExpanded(False)
                for sig in msg.signals:
                    sig_item = QTreeWidgetItem(msg_item, [sig.name])
                    sig_item.setData(0, Qt.ItemDataRole.UserRole, "signal")
                    sig_item.setData(0, Qt.ItemDataRole.UserRole + 1, {
                        'signal_name': sig.name,
                        'message_name': msg.name,
                        'unit': sig.unit,
                    })
                    sig_item.setCheckState(0, Qt.CheckState.Unchecked)
        self._signal_tree.blockSignals(False)
        self._rebuild_value_table()
        self._resubscribe()

    def _filter_tree(self, text: str):
        text = text.lower()
        for i in range(self._signal_tree.topLevelItemCount()):
            msg_item = self._signal_tree.topLevelItem(i)
            visible = False
            for j in range(msg_item.childCount()):
                sig_item = msg_item.child(j)
                match = text in sig_item.text(0).lower()
                sig_item.setHidden(not match)
                if match:
                    visible = True
            msg_item.setHidden(not visible)
            if visible and text:
                msg_item.setExpanded(True)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """勾选变化 = 重新订阅 (中台按 signal_names 过滤推送)"""
        if item.data(0, Qt.ItemDataRole.UserRole) != "signal":
            return
        name = item.data(0, Qt.ItemDataRole.UserRole + 1).get('signal_name', '')
        checked = item.checkState(0) == Qt.CheckState.Checked
        if checked:
            self._watched.add(name)
        else:
            self._watched.discard(name)
            self._values.pop(name, None)
        self._rebuild_value_table()
        self._resubscribe()

    def _rebuild_value_table(self):
        self._value_table.setRowCount(0)
        self._rows.clear()
        for i in range(self._signal_tree.topLevelItemCount()):
            msg_item = self._signal_tree.topLevelItem(i)
            for j in range(msg_item.childCount()):
                sig_item = msg_item.child(j)
                data = sig_item.data(0, Qt.ItemDataRole.UserRole + 1) or {}
                name = data.get('signal_name', '')
                if name not in self._watched:
                    continue
                row = self._value_table.rowCount()
                self._value_table.insertRow(row)
                self._rows[name] = row
                self._value_table.setItem(row, 0, QTableWidgetItem(name))
                self._value_table.setItem(
                    row, 1, QTableWidgetItem(data.get('message_name', '')))
                self._value_table.setItem(row, 2, QTableWidgetItem(""))
                self._value_table.setItem(row, 3, QTableWidgetItem(""))
                self._value_table.setItem(
                    row, 4, QTableWidgetItem(data.get('unit', '')))
                self._value_table.setItem(row, 5, QTableWidgetItem(""))

    # ------------------------------------------------------------------ #
    #  订阅与推送
    # ------------------------------------------------------------------ #

    def _resubscribe(self):
        channels = [self._channel_key] if self._channel_key else None
        filt = {'signal_names': set(self._watched)}
        if self._hub.get_subscription(self._sub_id):
            self._hub.update_subscription(
                self._sub_id, kinds={KIND_SIGNAL}, channels=channels,
                filter=filt)
        else:
            self._hub.register(self._sub_id, {KIND_SIGNAL},
                               channels=channels, filter=filt)

    def _on_push(self, sid: str, kind: str, payload):
        """中台推送 - 只缓存展示值"""
        if sid != self._sub_id or kind != KIND_SIGNAL:
            return
        for dto in payload:
            if dto.name in self._rows:
                self._values[dto.name] = dto

    def _refresh_values(self):
        for name, dto in self._values.items():
            row = self._rows.get(name)
            if row is None:
                continue
            val_item = self._value_table.item(row, 2)
            if val_item:
                new_text = f"{dto.phys:.4g}"
                if val_item.text() != new_text:
                    old = val_item.text()
                    val_item.setText(new_text)
                    # 值变化高亮 (涨绿跌红)
                    try:
                        if old and float(old) < dto.phys:
                            val_item.setBackground(QColor("#c8e6c9"))
                        else:
                            val_item.setBackground(QColor("#ffcdd2"))
                    except ValueError:
                        pass
            self._value_table.setItem(
                row, 3, QTableWidgetItem(self._ui.fmt_int(dto.raw)))
            self._value_table.setItem(
                row, 5, QTableWidgetItem(dto.value_desc or ""))

    # ------------------------------------------------------------------ #
    #  交互
    # ------------------------------------------------------------------ #

    def _on_cell_double_click(self, row: int, col: int):
        """双击行 - 注册为全局变量 (供Panel/Script绑定)"""
        item = self._value_table.item(row, 0)
        if not item:
            return
        dto = self._values.get(item.text())
        self._var_registry.set_value(item.text(), dto.phys if dto else 0)
        logger.info(f"信号已注册为变量: {item.text()}")

    def _on_channel_changed(self, text: str):
        self._channel_key = text
        self._rebuild_tree()

    def set_channel(self, channel_key: str):
        """切换通道 (重新订阅)"""
        self._channel_key = channel_key or ""
        self._refresh_channel_combo()
        self._rebuild_tree()

    def closeEvent(self, event):
        self._hub.unregister(self._sub_id)
        super().closeEvent(event)
