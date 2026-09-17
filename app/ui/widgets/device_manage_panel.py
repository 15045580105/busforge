"""
当前工程设备管理面板 - 全局唯一实例 (ADS dock)

职责: 管理当前工程的物理设备 + 将工程树创建的软件通道绑定到设备硬件通道。
两栏布局 (连接由"运行工程"自动完成, 故不再提供设备参数表单/手动连接):
- 左: 设备列表 (按 vendor/bus_type 分组, 状态灯; 设备用 型号·序列号 区分;
       右键/按钮枚举硬件添加设备)
- 右: 软件通道表 (通道在工程树 CAN/LIN 下添加; 表内直接选择"设备"/"硬件通道"
       完成绑定, 点行内【设备参数配置】设波特率/FD/只听/终端电阻/DBC)
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QLabel,
    QMessageBox, QAbstractItemView, QDialog, QMenu, QComboBox, QSpinBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap, QPainter, QCursor

from app.core.device_manager import DeviceManager, DeviceState
from app.core.data_hub import DataHub
from app.core.ui_settings import UISettings
from app.core.i18n import tr

logger = logging.getLogger(__name__)

# 状态灯颜色
_STATE_COLORS = {
    "disconnected": "#9aa9b5",   # 灰
    "connected": "#39b568",      # 绿
    "acquired": "#2f7fd0",       # 蓝 (运行占有)
    "error": "#d0453e",          # 红
}

# 通道表列 (设备/硬件通道表内直接编辑; 其余参数收拢到 ChannelParamDialog)
CH_COLS = ["软件通道", "设备", "硬件通道", "参数配置", "状态"]


def _state_icon(color: str) -> QIcon:
    pm = QPixmap(12, 12)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(2, 2, 8, 8)
    p.end()
    return QIcon(pm)


class DeviceManagePanel(QWidget):
    """当前工程设备管理面板 (单实例)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dm = DeviceManager.instance()
        self._hub = DataHub.instance()
        self._ui = UISettings.instance()
        self._loading = False
        self._inline_editing = False
        self._current_device: str = ""

        self._setup_ui()
        self._connect_signals()
        self.reload_all()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- 左: 设备列表 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel(tr("设备池 (未选择工程)"))
        f = self._title_label.font()
        f.setBold(True)
        self._title_label.setFont(f)
        left_layout.addWidget(self._title_label)
        self._dev_tree = QTreeWidget()
        self._dev_tree.setHeaderHidden(True)
        self._dev_tree.itemSelectionChanged.connect(self._on_device_selected)
        self._dev_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._dev_tree.customContextMenuRequested.connect(self._on_dev_tree_menu)
        left_layout.addWidget(self._dev_tree)

        self._add_dev_btn = QPushButton(tr("添加设备..."))
        self._add_dev_btn.clicked.connect(self._on_add_device)
        left_layout.addWidget(self._add_dev_btn)
        self._del_dev_btn = QPushButton(tr("移除选中设备"))
        self._del_dev_btn.clicked.connect(self._on_remove_device)
        left_layout.addWidget(self._del_dev_btn)
        splitter.addWidget(left)

        # ---- 右: 软件通道表 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._ch_hint = QLabel(tr(
            "软件通道表 (通道在左侧工程树 CAN/LIN 下添加; "
            "表内直接选\"设备\"/\"硬件通道\"完成绑定, "
            "点【设备参数配置】设波特率/FD/DBC 等)"))
        right_layout.addWidget(self._ch_hint)
        self._ch_table = QTableWidget()
        self._ch_table.setColumnCount(len(CH_COLS))
        self._ch_table.setHorizontalHeaderLabels([tr(c) for c in CH_COLS])
        # 名称/设备列自适应拉伸, 其余按内容, 避免横向滚动条
        hdr = self._ch_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (2, 3, 4):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._ch_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        right_layout.addWidget(self._ch_table)
        splitter.addWidget(right)

        splitter.setSizes([280, 660])
        layout.addWidget(splitter)

    def _connect_signals(self):
        self._dm.device_state_changed.connect(self._on_state_changed)
        self._dm.channel_state_changed.connect(self._on_channel_state)
        self._dm.pool_changed.connect(self.reload_all)
        # 语言切换 -> 重译 (静态文本 + 重建动态列表)
        self._ui.language_changed.connect(lambda _l: self.retranslateUi())

    def retranslateUi(self):
        """按当前语言重设静态文本并重建动态内容"""
        self._add_dev_btn.setText(tr("添加设备..."))
        self._del_dev_btn.setText(tr("移除选中设备"))
        self._ch_hint.setText(tr(
            "软件通道表 (通道在左侧工程树 CAN/LIN 下添加; "
            "表内直接选\"设备\"/\"硬件通道\"完成绑定, "
            "点【设备参数配置】设波特率/FD/DBC 等)"))
        self._ch_table.setHorizontalHeaderLabels([tr(c) for c in CH_COLS])
        self._update_title()
        self.reload_all()

    # ------------------------------------------------------------------ #
    #  公共API
    # ------------------------------------------------------------------ #

    def show_device(self, device_id: str):
        """定位到指定设备"""
        if device_id in self._dm._devices:
            self._select_device(device_id)

    def show_channel(self, channel_key: str):
        """定位到指定软件通道 (选中其所在行)"""
        ch = self._dm.get_channel(channel_key)
        if ch and ch.device_id:
            self._select_device(ch.device_id)
        for row in range(self._ch_table.rowCount()):
            item = self._ch_table.item(row, 0)
            if item and item.text() == channel_key:
                self._ch_table.selectRow(row)
                break

    # ------------------------------------------------------------------ #
    #  刷新
    # ------------------------------------------------------------------ #

    def reload_all(self):
        if self._inline_editing:   # 表内编辑触发的 pool_changed 不重建(避免销毁正在发信号的控件)
            return
        self.reload_devices()
        self.reload_channels()

    def _update_title(self):
        name = self._dm.active_project_name
        self._title_label.setText(
            tr("设备池 (工程: {name})").format(name=name) if name
            else tr("设备池 (未选择工程)"))

    def reload_devices(self):
        self._update_title()
        self._loading = True
        self._dev_tree.clear()
        devices = self._dm.list_devices()
        if not devices:
            hint_text = (tr("当前工程暂无设备, 点击【添加设备】枚举硬件")
                         if self._dm.active_project
                         else tr("请先创建或选择一个工程"))
            hint = QTreeWidgetItem(self._dev_tree, [hint_text])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            font = hint.font(0)
            font.setItalic(True)
            hint.setFont(0, font)
            self._loading = False
            return
        groups: dict[str, QTreeWidgetItem] = {}
        for dev in devices:
            gname = f"{dev.vendor} ({dev.bus_type.upper()})"
            if gname not in groups:
                g = QTreeWidgetItem(self._dev_tree, [gname])
                g.setFlags(g.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                groups[gname] = g
            item = QTreeWidgetItem(groups[gname], [dev.device_id])
            item.setData(0, Qt.ItemDataRole.UserRole, dev.device_id)
            self._paint_device_item(item, dev.device_id)
            item.setExpanded(True)
        for g in groups.values():
            g.setExpanded(True)
        self._loading = False

    def _device_display_state(self, device_id: str) -> str:
        dev = self._dm.get_device(device_id)
        if not dev:
            return "disconnected"
        if dev.state == DeviceState.ERROR:
            return "error"
        if dev.state == DeviceState.CONNECTED:
            return "acquired" if self._dm.is_acquired(device_id) else "connected"
        return "disconnected"

    def _paint_device_item(self, item: QTreeWidgetItem, device_id: str):
        """设备项: 状态灯 + 型号·序列号 (设备以类型/序列号区分)"""
        st = self._device_display_state(device_id)
        item.setIcon(0, _state_icon(_STATE_COLORS.get(st, "#9aa9b5")))
        dev = self._dm.get_device(device_id)
        if dev:
            ident = dev.model or dev.vendor
            tail = dev.serial or f"idx{dev.index}"
            base = f"{ident} · {tail}" if tail else ident
        else:
            base = device_id
        suffix = tr("  [运行中]") if st == "acquired" else ""
        item.setText(0, f"{base}{suffix}")
        item.setToolTip(0, device_id)

    def _refresh_device_items(self):
        for i in range(self._dev_tree.topLevelItemCount()):
            g = self._dev_tree.topLevelItem(i)
            for j in range(g.childCount()):
                item = g.child(j)
                did = item.data(0, Qt.ItemDataRole.UserRole)
                if did:
                    self._paint_device_item(item, did)

    def reload_channels(self):
        self._loading = True
        self._ch_table.setRowCount(0)
        devices = self._dm.list_devices()
        for ch in self._dm.list_channels():
            row = self._ch_table.rowCount()
            self._ch_table.insertRow(row)
            connected = self._dm.channel_state(ch.key) == "connected"

            # col0 软件通道 (只读)
            key_item = QTableWidgetItem(ch.key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._ch_table.setItem(row, 0, key_item)

            # col1 设备 (下拉直接绑定; 仅列同总线类型设备)
            devs = [d for d in devices if d.bus_type == ch.bus_type] or devices
            dev_combo = QComboBox()
            dev_combo.addItem(tr("(未绑定)"), "")
            for d in devs:
                dev_combo.addItem(f"{d.device_id}  [{d.model or d.vendor}]",
                                  d.device_id)
            di = dev_combo.findData(ch.device_id or "")
            dev_combo.setCurrentIndex(di if di >= 0 else 0)
            if not devs:
                dev_combo.setToolTip(
                    tr("无可选设备, 请先在左侧【添加设备】枚举硬件"))
            dev_combo.currentIndexChanged.connect(
                lambda _i, k=ch.key, c=dev_combo: self._on_inline_device(k, c))
            self._ch_table.setCellWidget(row, 1, dev_combo)

            # col2 硬件通道 (表内直接设置)
            hw_spin = QSpinBox()
            hw_spin.setRange(1, 16)
            hw_spin.setValue(int(ch.hw_channel or 1))
            hw_spin.valueChanged.connect(
                lambda v, k=ch.key: self._on_inline_hw(k, v))
            self._ch_table.setCellWidget(row, 2, hw_spin)

            # col3 设备参数配置 (行内按钮开弹窗: 波特率/FD/只听/电阻/DBC)
            cfg_btn = QPushButton(tr("设备参数配置"))
            cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cfg_btn.clicked.connect(
                lambda checked, k=ch.key: self._on_channel_param(k))
            self._ch_table.setCellWidget(row, 3, cfg_btn)

            # col4 状态 (只读)
            st_item = QTableWidgetItem(self._dm.channel_state(ch.key))
            st_item.setFlags(st_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._ch_table.setItem(row, 4, st_item)

            # 连接中: 禁止改绑定/参数 (需先终止工程)
            if connected:
                dev_combo.setEnabled(False)
                hw_spin.setEnabled(False)
                cfg_btn.setEnabled(False)
        self._loading = False

    # ------------------------------------------------------------------ #
    #  设备操作
    # ------------------------------------------------------------------ #

    def _on_device_selected(self):
        items = self._dev_tree.selectedItems()
        if not items:
            return
        device_id = items[0].data(0, Qt.ItemDataRole.UserRole)
        if device_id:
            self._current_device = device_id

    def _select_device(self, device_id: str):
        for i in range(self._dev_tree.topLevelItemCount()):
            g = self._dev_tree.topLevelItem(i)
            for j in range(g.childCount()):
                item = g.child(j)
                if item.data(0, Qt.ItemDataRole.UserRole) == device_id:
                    self._dev_tree.setCurrentItem(item)
                    self._current_device = device_id
                    return

    def _on_add_device(self):
        """枚举硬件添加设备到当前工程"""
        if self._dm.active_project is None:
            QMessageBox.warning(self, tr("提示"), tr("请先创建或选择一个工程"))
            return
        menu = QMenu(self)
        self._populate_add_device_menu(menu)
        menu.exec(QCursor.pos())

    def _on_dev_tree_menu(self, pos):
        """设备树右键: 添加设备 / 移除选中设备"""
        menu = QMenu(self)
        add = menu.addMenu(tr("添加设备"))
        self._populate_add_device_menu(add)
        item = self._dev_tree.itemAt(pos)
        did = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if did:
            menu.addSeparator()
            menu.addAction(tr("移除选中设备"), lambda: self._remove_device_by_id(did))
        menu.exec(self._dev_tree.viewport().mapToGlobal(pos))

    def _populate_add_device_menu(self, menu):
        """填充"创建 XXX 设备"厂商子菜单 (枚举硬件)"""
        can_menu = menu.addMenu(tr("CAN设备"))
        for v in ["TSMaster", "Vector", "ZLG", "Virtual"]:
            can_menu.addAction(tr("创建{v}设备").format(v=v),
                               lambda vt=v: self._create_device(vt, "can"))
        lin_menu = menu.addMenu(tr("LIN设备"))
        lin_menu.addAction(tr("创建{v}设备").format(v="TSMaster"),
                           lambda: self._create_device("TSMaster", "lin"))

    def _create_device(self, vendor, bus_type):
        """枚举并添加物理设备到当前工程 (不自动建通道, 通道在工程树添加)"""
        if self._dm.active_project is None:
            QMessageBox.warning(self, tr("提示"), tr("请先创建或选择一个工程"))
            return
        from app.ui.device_dialog import DeviceSelectDialog
        dialog = DeviceSelectDialog(vendor, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        info = dialog.get_selected_device() or {}
        dev = self._dm.add_device(
            vendor, model=info.get('model', vendor),
            serial=info.get('serial', ''), index=info.get('index', 0),
            bus_type=bus_type)
        if dev is None:
            QMessageBox.warning(self, tr("提示"), tr("请先创建或选择一个工程"))
            return
        self.reload_all()
        self._select_device(dev.device_id)
        logger.info(f"设备已添加到工程: {dev.device_id}")

    def _on_remove_device(self):
        self._remove_device_by_id(self._current_device)

    def _remove_device_by_id(self, device_id: str):
        if not device_id:
            QMessageBox.warning(self, tr("提示"), tr("请先在左侧选择设备"))
            return
        if self._dm.is_connected(device_id):
            QMessageBox.warning(self, tr("提示"), tr("设备连接中, 请先终止工程再移除"))
            return
        bound = [c.key for c in self._dm.channels_of_device(device_id)]
        msg = tr("从当前工程移除设备 '{device_id}'?").format(device_id=device_id)
        if bound:
            msg += "\n" + tr("绑定到它的通道 {bound} 将变为未绑定。").format(bound=bound)
        reply = QMessageBox.question(self, tr("确认移除"), msg)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._dm.remove_device(device_id)
        if self._current_device == device_id:
            self._current_device = ""
        self.reload_all()

    def _on_state_changed(self, device_id: str, state: str):
        self._refresh_device_items()
        self.reload_channels()

    def _on_channel_state(self, channel_key: str, state: str):
        self.reload_channels()

    # ------------------------------------------------------------------ #
    #  软件通道操作
    # ------------------------------------------------------------------ #

    def _on_inline_device(self, key: str, combo):
        """表内下拉选择设备 -> 直接绑定/解绑 (不整表重建)"""
        if self._loading:
            return
        dev_id = combo.currentData() or ""
        self._inline_editing = True
        try:
            ok, err = self._dm.bind_channel(key, dev_id)
        finally:
            self._inline_editing = False
        if not ok:
            QMessageBox.warning(self, tr("绑定失败"), err)
            QTimer.singleShot(0, self.reload_channels)

    def _on_inline_hw(self, key: str, value: int):
        """表内设置硬件通道号"""
        if self._loading:
            return
        self._inline_editing = True
        try:
            ok, err = self._dm.update_channel(key, hw_channel=value)
        finally:
            self._inline_editing = False
        if not ok:
            QMessageBox.warning(self, tr("修改失败"), err)
            QTimer.singleShot(0, self.reload_channels)

    def _on_channel_param(self, key: str):
        """打开设备参数配置 (波特率/FD/数据波特率/只听/终端电阻)"""
        ch = self._dm.get_channel(key)
        if not ch:
            return
        if self._dm.channel_state(key) == "connected":
            QMessageBox.warning(self, tr("提示"), tr("通道连接中, 请先终止工程再配置"))
            return
        from app.ui.device_dialog import ChannelParamDialog
        dlg = ChannelParamDialog(key, ch, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        r = dlg.get_result()
        self._dm.update_channel(
            key, baud_rate=r['baud_rate'], is_fd=r['is_fd'],
            data_baud_rate=r['data_baud_rate'],
            listen_only=r['listen_only'],
            terminal_resistor=r['terminal_resistor'])
        self.reload_channels()
