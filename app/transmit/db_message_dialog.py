"""
DbMessagePickerDialog - 跨通道数据库报文选择对话框

用于"仿真发送"面板的【从数据库添加帧】: 遍历全部通道的全部 DBC,
按 通道 → 数据库 → 报文 三级层级展示; 报文行显示 报文名 / ID / DLC /
发送节点; 顶部搜索框支持按 报文名 或 ID (兼容十六进制与十进制) 实时过滤。

数据源为 DataHub.all_channel_dbc(); ID 格式化复用 UISettings.fmt_id,
与全局进制显示保持一致。选中报文后 get_selected() 返回 (channel_key,
DbcMessage), 由调用方构造发送帧。
"""

import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QDialogButtonBox,
    QMessageBox, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer

from app.common.i18n import tr

logger = logging.getLogger(__name__)

# 节点数据角色 (存储 {'kind':..., 'channel':..., 'msg'/... })
_ROLE = Qt.ItemDataRole.UserRole

# 列索引
COL_NAME, COL_ID, COL_DLC, COL_SENDER = range(4)


class DbMessagePickerDialog(QDialog):
    """从全部通道的全部数据库中按层级选择一个报文"""

    def __init__(self, hub, ui, parent=None):
        super().__init__(parent)
        self._hub = hub
        self._ui = ui
        self.setWindowTitle(tr("从数据库添加帧"))
        self.setMinimumWidth(600)
        self.setMinimumHeight(480)
        self._setup_ui()
        self._build_tree()

    # ------------------------------------------------------------------ #
    #  UI 构建
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 筛选行: 通道下拉 + 搜索框 (按通道和报文名/ID 筛选)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._channel_combo = QComboBox()
        self._channel_combo.addItem(tr("全部通道"), "")
        for ch in sorted(self._hub.all_channel_dbc().keys()):
            self._channel_combo.addItem(ch, ch)
        self._channel_combo.currentIndexChanged.connect(
            lambda _i: self._on_search(self._search_edit.text()))
        filter_row.addWidget(self._channel_combo)
        self._search_edit = QLineEdit()
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setPlaceholderText(tr("输入报文名或ID进行过滤"))
        self._search_edit.textChanged.connect(self._on_search)
        filter_row.addWidget(self._search_edit, 1)
        layout.addLayout(filter_row)

        # 层级树: 通道 → 数据库 → 报文
        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.itemActivated.connect(self._on_item_activated)
        hdr = self._tree.header()
        # 全部列 Interactive: 用户可拖动任意列边界; 配合 resizeEvent 等比缩放填满视口
        for col in (COL_NAME, COL_ID, COL_DLC, COL_SENDER):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        layout.addWidget(self._tree, 1)
        # 初始宽度即等比缩放的比例权重
        for col, w in [(COL_NAME, 260), (COL_ID, 90),
                       (COL_DLC, 60), (COL_SENDER, 140)]:
            self._tree.setColumnWidth(col, w)

        # 用法提示
        tip = QLabel(tr(
            "选择报文后点【确定】添加到发送列表; 双击可直接添加; "
            "支持按报文名或ID搜索。"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #666666;")
        layout.addWidget(tip)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.retranslateUi()

    def retranslateUi(self):
        """按当前语言重设表头/提示 (对话框为一次性弹出, 构造时翻译即可)"""
        self._tree.setHeaderLabels(
            [tr("名称"), tr("ID"), tr("DLC"), tr("发送节点")])
        self._channel_combo.setItemText(0, tr("全部通道"))

    # ------------------------------------------------------------------ #
    #  列宽自适应 (窗口缩放时各列等比放大/缩小以填满视口, 列宽仍可拖动)
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示后按初始比例填满视口 (延迟到布局完成)
        QTimer.singleShot(0, self._fit_columns_to_viewport)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_columns_to_viewport()

    def _fit_columns_to_viewport(self, total=None):
        """按各列当前宽度比例等比缩放, 使列宽之和恰好填满视口宽度。

        total 为 None 时取树视口实际宽度; 显式传入 total 便于离屏测试。
        用户拖动列边界只改单列宽度、不触发本方法, 故列宽仍可自由拖动。
        """
        if total is None:
            total = self._tree.viewport().width()
        n = self._tree.columnCount()
        if total <= 0 or n == 0:
            return
        widths = [self._tree.columnWidth(c) for c in range(n)]
        cur = sum(widths)
        if cur <= 0:
            return
        scaled = [max(24, int(w * total / cur)) for w in widths]
        scaled[-1] += total - sum(scaled)   # 累计取整误差补到末列, 保证填满
        self._tree.blockSignals(True)
        for c, w in enumerate(scaled):
            self._tree.setColumnWidth(c, w)
        self._tree.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  数据构建
    # ------------------------------------------------------------------ #

    def _build_tree(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        all_dbc = self._hub.all_channel_dbc()
        if not all_dbc:
            empty = QTreeWidgetItem(
                self._tree, [tr("(未找到数据库, 请先为通道导入 DBC)")])
            empty.setData(0, _ROLE, {'kind': 'empty'})
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._tree.blockSignals(False)
            return

        total_msgs = 0
        for ch_key in sorted(all_dbc.keys()):
            dbc_list = all_dbc[ch_key]
            ch_count = sum(len(d.messages) for d in dbc_list)
            total_msgs += ch_count
            ch_item = QTreeWidgetItem(
                self._tree, [f"{ch_key} ({ch_count})", "", "", ""])
            ch_item.setData(0, _ROLE, {'kind': 'channel', 'channel': ch_key})
            ch_item.setExpanded(True)

            for dbc in dbc_list:
                db_item = QTreeWidgetItem(
                    ch_item,
                    [f"{dbc.name} ({len(dbc.messages)})", "", "", ""])
                db_item.setData(0, _ROLE, {
                    'kind': 'dbc', 'channel': ch_key, 'dbc_name': dbc.name})
                db_item.setExpanded(True)

                for msg in sorted(dbc.messages,
                                  key=lambda m: (m.message_id, m.name)):
                    m_item = QTreeWidgetItem(db_item, [
                        msg.name,
                        self._ui.fmt_id(msg.message_id),
                        str(msg.dlc),
                        msg.sender or "",
                    ])
                    m_item.setData(0, _ROLE, {
                        'kind': 'msg', 'channel': ch_key, 'msg': msg})
                    m_item.setToolTip(
                        COL_NAME, f"{msg.name}  [{self._ui.fmt_id(msg.message_id)}]")

        self._tree.blockSignals(False)
        logger.info(f"报文选择对话框已构建: {len(all_dbc)} 通道, "
                    f"{total_msgs} 报文")

    # ------------------------------------------------------------------ #
    #  搜索过滤 (按报文名 / ID, 兼容 hex 与 dec)
    # ------------------------------------------------------------------ #

    def _on_search(self, text: str):
        text = text.strip().lower()
        sel_ch = self._channel_combo.currentData() or ""
        for i in range(self._tree.topLevelItemCount()):
            ch_item = self._tree.topLevelItem(i)
            ch_data = ch_item.data(0, _ROLE)
            if ch_data and ch_data.get('kind') == 'empty':
                continue
            if sel_ch and ch_data.get('channel') != sel_ch:
                ch_item.setHidden(True)   # 通道筛选: 隐藏非选中通道
                continue
            ch_visible = False
            for j in range(ch_item.childCount()):
                db_item = ch_item.child(j)
                db_visible = False
                for k in range(db_item.childCount()):
                    m_item = db_item.child(k)
                    match = (not text) or self._msg_matches(m_item, text)
                    m_item.setHidden(not match)
                    if match:
                        db_visible = True
                db_item.setHidden(not db_visible)
                if db_visible:
                    ch_visible = True
                    if text:
                        db_item.setExpanded(True)
            ch_item.setHidden(not ch_visible)
            if ch_visible and text:
                ch_item.setExpanded(True)

    def _msg_matches(self, item: QTreeWidgetItem, text: str) -> bool:
        data = item.data(0, _ROLE)
        if not data or data.get('kind') != 'msg':
            return False
        msg = data['msg']
        if text in msg.name.lower():
            return True
        mid = msg.message_id
        candidates = (
            self._ui.fmt_id(mid).lower(),   # 当前进制显示 (0x1A3 / 419)
            f"0x{mid:x}",                   # 十六进制带前缀
            f"{mid:x}",                     # 十六进制无前缀
            str(mid),                       # 十进制
        )
        return any(text in c for c in candidates)

    # ------------------------------------------------------------------ #
    #  选择 / 确认
    # ------------------------------------------------------------------ #

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int):
        """双击: 报文行直接确认; 通道/数据库行切换展开"""
        data = item.data(0, _ROLE)
        if data and data.get('kind') == 'msg':
            self.accept()
        else:
            item.setExpanded(not item.isExpanded())

    def get_selected(self):
        """返回选中报文 (channel_key, DbcMessage); 非报文行返回 None"""
        item = self._tree.currentItem()
        if item is None:
            return None
        data = item.data(0, _ROLE)
        if not data or data.get('kind') != 'msg':
            return None
        return data['channel'], data['msg']

    def accept(self):
        """未选中报文时不允许确认"""
        if self.get_selected() is None:
            QMessageBox.information(self, tr("提示"), tr("请选择一个报文"))
            return
        super().accept()
