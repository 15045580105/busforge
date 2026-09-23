"""
TransmitPanel - 仿真发送面板 (参照 zxdoc 报文发送界面)

统一取代原 IG(手动发送) 与 Generator(报文序列): 不再挂到通道下,
而是作为 Monitor 下的独立面板, 每行自带【通道】列, 使用更直观。

布局 (与 zxdoc 发送窗口一致):
1. 工具栏: 启动/停止全部 | 添加 CAN/CAN FD/数据库帧 | 删除 | 上移/下移
2. 发送列表 (树表, 支持"序列"嵌套成员帧):
   列: 触发 | 启用 | 名称 | 通道 | ID | 类型 | 长度 | 次数 | 周期(ms)
   - 次数=0 表示无穷(周期发送), 否则按次数+间隔发送
   - 进度=已发送计数
   - 序列行: 触发后按间隔顺序发送其成员帧, 可重复次数次
3. 信号/原始数据场: 随选中帧行联动 (数据库帧->信号, 自定义帧->原始数据)

发送走 DeviceManager; 数据库帧编码走 DataHub 解析层 CanCodec。
全部文本经 tr(), 订阅 UISettings.language_changed 实现中英文实时切换。
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget, QTreeWidget, QTreeWidgetItem,
    QTableWidgetItem, QHeaderView, QPushButton, QLabel, QLineEdit, QSpinBox,
    QComboBox, QAbstractItemView, QDialog, QSplitter, QStyledItemDelegate,
    QAbstractSpinBox, QApplication, QMenu, QToolButton, QFrame
)
from PySide6.QtCore import Qt, QTimer, QEvent, QPoint, QRect, QRectF, Signal, \
    QItemSelection, QItemSelectionModel, QRegularExpression
from PySide6.QtGui import QFont, QPainter, QColor, QPainterPath, QBrush, \
    QKeySequence, QRegularExpressionValidator, QIcon, QPixmap

from app.devices.device_manager import DeviceManager
from app.datahub.data_hub import DataHub
from app.common.ui_settings import UISettings
from app.common.i18n import tr
from app.transmit.db_message_dialog import DbMessagePickerDialog
from app.ui.toolbar_widget import _ToolButton

logger = logging.getLogger(__name__)

# 报文类型 (与 zxdoc/CANoe 一致: 标准/扩展 × 数据/远程 × CAN/CAN FD/FD加速)
FRAME_TYPES = [
    "CAN数据帧", "扩展CAN数据帧", "CAN远程帧", "扩展CAN远程帧",
    "CAN FD数据帧", "扩展CAN FD数据帧",
    "CAN FD数据帧(加速)", "扩展CAN FD数据帧(加速)",
]
# 类型 -> (is_extended, is_remote, is_fd, is_brs); 索引与 FRAME_TYPES 一一对应
FRAME_TYPE_FLAGS = [
    (False, False, False, False),   # CAN数据帧
    (True,  False, False, False),   # 扩展CAN数据帧
    (False, True,  False, False),   # CAN远程帧
    (True,  True,  False, False),   # 扩展CAN远程帧
    (False, False, True,  False),   # CAN FD数据帧
    (True,  False, True,  False),   # 扩展CAN FD数据帧
    (False, False, True,  True),    # CAN FD数据帧(加速, BRS)
    (True,  False, True,  True),    # 扩展CAN FD数据帧(加速, BRS)
]


def _flags_to_type_index(meta: dict) -> int:
    flags = (bool(meta.get('is_extended')), bool(meta.get('is_remote')),
             bool(meta.get('is_fd')), bool(meta.get('is_brs')))
    return FRAME_TYPE_FLAGS.index(flags) if flags in FRAME_TYPE_FLAGS else 0

_META_ROLE = Qt.ItemDataRole.UserRole + 3

# 列索引
COL_TRIG, COL_EN, COL_NAME, COL_CH, COL_ID, COL_TYPE, \
    COL_LEN, COL_COUNT, COL_INTV = range(9)


class _TriggerDelegate(QStyledItemDelegate):
    """触发列自绘按钮: 精确填充满单元格。

    setItemWidget 的控件几何不会填满列宽 (探针验证), 故触发列改用
    delegate 在 paint 中按 option.rect 自绘 soft 语义按钮, 点击由
    editorEvent 捕获并回调面板 _on_trigger。
    """

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel

    def createEditor(self, parent, option, index):
        """触发列只是自绘按钮, 禁止弹编辑器
        (行级 ItemIsEditable 波及所有列, 双击/键入会在按钮上开文本框并吞掉点击)"""
        return None

    def _meta_of(self, index):
        item = self._panel._tree.itemFromIndex(index)
        meta = self._panel._item_meta(item) if item is not None else None
        return meta, item

    def _cell_rect(self, option, index):
        """单元格真实矩形: 用列宽累加计算, 不受列0 indentation 内缩影响"""
        tree = self._panel._tree
        x = sum(tree.columnWidth(c) for c in range(index.column()))
        w = tree.columnWidth(index.column())
        return QRectF(x + 2, option.rect.y() + 2, w - 4,
                      option.rect.height() - 4)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        meta, _item = self._meta_of(index)
        if meta is None:
            return
        running = meta.get('timer') is not None
        rect = self._cell_rect(option, index)
        if running:
            bg, fg, bd, text = QColor("#f5e6e4"), QColor("#a5372f"), \
                QColor("#dcbcb8"), tr("停止")
        else:
            bg, fg, bd, text = QColor("#e6eef6"), QColor("#35618f"), \
                QColor("#b9cfe2"), tr("发送")
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.fillPath(path, QBrush(bg))
        painter.setPen(bd)
        painter.drawPath(path)
        painter.setPen(fg)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease:
            meta, item = self._meta_of(index)
            if meta is not None and self._cell_rect(option, index).contains(
                    event.pos()):
                self._panel._on_trigger(meta, item)
                return True
        return super().editorEvent(event, model, option, index)


class _NoEditDelegate(QStyledItemDelegate):
    """禁止单元格弹出编辑器 (行级 ItemIsEditable 波及全部列, 按列 delegate 拦截;
    勾选/下拉/只读列用, QStyledItemDelegate.editorEvent 的勾选切换不受影响)"""

    def createEditor(self, parent, option, index):
        return None


class _RawTable(QTableWidget):
    """数据 hex dump 表: 十六进制编辑器式逐字节连续选中 / 复制 / 粘贴 / 右键菜单"""

    paste_hex = Signal(str)
    copy_hex = Signal()
    hex_typed = Signal(int, int)   # (字节索引, 字节值) 选中后直接键入 hex 回写

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anchor = -1      # 选区锚点字节索引
        self._dragging = False
        self._nibble = -1      # 已键入的高半字节 (-1=无待配对半字节)
        self._nibble_byte = -1 # 半字节所属字节索引

    # ---------------- 逐字节连续选区 (跨行续接) ---------------- #

    def _byte_at(self, pos):
        """视口坐标 -> 字节索引 (仅 1..16 数据列, 空单元格返回 None)"""
        idx = self.indexAt(pos)
        if not idx.isValid():
            return None
        c = idx.column()
        if not (1 <= c <= 16):
            return None
        it = self.item(idx.row(), c)
        if it is None or not (it.flags() & Qt.ItemFlag.ItemIsEnabled):
            return None
        return idx.row() * 16 + (c - 1)

    def _apply_byte_selection(self, a: int, b: int):
        """选中 [a,b] 字节区间: 逐行映射为单元格选区 (非矩形, 跨行续接)"""
        lo, hi = min(a, b), max(a, b)
        sel = QItemSelection()
        for r in range(lo // 16, hi // 16 + 1):
            c1 = lo - r * 16 if r == lo // 16 else 0
            c2 = hi - r * 16 if r == hi // 16 else 15
            sel.select(self.model().index(r, 1 + c1),
                       self.model().index(r, 1 + c2))
        sm = self.selectionModel()
        sm.select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        sm.setCurrentIndex(
            self.model().index(b // 16, 1 + b % 16),
            QItemSelectionModel.SelectionFlag.NoUpdate)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            b = self._byte_at(event.position().toPoint())
            if b is not None:
                self._nibble = -1   # 点击移动光标, 取消半字节态
                # 先走默认按下处理维护 pressedIndex/焦点 (双击编辑依赖
                # pressedIndex==当前 index 才会进入 edit; 跳过 super 会永远弹不出编辑器),
                # 再覆盖为字节连续选区
                super().mousePressEvent(event)
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier \
                        and self._anchor >= 0:
                    self._apply_byte_selection(self._anchor, b)
                else:
                    self._anchor = b
                    self._apply_byte_selection(b, b)
                self._dragging = True
                self.setFocus()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            b = self._byte_at(event.position().toPoint())
            if b is not None:
                self._apply_byte_selection(self._anchor, b)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    def selected_byte_range(self):
        """选中的连续字节区间 (lo, hi); 无选中返回 None"""
        rng = [i.row() * 16 + (i.column() - 1)
               for i in self.selectedIndexes() if 1 <= i.column() <= 16]
        return (min(rng), max(rng)) if rng else None

    # ---------------- 快捷键 / 右键菜单 ---------------- #

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_hex.emit(QApplication.clipboard().text())
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_hex.emit()
            return
        # 选中字节后直接键入 hex 直写 (hex 编辑器式, 免双击):
        # 第 1 个字符置高半字节, 第 2 个字符合成完整字节并自动前进
        ch = event.text().lower()
        if len(ch) == 1 and ch in "0123456789abcdef" and not (
                event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                     | Qt.KeyboardModifier.AltModifier)):
            idx = self.currentIndex()
            it = self.item(idx.row(), idx.column()) if idx.isValid() else None
            if it is not None and 1 <= idx.column() <= 16 \
                    and (it.flags() & Qt.ItemFlag.ItemIsEnabled):
                b = idx.row() * 16 + (idx.column() - 1)
                if self._nibble >= 0 and self._nibble_byte == b:
                    self.hex_typed.emit(b, (self._nibble << 4) | int(ch, 16))
                    self._nibble = -1
                    self._advance_byte(b)
                else:
                    self._nibble = int(ch, 16)
                    self._nibble_byte = b
                    self.hex_typed.emit(b, self._nibble << 4)
                return
        self._nibble = -1   # 其他按键取消半字节态
        super().keyPressEvent(event)

    def _advance_byte(self, b: int):
        """字节输入完成后光标前进到下一字节 (越出数据区则停留)"""
        nb = b + 1
        it = self.item(nb // 16, 1 + nb % 16)
        if it is None or not (it.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        self._anchor = nb
        self._apply_byte_selection(nb, nb)

    def reset_input_state(self):
        """数据刷新/粘贴后清空半字节输入态"""
        self._nibble = -1

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_copy = menu.addAction(tr("复制"))
        act_paste = menu.addAction(tr("粘贴"))
        act = menu.exec(event.globalPos())
        if act == act_copy:
            self.copy_hex.emit()
        elif act == act_paste:
            self.paste_hex.emit(QApplication.clipboard().text())


class _HexByteDelegate(QStyledItemDelegate):
    """hex 字节格编辑器 (双击/F2 进入): 仅接受 1~2 位十六进制, 居中显示"""

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        # objectName 命中 styles.py 紧凑规则 (全局 QLineEdit padding 5px 8px
        # 会吃掉 27px 小格导致两位 hex 显示不全)
        ed.setObjectName("hexCellEditor")
        ed.setMaxLength(2)
        ed.setValidator(QRegularExpressionValidator(
            QRegularExpression("[0-9A-Fa-f]{1,2}"), ed))
        ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return ed

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        editor.selectAll()   # 全选原值, 键入即替换 (否则 maxLength=2 顶住输不进)


def _funnel_icon(active: bool) -> QIcon:
    """漏斗小图标: 激活态主题强调色, 未激活灰色"""
    pm = QPixmap(12, 12)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#4a7fb5" if active else "#8a919a"))
    path = QPainterPath()
    path.moveTo(1, 1)
    path.lineTo(11, 1)
    path.lineTo(7, 6)
    path.lineTo(7, 10)
    path.lineTo(5, 11)
    path.lineTo(5, 6)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pm)


class _FilterHeader(QHeaderView):
    """列头内嵌筛选按钮: 【通道】/【ID】列右侧漏斗按钮, 点击弹出筛选框。

    按钮作为表头子控件跟随列宽拖动/水平滚动/面板缩放重排; 列名单击仍触发
    sectionClicked 排序, 互不干扰。
    """

    filter_clicked = Signal(int)   # 列索引

    def __init__(self, tree):
        super().__init__(Qt.Orientation.Horizontal, tree)
        self._btns: dict[int, QToolButton] = {}
        self.sectionResized.connect(lambda *_a: self._relayout())
        # 水平滚动时列视口位置变化, 需重排筛选按钮
        tree.horizontalScrollBar().valueChanged.connect(
            lambda _v: self._relayout())

    def add_filter_button(self, col: int) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("hdrFilterBtn")
        btn.setFixedSize(16, 16)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _c=False, c=col: self.filter_clicked.emit(c))
        btn.show()
        self._btns[col] = btn
        QTimer.singleShot(0, self._relayout)
        return btn

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        """筛选按钮吸附各列右缘 (列过窄时隐藏, 避免遮挡列名)"""
        for col, b in self._btns.items():
            w = self.sectionSize(col)
            if w < 34:
                b.hide()
                continue
            b.show()
            b.move(self.sectionViewportPosition(col) + w - 19,
                   (self.height() - 16) // 2)


class TransmitPanel(QWidget):
    """仿真发送面板 - zxdoc 式统一发送列表 (帧 + 序列)"""

    state_dirty = Signal()   # 帧配置变化 -> 工程树自动保存

    def __init__(self, channel_key: str = "", parent=None):
        super().__init__(parent)
        self._channel_key = channel_key
        self._restoring_state = False   # 导入恢复期间抑制 state_dirty
        self._sort_col = -1             # 当前排序列 (-1=未排序)
        self._sort_asc = True
        self._pre_sort_keys = None      # 排序前顶层行 meta key 顺序 (取消排序时恢复)
        self._flt_ch = ""               # 列筛选: 通道 (''=不筛选)
        self._flt_id = ""               # 列筛选: ID 文本
        self._dm = DeviceManager.instance()
        self._hub = DataHub.instance()
        self._ui = UISettings.instance()
        # 硬件异步发送失败 -> 提示条警示 (dm侧已节流 2s/通道)
        _sf = getattr(self._dm, 'send_failed', None)
        if _sf is not None:
            _sf.connect(self._on_dm_send_failed)
        # 行 meta 权威存储: item 数据仅存 key (QTreeWidgetItem 存 dict 会返回副本)
        self._meta_store: dict[int, dict] = {}
        self._meta_next: int = 0

        self._setup_ui()
        self._connect_signals()
        self.retranslateUi()

    def _register_meta(self, meta: dict) -> int:
        self._meta_next += 1
        key = self._meta_next
        meta['_key'] = key
        self._meta_store[key] = meta
        return key

    def _unregister_meta(self, meta: Optional[dict]):
        if not meta:
            return
        self._meta_store.pop(meta.get('_key', -1), None)

    # ------------------------------------------------------------------ #
    #  UI 构建
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        self.setObjectName("transmitPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._auto_tab = True   # 仅用户选中报文时切换信号/数据 tab
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 1. 工具栏条块 (浅底+边框, 与下方内容明确分隔; 仿主工具栏图标竖排)
        toolbar_wrap = QWidget()
        toolbar_wrap.setObjectName("panelToolbar")
        toolbar_wrap.setAttribute(Qt.WA_StyledBackground, True)
        toolbar = QHBoxLayout(toolbar_wrap)
        toolbar.setContentsMargins(6, 4, 6, 4)
        toolbar.setSpacing(2)
        self._start_all_btn = _ToolButton("run", "启动", "启动")
        self._start_all_btn.clicked.connect(self._start_all)
        toolbar.addWidget(self._start_all_btn)
        self._stop_all_btn = _ToolButton("stop", "停止", "停止", True)
        self._stop_all_btn.clicked.connect(self._stop_all)
        toolbar.addWidget(self._stop_all_btn)
        toolbar.addSpacing(8)

        self._add_can_btn = _ToolButton("add_can", "添加 CAN 帧", "添加 CAN 帧")
        self._add_can_btn.clicked.connect(lambda: self._add_frame(False))
        toolbar.addWidget(self._add_can_btn)
        self._add_fd_btn = _ToolButton("add_fd", "添加 CAN FD 帧", "添加 CAN FD 帧")
        self._add_fd_btn.clicked.connect(lambda: self._add_frame(True))
        toolbar.addWidget(self._add_fd_btn)
        self._add_db_btn = _ToolButton("add_db", "从数据库添加帧", "从数据库添加帧")
        self._add_db_btn.clicked.connect(self._add_db_frame)
        toolbar.addWidget(self._add_db_btn)
        self._add_seq_btn = _ToolButton("add_seq", "添加序列", "添加序列")
        self._add_seq_btn.clicked.connect(self._add_sequence)
        toolbar.addWidget(self._add_seq_btn)
        toolbar.addSpacing(8)

        self._remove_btn = _ToolButton("remove_item", "删除选中", "删除选中", True)
        self._remove_btn.clicked.connect(self._remove_selected)
        toolbar.addWidget(self._remove_btn)
        self._up_btn = _ToolButton("move_up", "上移", "上移")
        self._up_btn.clicked.connect(lambda: self._move_selected(-1))
        toolbar.addWidget(self._up_btn)
        self._down_btn = _ToolButton("move_down", "下移", "下移")
        self._down_btn.clicked.connect(lambda: self._move_selected(1))
        toolbar.addWidget(self._down_btn)
        toolbar.addStretch()
        layout.addWidget(toolbar_wrap)

        # 用法提示 (柔和信息条)
        self._hint_label = QLabel()
        self._hint_label.setObjectName("hintBar")
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        # 2 + 3. 发送列表 / 信号数据场 (可拖拽分割)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(COL_INTV + 1)
        self._tree.setHeaderLabels([""] * (COL_INTV + 1))
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        # 单列头: 点【通道】/【ID】列名排序, 列右缘漏斗按钮弹筛选框
        hdr = _FilterHeader(self._tree)
        self._tree.setHeader(hdr)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setSectionsClickable(True)
        hdr.sectionClicked.connect(self._on_header_clicked)
        splitter.addWidget(self._tree)
        for col, w in [(COL_TRIG, 56), (COL_EN, 48), (COL_NAME, 140),
                       (COL_CH, 80), (COL_ID, 70), (COL_TYPE, 110),
                       (COL_LEN, 50), (COL_COUNT, 64), (COL_INTV, 70)]:
            self._tree.setColumnWidth(col, w)
        # 触发列自绘按钮 (填满单元格, 见 _TriggerDelegate)
        self._tree.setItemDelegateForColumn(COL_TRIG, _TriggerDelegate(self))
        # 行级 ItemIsEditable 波及所有列: 勾选/下拉/只读列按列禁止弹编辑器
        for col in (COL_EN, COL_CH, COL_TYPE, COL_LEN, COL_COUNT, COL_INTV):
            self._tree.setItemDelegateForColumn(col, _NoEditDelegate(self._tree))

        # 列头筛选: 【通道】/【ID】列右缘漏斗按钮, 点击弹出筛选框
        self._fbtn_ch = hdr.add_filter_button(COL_CH)
        self._fbtn_id = hdr.add_filter_button(COL_ID)
        hdr.filter_clicked.connect(self._on_filter_clicked)
        self._update_filter_icons()

        self._field_tabs = QTabWidget()
        self._signal_table = QTreeWidget()
        self._signal_table.setColumnCount(6)
        self._signal_table.setHeaderLabels([""] * 6)
        self._signal_table.setAlternatingRowColors(True)
        self._signal_table.header().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._signal_table.itemChanged.connect(self._on_phys_edited)
        self._field_tabs.addTab(self._signal_table, "")

        # 原始数据: hex dump 网格 (地址 | 16字节hex | ASCII), 单字节可编辑
        self._raw_table = _RawTable()
        self._raw_table.setColumnCount(18)
        self._raw_table.setAlternatingRowColors(True)
        self._raw_table.horizontalHeader().setVisible(False)
        self._raw_table.verticalHeader().setVisible(False)
        self._raw_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ContiguousSelection)
        self._raw_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        # 编辑方式: 选中字节后直接键入 hex 直写 (见 _RawTable.keyPressEvent);
        # 双击/F2 打开行内编辑器 (hex 校验, 见 _HexByteDelegate) 作为兜底;
        # 单击/拖选不进入编辑 (否则编辑器捕获鼠标无法拖选多行)
        self._raw_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed)
        self._raw_table.setItemDelegate(_HexByteDelegate(self._raw_table))
        self._raw_table.setFont(QFont("Consolas", 10))
        self._raw_table.itemChanged.connect(self._on_raw_byte_edited)
        self._raw_table.hex_typed.connect(self._on_hex_typed)
        self._raw_table.paste_hex.connect(self._on_raw_paste)
        self._raw_table.copy_hex.connect(self._on_raw_copy)
        self._raw_table.setColumnWidth(0, 46)
        for c in range(1, 17):
            self._raw_table.setColumnWidth(c, 28)
        self._raw_table.horizontalHeader().setSectionResizeMode(
            17, QHeaderView.ResizeMode.Stretch)
        self._field_tabs.addTab(self._raw_table, "")

        splitter.addWidget(self._field_tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        self._update_run_buttons()   # 初始: 无行 -> 启动/停止均禁用

    def _connect_signals(self):
        # 单例信号一律用绑定方法连接: C++ 对象销毁时自动断开;
        # lambda 连接不会自动断开, 工程切换丢弃本面板后再次发射将
        # 访问已删除的 C++ 对象 (闪退根因)
        self._hub.dbc_changed.connect(self._on_dbc_changed)
        self._hub.running_changed.connect(self._on_running_changed)
        self._dm.pool_changed.connect(self._on_pool_changed)
        self._ui.number_format_changed.connect(
            self._on_number_format_changed)
        self._ui.language_changed.connect(self._on_language_changed)

    def _on_pool_changed(self):
        self._refresh_channel_options()

    def _on_number_format_changed(self, _fmt):
        self._reformat_all()

    def _on_language_changed(self, _lang):
        self.retranslateUi()

    # ------------------------------------------------------------------ #
    #  列宽自适应 (面板缩放时发送列表各列等比填满视口, 列宽仍可拖动)
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_tree_columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_tree_columns()

    def _fit_tree_columns(self):
        """按各列当前宽度比例等比缩放, 使发送列表列宽之和填满视口 (无右侧空白)"""
        total = self._tree.viewport().width()
        n = self._tree.columnCount()
        if total <= 0 or n == 0:
            return
        widths = [self._tree.columnWidth(c) for c in range(n)]
        cur = sum(widths)
        if cur <= 0:
            return
        scaled = [max(30, int(w * total / cur)) for w in widths]
        scaled[-1] += total - sum(scaled)
        self._tree.blockSignals(True)
        for c, w in enumerate(scaled):
            self._tree.setColumnWidth(c, w)
        self._tree.blockSignals(False)
        # 列宽变化后刷新行内控件几何, 避免 setItemWidget 控件错位
        self._tree.doItemsLayout()
        # 表头筛选控件跟随列宽 (blockSignals 抑制了 sectionResized, 手动重排)
        hdr = self._tree.header()
        if hasattr(hdr, '_relayout'):
            hdr._relayout()

    # ------------------------------------------------------------------ #
    #  国际化
    # ------------------------------------------------------------------ #

    @staticmethod
    def _usage_hint_text() -> str:
        return tr(
            "用法: 添加帧或序列(序列可嵌套成员帧) → 每行选【通道】→ "
            "在下方改信号值(数据库帧)或数据(自定义帧: 选中字节后直接键入 hex, "
            "两位一字节自动前进) → 点该行【发送】; "
            "次数=0 为无穷周期发送, 否则按次数+周期发送; 【启动】发送全部启用行。")

    def retranslateUi(self):
        """按当前语言重设全部文本"""
        for btn in (self._start_all_btn, self._stop_all_btn, self._add_can_btn,
                    self._add_fd_btn, self._add_db_btn, self._add_seq_btn,
                    self._remove_btn, self._up_btn, self._down_btn):
            btn.setText(tr(btn._text_key))
            btn.setToolTip(tr(btn._tooltip_key))
        self._hint_label.setText(self._usage_hint_text())
        self._update_sort_marks()   # 表头列名 + 排序箭头
        self._field_tabs.setTabText(0, tr("信号"))
        self._field_tabs.setTabText(1, tr("数据"))
        self._signal_table.setHeaderLabels(
            [tr("信号"), tr("起始位"), tr("长度"), tr("总线值"),
             tr("物理值"), tr("单位")])
        # 刷新行内控件文本
        it = self._tree.invisibleRootItem()
        self._retranslate_items(it)

    def _retranslate_items(self, parent: QTreeWidgetItem):
        for i in range(parent.childCount()):
            item = parent.child(i)
            meta = self._item_meta(item)
            ctype = self._tree.itemWidget(item, COL_TYPE)
            if isinstance(ctype, QComboBox):
                for k, t in enumerate(FRAME_TYPES):
                    ctype.setItemText(k, tr(t))
            ccount = self._tree.itemWidget(item, COL_COUNT)
            if isinstance(ccount, QSpinBox):
                ccount.setSpecialValueText(tr("无穷"))
            self._retranslate_items(item)

    # ------------------------------------------------------------------ #
    #  行构建
    # ------------------------------------------------------------------ #

    def _channel_options(self) -> list:
        return [c.key for c in self._dm.list_channels()]

    def _new_frame_meta(self, is_fd: bool) -> dict:
        return {
            'kind': 'frame', 'src': 'custom', 'name': '', 'id': 0x000,
            'is_fd': is_fd, 'is_extended': False,
            'is_remote': False, 'is_brs': False,
            'data': bytearray(64 if is_fd else 8),
            'msg': None, 'phys': {},
            'channel': self._channel_key, 'enabled': True,
            'count': 1, 'interval': 100, 'progress': 0,
            'timer': None, '_remaining': 0,
        }

    def _new_seq_meta(self) -> dict:
        return {
            'kind': 'seq', 'name': tr("序列"), 'members': [],
            'channel': self._channel_key, 'enabled': True,
            'count': 1, 'interval': 100, 'progress': 0,
            'timer': None, '_seq_idx': 0, '_pass': 0,
        }

    def _add_frame(self, is_fd: bool):
        meta = self._new_frame_meta(is_fd)
        parent = self._selected_seq_item()
        self._append_frame_item(parent, meta)

    def _add_db_frame(self):
        """从全部通道的全部数据库中按 通道→数据库→报文 层级选报文添加帧"""
        parent = self._selected_seq_item()
        dlg = DbMessagePickerDialog(self._hub, self._ui, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = dlg.get_selected()
        if not sel:
            return
        ch, msg = sel
        meta = self._new_frame_meta(msg.is_fd or msg.dlc > 8)
        meta.update({
            'src': 'db', 'name': msg.name, 'id': msg.message_id,
            'msg': msg, 'phys': {s.name: 0.0 for s in msg.signals},
            'channel': ch,
        })
        self._append_frame_item(parent, meta)

    def _add_sequence(self):
        meta = self._new_seq_meta()
        item = self._make_item(None, meta)
        self._tree.addTopLevelItem(item)
        self._attach_item_widgets(item, meta)
        self._tree.setCurrentItem(item)

    def _selected_seq_item(self) -> Optional[QTreeWidgetItem]:
        """当前选中为序列行时返回该 item (新帧将作为其成员), 否则 None"""
        item = self._tree.currentItem()
        if item is None:
            return None
        meta = self._item_meta(item)
        if meta and meta['kind'] == 'seq':
            return item
        return None

    def _attach_item_widgets(self, item: QTreeWidgetItem, meta: dict):
        """item 入树后绑定行内控件 (setItemWidget 对未入树 item 静默失效, 必须入树后调用)"""
        for col, w in (meta.get('_w') or {}).items():
            if w is not None:
                self._tree.setItemWidget(item, col, w)

    def _reattach_row_widgets(self, item: QTreeWidgetItem):
        """take/insert 重排行后重挂行内控件 (含全部子孙行):
        setItemWidget 关联存于视图持久索引, 行被 take 后整棵子树的索引全部失效;
        且 Qt 可能对失效关联的旧控件延迟销毁, 直接复用旧控件重挂会访问已释放
        内存 (真实点击排序后闪退, 探针复现 access violation), 故重建全新控件
        挂接, 旧控件延迟销毁。"""
        meta = self._item_meta(item)
        if meta:
            old = list((meta.get('_w') or {}).values())
            meta['_w'] = self._create_row_widgets(item, meta)
            self._attach_item_widgets(item, meta)
            for w in old:
                if w is not None:
                    w.hide()
                    w.deleteLater()
        for i in range(item.childCount()):
            self._reattach_row_widgets(item.child(i))

    def _append_frame_item(self, parent: Optional[QTreeWidgetItem], meta: dict):
        item = self._make_item(parent, meta)
        if parent is None:
            self._tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
            parent.setExpanded(True)
            self._item_meta(parent)['members'].append(meta)
        self._attach_item_widgets(item, meta)
        self._auto_tab = False   # 添加帧不切换 tab
        self._tree.setCurrentItem(item)
        self._on_selection_changed()
        self._auto_tab = True
        self._apply_filter()   # 筛选激活时新帧立即参与过滤
        self._mark_dirty()
        self._update_run_buttons()
        return item

    def _make_item(self, parent: Optional[QTreeWidgetItem], meta: dict) \
            -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        is_seq = meta['kind'] == 'seq'

        # 启用
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                      | Qt.ItemFlag.ItemIsEnabled)
        item.setCheckState(COL_EN, Qt.CheckState.Checked if meta['enabled']
                           else Qt.CheckState.Unchecked)

        # 名称 (可编辑)
        item.setText(COL_NAME, meta['name'])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)

        if not is_seq:
            # ID (可编辑)
            item.setText(COL_ID, self._ui.fmt_id(meta['id']))
            if meta['src'] == 'custom':
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            # 长度
            item.setText(COL_LEN, str(self._frame_len(meta)))

        # 行内控件暂存到 meta (setItemWidget 须待 item 入树后调用, 见 _attach_item_widgets)
        meta['_w'] = self._create_row_widgets(item, meta)

        item.setData(COL_NAME, _META_ROLE, self._register_meta(meta))
        return item

    def _create_row_widgets(self, item: QTreeWidgetItem, meta: dict) -> dict:
        """创建行内控件 (通道/类型/次数/周期), 返回 {列: 控件} 暂存待入树后绑定。
        排序/移动重排后旧控件被 Qt 延迟销毁, 也走这里重建 (见 _reattach_row_widgets)。
        初始化期间阻断信号: 初始值来自 meta, 信号触发只会引发冗余回写/自动保存。"""
        is_seq = meta['kind'] == 'seq'
        made = []

        # 通道
        ch_combo = QComboBox()
        made.append(ch_combo)
        ch_combo.blockSignals(True)
        ch_combo.addItems(self._channel_options())
        if meta['channel'] in [ch_combo.itemText(i)
                               for i in range(ch_combo.count())]:
            ch_combo.setCurrentText(meta['channel'])
        elif ch_combo.count():
            meta['channel'] = ch_combo.currentText()
        ch_combo.currentTextChanged.connect(
            lambda _t, m=meta, it=item: self._on_widget_changed(m, it))

        widgets = {}
        if not is_seq:
            # 类型 (8 种: 按索引映射标志位, 不受语言切换影响)
            t_combo = QComboBox()
            made.append(t_combo)
            t_combo.blockSignals(True)
            t_combo.addItems([tr(t) for t in FRAME_TYPES])
            t_combo.setCurrentIndex(_flags_to_type_index(meta))
            t_combo.currentTextChanged.connect(
                lambda _t, m=meta, it=item: self._on_widget_changed(m, it))
            widgets[COL_TYPE] = t_combo

        # 次数 (0=无穷, 只编辑隐藏上下按钮)
        count_spin = QSpinBox()
        made.append(count_spin)
        count_spin.blockSignals(True)
        count_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        count_spin.setRange(0, 99999)
        count_spin.setSpecialValueText(tr("无穷"))
        count_spin.setValue(meta['count'])
        count_spin.valueChanged.connect(
            lambda _v, m=meta, it=item: self._on_widget_changed(m, it))

        # 周期 (只编辑, 隐藏上下按钮更易点)
        intv_spin = QSpinBox()
        made.append(intv_spin)
        intv_spin.blockSignals(True)
        intv_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        intv_spin.setRange(1, 60000)
        intv_spin.setValue(meta['interval'])
        intv_spin.valueChanged.connect(
            lambda _v, m=meta, it=item: self._on_widget_changed(m, it))

        for w in made:
            w.blockSignals(False)
        widgets.update({COL_CH: ch_combo,
                        COL_COUNT: count_spin, COL_INTV: intv_spin})
        return widgets

    def _frame_len(self, meta: dict) -> int:
        if meta['src'] == 'db':
            return meta['msg'].dlc if meta.get('msg') else 0
        return len(meta['data'])

    def _remove_selected(self):
        item = self._tree.currentItem()
        if item is None:
            return
        meta = self._item_meta(item)
        if meta:
            self._stop_meta(meta)
            if meta['kind'] == 'seq':
                for m in meta['members']:
                    self._stop_meta(m)
                    self._unregister_meta(m)
                meta['members'].clear()
            self._unregister_meta(meta)
        parent = item.parent()
        self._auto_tab = False   # 删除不切换 tab
        if parent is not None:
            pmeta = self._item_meta(parent)
            if pmeta and pmeta['kind'] == 'seq' and meta in pmeta['members']:
                pmeta['members'].remove(meta)
            parent.removeChild(item)
        else:
            idx = self._tree.indexOfTopLevelItem(item)
            self._tree.takeTopLevelItem(idx)
        self._on_selection_changed()
        self._auto_tab = True
        self._mark_dirty()
        self._update_run_buttons()

    def _move_selected(self, delta: int):
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        self._auto_tab = False   # 移动不切换 tab
        # 重排期间抑制 state_dirty: 重建控件初始化信号会触发多次同步自动保存
        self._restoring_state = True
        try:
            if parent is None:
                idx = self._tree.indexOfTopLevelItem(item)
                target = idx + delta
                if 0 <= target < self._tree.topLevelItemCount():
                    self._tree.takeTopLevelItem(idx)
                    self._tree.insertTopLevelItem(target, item)
                    self._tree.setCurrentItem(item)
            else:
                idx = parent.indexOfChild(item)
                target = idx + delta
                if 0 <= target < parent.childCount():
                    meta = self._item_meta(item)
                    pmeta = self._item_meta(parent)
                    parent.removeChild(item)
                    parent.insertChild(target, item)
                    if pmeta and pmeta['kind'] == 'seq' and meta in pmeta['members']:
                        pmeta['members'].remove(meta)
                        pmeta['members'].insert(target, meta)
                    self._tree.setCurrentItem(item)
            # take/insert 后 setItemWidget 关联失效, 重挂该行及全部子孙行
            self._reattach_row_widgets(item)
            self._tree.doItemsLayout()
        finally:
            self._restoring_state = False
            self._auto_tab = True
        self._mark_dirty()

    def _item_meta(self, item: Optional[QTreeWidgetItem]) -> Optional[dict]:
        if item is None:
            return None
        key = item.data(COL_NAME, _META_ROLE)
        if key is None:
            return None
        return self._meta_store.get(key)

    def _selected_meta(self) -> Optional[dict]:
        return self._item_meta(self._tree.currentItem())

    def _refresh_channel_options(self):
        opts = self._channel_options()
        it = self._tree.invisibleRootItem()
        self._refresh_ch_items(it, opts)

    def _refresh_ch_items(self, parent: QTreeWidgetItem, opts: list):
        for i in range(parent.childCount()):
            item = parent.child(i)
            meta = self._item_meta(item)
            w = self._tree.itemWidget(item, COL_CH)
            if isinstance(w, QComboBox) and meta:
                cur = meta['channel']
                w.blockSignals(True)
                w.clear()
                w.addItems(opts)
                if cur in opts:
                    w.setCurrentText(cur)
                elif opts:
                    meta['channel'] = w.currentText()
                w.blockSignals(False)
            self._refresh_ch_items(item, opts)

    # ------------------------------------------------------------------ #
    #  筛选 / 排序
    # ------------------------------------------------------------------ #

    def _update_sort_marks(self):
        """表头列名 + 排序箭头 (▲/▼ 附加在排序列名后, 避免与右缘漏斗按钮重叠)"""
        labels = [tr("触发"), tr("启用"), tr("名称"), tr("通道"), tr("ID"),
                  tr("类型"), tr("长度"), tr("次数"), tr("周期(ms)")]
        if self._sort_col in (COL_CH, COL_ID):
            labels[self._sort_col] += " ▲" if self._sort_asc else " ▼"
        self._tree.setHeaderLabels(labels)

    def _update_filter_icons(self):
        """漏斗按钮着色: 筛选激活为主题强调色, 未激活灰色"""
        self._fbtn_ch.setIcon(_funnel_icon(bool(self._flt_ch)))
        self._fbtn_id.setIcon(_funnel_icon(bool(self._flt_id)))

    def _on_filter_clicked(self, col: int):
        if col == COL_CH:
            self._show_ch_filter_menu()
        elif col == COL_ID:
            self._show_id_filter_popup()

    def _set_channel_filter(self, key: str):
        self._flt_ch = key
        self._update_filter_icons()
        self._apply_filter()

    def _set_id_filter(self, text: str):
        self._flt_id = text
        self._update_filter_icons()
        self._apply_filter()

    def _show_ch_filter_menu(self):
        """通道筛选: 漏斗下弹出勾选菜单 (全部通道 + 设备池通道, 随设备池实时枚举)"""
        menu = QMenu(self)
        for key, label in [("", tr("全部通道"))] + [
                (k, k) for k in self._channel_options()]:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(key == self._flt_ch)
            act.triggered.connect(
                lambda _c=False, k=key: self._set_channel_filter(k))
        menu.exec(self._fbtn_ch.mapToGlobal(QPoint(0, self._fbtn_ch.height())))

    def _show_id_filter_popup(self):
        """ID 筛选: 漏斗下弹出输入框 (实时过滤, 支持 0x1F4 / 十进制 / 无前缀 hex)"""
        pop = QFrame(self._tree, Qt.WindowType.Popup)
        pop.setObjectName("filterPopup")
        pop.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(pop)
        lay.setContentsMargins(6, 6, 6, 6)
        ed = QLineEdit(pop)
        ed.setText(self._flt_id)
        ed.setPlaceholderText(tr("0x1F4 / 十进制"))
        ed.setClearButtonEnabled(True)
        ed.setMinimumWidth(140)
        ed.textChanged.connect(self._set_id_filter)
        lay.addWidget(ed)
        pop.move(self._fbtn_id.mapToGlobal(QPoint(0, self._fbtn_id.height())))
        pop.show()
        ed.setFocus()

    def _parse_filter_id(self) -> Optional[int]:
        """筛选 ID: 支持 0x 前缀 hex / 十进制; 纯字母数字串按 hex 兜底;
        无法解析返回 -1 (不匹配任何帧), 空串返回 None (不筛选)"""
        text = self._flt_id.strip()
        if not text:
            return None
        fid = self._parse_id(text)
        if fid is None:
            try:
                fid = int(text, 16)
            except ValueError:
                fid = -1
        return fid

    def _match_filter(self, meta: dict, ch: str, fid: Optional[int]) -> bool:
        if ch and meta.get('channel') != ch:
            return False
        if fid is not None and meta.get('id') != fid:
            return False
        return True

    def _apply_filter(self):
        """按通道/ID 过滤顶层行; 序列任一成员命中则整组显示 (含全部成员)"""
        ch = self._flt_ch
        fid = self._parse_filter_id()
        filtering = bool(ch) or fid is not None
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            meta = self._item_meta(item)
            if meta is None:
                continue
            if meta['kind'] == 'seq':
                show = any(self._match_filter(m, ch, fid)
                           for m in meta['members']) if filtering else True
                item.setHidden(not show)
                for j in range(item.childCount()):
                    item.child(j).setHidden(not show)
            else:
                item.setHidden(not self._match_filter(meta, ch, fid))

    def _on_header_clicked(self, col: int):
        """点击【通道】/【ID】表头循环排序状态: 升序 -> 降序 -> 取消(恢复排序前顺序)
        (序列按自身通道/首成员 ID 参与, 成员顺序不动 -- 成员顺序是发送语义)。
        注意: 本槽在 QHeaderView::mouseReleaseEvent 调用栈内执行, 直接做
        take/insert + setItemWidget + setHeaderLabels 这类树/表头手术曾在
        真实环境引发原生崩溃, 故重排整体延迟到事件循环空闲时执行。"""
        if col not in (COL_CH, COL_ID):
            return
        if self._sort_col == col:
            if self._sort_asc:
                self._sort_asc = False      # 升序 -> 降序
            else:
                self._sort_col = -1         # 降序 -> 取消排序
        else:
            self._sort_col, self._sort_asc = col, True
        QTimer.singleShot(0, self._apply_sort)

    def _apply_sort(self):
        """按当前 _sort_col/_sort_asc 重排顶层行; _sort_col=-1 时恢复排序前顺序"""
        cur = [self._tree.topLevelItem(i)
               for i in range(self._tree.topLevelItemCount())]
        col = self._sort_col
        if col not in (COL_CH, COL_ID):
            # 取消排序: 恢复排序前顺序; 排序期间新增的行保持相对顺序排在末尾
            pre = self._pre_sort_keys
            self._pre_sort_keys = None
            if not pre:
                return
            by_key = {it.data(COL_NAME, _META_ROLE): it for it in cur}
            pre_set = set(pre)
            order = [by_key[k] for k in pre if k in by_key]
            order += [it for it in cur
                      if it.data(COL_NAME, _META_ROLE) not in pre_set]
            self._reorder_top_level(order)
            self._update_sort_marks()
            self._mark_dirty()
            return
        if self._pre_sort_keys is None:
            # 从未排序状态进入排序: 记录当前顺序供取消时恢复
            self._pre_sort_keys = [it.data(COL_NAME, _META_ROLE) for it in cur]
        if col == COL_CH:
            key = lambda m: m.get('channel') or ''
        else:
            key = lambda m: m.get('id', -1) if m['kind'] != 'seq' else (
                m['members'][0].get('id', -1) if m['members'] else -1)
        cur.sort(key=lambda it: key(self._item_meta(it) or {}),
                 reverse=not self._sort_asc)
        self._reorder_top_level(cur)
        self._update_sort_marks()
        self._mark_dirty()

    def _reorder_top_level(self, items: list):
        """按给定顺序重排顶层行并重建行内控件 (take/insert 后关联失效需重挂)"""
        self._auto_tab = False   # 重排不切换 tab
        # 重排期间抑制 state_dirty: 重建控件初始化信号会触发十几次同步自动保存
        self._restoring_state = True
        try:
            for it in items:
                self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(it))
            for it in items:
                self._tree.addTopLevelItem(it)
                # take/insert 后整棵子树 setItemWidget 关联失效, 递归重挂
                self._reattach_row_widgets(it)
            self._tree.doItemsLayout()
        finally:
            self._restoring_state = False
            self._auto_tab = True

    # ------------------------------------------------------------------ #
    #  行内编辑回调
    # ------------------------------------------------------------------ #

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        meta = self._item_meta(item)
        if meta is None:
            return
        if column == COL_EN:
            meta['enabled'] = \
                item.checkState(COL_EN) == Qt.CheckState.Checked
            self._update_run_buttons()   # 启用勾选变化联动启停按钮
        elif column == COL_NAME:
            meta['name'] = item.text(COL_NAME)
        elif column == COL_ID and meta['kind'] == 'frame' \
                and meta['src'] == 'custom':
            fid = self._parse_id(item.text(COL_ID))
            if fid is not None:
                meta['id'] = fid
            else:
                item.setText(COL_ID, self._ui.fmt_id(meta['id']))
        self._mark_dirty()

    def _on_widget_changed(self, meta: dict, item: QTreeWidgetItem):
        """行内控件 (通道/类型/次数/间隔) 变化回写 meta"""
        ch = self._tree.itemWidget(item, COL_CH)
        if isinstance(ch, QComboBox):
            meta['channel'] = ch.currentText()
        ctype = self._tree.itemWidget(item, COL_TYPE)
        if isinstance(ctype, QComboBox):
            idx = ctype.currentIndex()
            if 0 <= idx < len(FRAME_TYPE_FLAGS):
                (meta['is_extended'], meta['is_remote'],
                 meta['is_fd'], meta['is_brs']) = FRAME_TYPE_FLAGS[idx]
        ccount = self._tree.itemWidget(item, COL_COUNT)
        if isinstance(ccount, QSpinBox):
            meta['count'] = ccount.value()
        cintv = self._tree.itemWidget(item, COL_INTV)
        if isinstance(cintv, QSpinBox):
            meta['interval'] = cintv.value()
            if meta.get('timer') is not None:
                meta['timer'].setInterval(max(1, meta['interval']))
        self._mark_dirty()

    # ------------------------------------------------------------------ #
    #  选中联动 -> 信号 / 数据场
    # ------------------------------------------------------------------ #

    def _on_selection_changed(self):
        meta = self._selected_meta()
        if meta is None or meta['kind'] == 'seq':
            self._signal_table.clear()
            self._raw_table.setRowCount(0)
            self._field_tabs.setEnabled(False)
            return
        self._field_tabs.setEnabled(True)
        if meta['src'] == 'db':
            if self._auto_tab:
                self._field_tabs.setCurrentIndex(0)
            self._build_signal_field(meta)
            self._refresh_raw_field()   # db 帧也填充原始数据(只读)
        else:
            if self._auto_tab:
                self._field_tabs.setCurrentIndex(1)
            self._signal_table.clear()   # 自定义帧无信号, 清空避免残留
            self._refresh_raw_field()

    def _build_signal_field(self, meta: dict):
        msg = meta.get('msg')
        self._signal_table.blockSignals(True)
        self._signal_table.clear()
        if msg is None:
            self._signal_table.blockSignals(False)
            return
        for sig in msg.signals:
            node = QTreeWidgetItem(self._signal_table, [sig.name])
            phys = meta['phys'].get(sig.name, 0.0)
            raw = self._phys_to_raw(sig, phys)
            node.setText(1, str(sig.start_bit))
            node.setText(2, str(sig.length))
            node.setText(3, str(raw))
            node.setText(4, self._phys_display(sig, raw, phys))
            node.setText(5, sig.unit)
            node.setData(3, Qt.ItemDataRole.UserRole, sig.name)
            node.setData(4, Qt.ItemDataRole.UserRole, sig.name)
            node.setFlags(node.flags() | Qt.ItemFlag.ItemIsEditable)
        self._signal_table.blockSignals(False)

    def _on_phys_edited(self, item: QTreeWidgetItem, column: int):
        """总线值/物理值双向联动 (按 DBC 换算规则 factor/offset)"""
        if column not in (3, 4):
            return
        meta = self._selected_meta()
        if meta is None or meta['kind'] != 'frame' or meta['src'] != 'db':
            return
        sig_name = item.data(3, Qt.ItemDataRole.UserRole)
        msg = meta.get('msg')
        sig = msg.find_signal(sig_name) if msg else None
        if sig is None:
            return
        if column == 3:   # 编辑总线值 -> 换算物理值
            try:
                raw = int(item.text(3), 0)
            except ValueError:
                return
            phys = raw * sig.factor + sig.offset
            meta['phys'][sig_name] = phys
            item.setText(4, self._phys_display(sig, raw, phys))
        else:   # 编辑物理值 -> 换算总线值
            try:
                phys = float(item.text(4))
            except ValueError:
                return
            meta['phys'][sig_name] = phys
            raw = self._phys_to_raw(sig, phys)
            item.setText(3, str(raw))
            item.setText(4, self._phys_display(sig, raw, phys))
        self._refresh_raw_field()   # 数据随值刷新
        self._mark_dirty()

    @staticmethod
    def _phys_display(sig, raw: int, phys: float) -> str:
        """物理值显示: 离散值表描述优先, 否则按换算规则数值"""
        if getattr(sig, 'value_descriptions', None):
            desc = sig.get_value_description(raw)
            if desc != str(raw):
                return desc
        return f"{phys:g}"

    @staticmethod
    def _phys_to_raw(sig, phys: float) -> int:
        return int((phys - sig.offset) / sig.factor) if sig.factor else 0

    def _encode_db_data(self, meta: dict) -> bytes:
        """数据库帧: 由当前物理值实时编码出总线字节供 hex dump 显示"""
        codec = self._hub.get_codec(meta.get('channel') or self._channel_key)
        if codec is None:
            return bytes(meta.get('data') or b"")
        try:
            out = codec.encode_message(meta['name'], dict(meta['phys']))
        except (ValueError, TypeError, KeyError):
            out = None   # 编码异常(如位布局越界)不中断显示
        return bytes(out.data) if out else bytes(meta.get('data') or b"")

    def _refresh_raw_field(self):
        """填充 hex dump 网格: 地址 | 16字节hex | ASCII (custom 可编辑, db 只读)"""
        meta = self._selected_meta()
        if meta is None or meta['kind'] != 'frame':
            return
        editable = True   # 所有帧字节可编辑
        data = bytes(meta['data']) if meta['src'] == 'custom' \
            else self._encode_db_data(meta)
        rows = max(1, (len(data) + 15) // 16)
        self._raw_table.reset_input_state()
        self._raw_table.blockSignals(True)
        self._raw_table.setRowCount(rows)
        for r in range(rows):
            addr = QTableWidgetItem(f"{r * 16:04X}")
            addr.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._raw_table.setItem(r, 0, addr)
            ascii_chars = []
            for c in range(16):
                idx = r * 16 + c
                if idx < len(data):
                    b = data[idx]
                    cell = QTableWidgetItem(f"{b:02X}")
                    # setFlags 为整体替换, 必须显式带上 ItemIsSelectable 否则无法选中
                    flags = Qt.ItemFlag.ItemIsEnabled \
                        | Qt.ItemFlag.ItemIsSelectable
                    if editable:
                        flags |= Qt.ItemFlag.ItemIsEditable
                    cell.setFlags(flags)
                    ascii_chars.append(chr(b) if 32 <= b < 127 else ".")
                else:
                    cell = QTableWidgetItem("")
                    cell.setFlags(Qt.ItemFlag.NoItemFlags)
                    ascii_chars.append("")
                self._raw_table.setItem(r, 1 + c, cell)
            asc = QTableWidgetItem("".join(ascii_chars))
            asc.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._raw_table.setItem(r, 17, asc)
        self._raw_table.blockSignals(False)

    def _on_raw_byte_edited(self, item: QTableWidgetItem):
        """单字节编辑回写 meta['data'] 并刷新 ASCII/长度/信号"""
        meta = self._selected_meta()
        if meta is None or meta['kind'] != 'frame':
            return
        row, col = self._raw_table.row(item), self._raw_table.column(item)
        if not (1 <= col <= 16):
            return
        idx = row * 16 + (col - 1)
        if idx >= len(meta['data']):
            return
        try:
            b = int(item.text().strip(), 16)
        except ValueError:
            b = None
        if b is None or not (0 <= b <= 255):
            # 非法输入回滚: 延迟到编辑器关闭后再重建 (commit 回调内
            # setRowCount/setItem 重建表格会产生悬垂索引, 可能原生崩溃)
            QTimer.singleShot(0, self._refresh_raw_field)
            return
        meta['data'][idx] = b
        if meta['src'] == 'db':
            self._sync_phys_from_data(meta)   # 字节编辑反推物理值
            self._build_signal_field(meta)
        self._raw_table.blockSignals(True)
        item.setText(f"{b:02X}")
        self._refresh_ascii_row(row, bytes(meta['data']))
        self._raw_table.blockSignals(False)
        it = self._tree.currentItem()
        if it:
            it.setText(COL_LEN, str(len(meta['data'])))
        self._mark_dirty()

    def _on_hex_typed(self, idx: int, val: int):
        """选中字节直接键入 hex: 直写 meta['data'] 并刷新显示 (免双击连续录数)"""
        meta = self._selected_meta()
        if meta is None or meta['kind'] != 'frame' or idx >= len(meta['data']):
            return
        meta['data'][idx] = val
        self._raw_table.blockSignals(True)
        cell = self._raw_table.item(idx // 16, 1 + idx % 16)
        if cell is not None:
            cell.setText(f"{val:02X}")
        self._refresh_ascii_row(idx // 16, bytes(meta['data']))
        self._raw_table.blockSignals(False)
        if meta['src'] == 'db':
            self._sync_phys_from_data(meta)
            self._build_signal_field(meta)
        self._mark_dirty()

    def _refresh_ascii_row(self, row: int, data: bytes):
        chars = []
        for c in range(16):
            idx = row * 16 + c
            if idx < len(data):
                chars.append(chr(data[idx]) if 32 <= data[idx] < 127 else ".")
            else:
                chars.append("")
        asc = self._raw_table.item(row, 17)
        if asc is not None:
            asc.setText("".join(chars))

    def _sync_phys_from_data(self, meta: dict):
        """由 data 字节反推各信号物理值 (字节编辑/粘贴后联动信号表)"""
        msg = meta.get('msg')
        if not msg:
            return
        data = bytes(meta['data'])
        for sig in msg.signals:
            try:
                raw = sig.decode_raw(data)
                meta['phys'][sig.name] = raw * sig.factor + sig.offset
            except (ValueError, TypeError):
                pass

    def _on_raw_paste(self, text: str):
        """粘贴: 从第一个字节开始顺序填充 (非选中区域粘贴)"""
        meta = self._selected_meta()
        if meta is None or meta['kind'] != 'frame':
            return
        tokens = text.replace(",", " ").split()
        try:
            if len(tokens) == 1 and len(tokens[0]) % 2 == 0 and len(tokens[0]) > 2:
                s = tokens[0]
                vals = [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]
            else:
                vals = [int(t, 16) for t in tokens if t]
        except ValueError:
            return
        data = meta['data']
        rng = self._raw_table.selected_byte_range()
        start = rng[0] if rng else 0   # 有选中则从选中首字节起顺序填充
        for i, b in enumerate(vals):
            pos = start + i
            if pos >= len(data):
                break
            if 0 <= b <= 255:
                data[pos] = b
        if meta['src'] == 'db':
            self._sync_phys_from_data(meta)
            self._build_signal_field(meta)
        self._refresh_raw_field()
        it = self._tree.currentItem()
        if it:
            it.setText(COL_LEN, str(len(data)))
        self._mark_dirty()

    # ------------------------------------------------------------------ #
    #  状态导出 / 导入 (工程文件持久化)
    # ------------------------------------------------------------------ #

    def _mark_dirty(self):
        """帧配置变化 -> 通知工程树自动保存 (导入恢复期间抑制)"""
        if not self._restoring_state:
            self.state_dirty.emit()

    def export_state(self) -> dict:
        """导出发送列表全部帧/序列配置 (存 .bfproj panels[].state)"""
        root = self._tree.invisibleRootItem()
        return {'items': [self._meta_to_state(root.child(i))
                          for i in range(root.childCount())]}

    def _meta_to_state(self, item: QTreeWidgetItem) -> dict:
        meta = self._item_meta(item) or {}
        st = {
            'kind': meta.get('kind', 'frame'),
            'name': meta.get('name', ''),
            'channel': meta.get('channel', ''),
            'enabled': bool(meta.get('enabled', True)),
            'count': int(meta.get('count', 1)),
            'interval': int(meta.get('interval', 100)),
        }
        if st['kind'] == 'seq':
            st['members'] = [self._meta_to_state(item.child(i))
                             for i in range(item.childCount())]
        else:
            st.update({
                'src': meta.get('src', 'custom'),
                'id': int(meta.get('id', 0)),
                'is_fd': bool(meta.get('is_fd')),
                'is_extended': bool(meta.get('is_extended')),
                'is_remote': bool(meta.get('is_remote')),
                'is_brs': bool(meta.get('is_brs')),
                'data': bytes(meta.get('data') or b'').hex(),
                'phys': {k: float(v) for k, v in
                         (meta.get('phys') or {}).items()},
            })
        return st

    def import_state(self, state: dict):
        """从工程文件状态恢复发送列表 (帧/序列/数据/物理值)"""
        self._restoring_state = True
        try:
            self._tree.clear()
            self._meta_store.clear()
            for st in (state or {}).get('items', []):
                self._restore_item(None, st)
            self._auto_tab = False
            self._on_selection_changed()
            self._auto_tab = True
        finally:
            self._restoring_state = False
        self._update_run_buttons()

    def _restore_item(self, parent, st: dict):
        """按状态字典恢复一行 (帧或序列, 序列递归恢复成员)"""
        if st.get('kind') == 'seq':
            meta = self._new_seq_meta()
            meta['name'] = st.get('name', meta['name'])
            meta['channel'] = st.get('channel', meta['channel'])
            meta['enabled'] = bool(st.get('enabled', True))
            meta['count'] = int(st.get('count', 1))
            meta['interval'] = int(st.get('interval', 100))
            item = self._append_frame_item(parent, meta)
            for m in st.get('members', []):
                self._restore_item(item, m)
            return item
        meta = self._new_frame_meta(bool(st.get('is_fd')))
        meta['name'] = st.get('name', '')
        meta['src'] = st.get('src', 'custom')
        meta['id'] = int(st.get('id', 0))
        meta['is_fd'] = bool(st.get('is_fd'))
        meta['is_extended'] = bool(st.get('is_extended'))
        meta['is_remote'] = bool(st.get('is_remote'))
        meta['is_brs'] = bool(st.get('is_brs'))
        meta['channel'] = st.get('channel', self._channel_key)
        meta['enabled'] = bool(st.get('enabled', True))
        meta['count'] = int(st.get('count', 1))
        meta['interval'] = int(st.get('interval', 100))
        try:
            meta['data'] = bytearray(bytes.fromhex(st.get('data') or ''))
        except ValueError:
            pass
        meta['phys'].update(st.get('phys') or {})
        if meta['src'] == 'db':
            meta['msg'] = self._find_db_message(
                meta['channel'], meta['name'])
        return self._append_frame_item(parent, meta)

    def _find_db_message(self, channel: str, name: str):
        """按 通道+报文名 反查 DBC 报文对象 (恢复 db 帧用)"""
        for dbc in self._hub.all_channel_dbc().get(channel, []):
            msg = dbc.get_message_by_name(name)
            if msg is not None:
                return msg
        return None

    def _on_raw_copy(self):
        """复制: 选中字节区间 (无选中则全部) 以 hex 文本入剪贴板"""
        meta = self._selected_meta()
        if meta is None or meta['kind'] != 'frame':
            return
        data = bytes(meta['data'])
        rng = self._raw_table.selected_byte_range()
        if rng:
            data = data[rng[0]:rng[1] + 1]
        QApplication.clipboard().setText(
            " ".join(f"{b:02X}" for b in data))

    def _on_dbc_changed(self, channel_key: str, dbc):
        meta = self._selected_meta()
        if meta and meta['kind'] == 'frame' and meta['src'] == 'db' \
                and meta['channel'] == channel_key:
            meta['msg'] = dbc.get_message_by_name(meta['name']) if dbc else None
            self._build_signal_field(meta)

    # ------------------------------------------------------------------ #
    #  发送 / 触发
    # ------------------------------------------------------------------ #

    def _flash_hint(self, text: str):
        """用法提示条临时显示运行反馈 (淡红警示, 4s 后恢复用法提示)"""
        self._hint_label.setText(text)
        self._hint_label.setProperty("alert", True)
        self._hint_label.style().unpolish(self._hint_label)
        self._hint_label.style().polish(self._hint_label)
        QTimer.singleShot(4000, self._restore_hint)

    def _restore_hint(self):
        self._hint_label.setProperty("alert", False)
        self._hint_label.style().unpolish(self._hint_label)
        self._hint_label.style().polish(self._hint_label)
        self._hint_label.setText(self._usage_hint_text())

    def _update_run_buttons(self):
        """启停按钮使能联动: 有可启动的启用行则【启动】可点;
        有运行中的行则【停止】可点"""
        any_running = False
        any_startable = False
        for i in range(self._tree.topLevelItemCount()):
            meta = self._item_meta(self._tree.topLevelItem(i))
            if not meta:
                continue
            if meta.get('timer') is not None:
                any_running = True
            elif meta['enabled']:
                any_startable = True
        self._start_all_btn.setEnabled(any_startable)
        self._stop_all_btn.setEnabled(any_running)

    def _ensure_channel_ready(self, key: str) -> tuple:
        """发送前确保通道已连接 (连接即可发, 不依赖工程运行态); 未连接则同步连接"""
        if not key:
            return False, tr("未选择通道")
        if self._dm.get_instance(key) is not None:
            return True, ""
        return self._dm.connect_channel(key)

    def _ensure_meta_ready(self, meta: dict) -> tuple:
        """启动前确保该行通道就绪 (序列须全部成员通道就绪)"""
        if meta['kind'] == 'seq':
            if not meta['members']:
                return False, tr("序列为空, 请先添加成员帧")
            for m in meta['members']:
                ok, err = self._ensure_channel_ready(
                    m.get('channel') or self._channel_key)
                if not ok:
                    return False, f"{m.get('name') or tr('成员帧')}: {err}"
            return True, ""
        return self._ensure_channel_ready(
            meta.get('channel') or self._channel_key)

    def _on_trigger(self, meta: dict, item: QTreeWidgetItem):
        self._on_widget_changed(meta, item)
        if meta.get('timer') is not None:
            self._stop_meta(meta)
        else:
            self._start_meta(meta, item)
        self._tree.viewport().update()   # 触发列 delegate 重绘 发送/停止
        self._update_run_buttons()

    def _start_meta(self, meta: dict, item: QTreeWidgetItem):
        ok, err = self._ensure_meta_ready(meta)
        if not ok:
            self._flash_hint(tr("启动失败: ") + err)
            return
        meta['_err_shown'] = False   # 本轮运行失败反馈重新计次
        meta['_trunc_warned'] = False   # 截断警示也重新计次
        meta['progress'] = 0
        self._set_progress(item, 0)
        if meta['kind'] == 'seq':
            meta['_seq_idx'] = 0
            meta['_pass'] = 0
            timer = QTimer(self)
            timer.setInterval(max(1, meta['interval']))
            timer.timeout.connect(lambda m=meta, it=item: self._seq_tick(m, it))
            timer.start()
            meta['timer'] = timer
            self._seq_tick(meta, item)
            return
        meta['_remaining'] = meta['count']
        timer = QTimer(self)
        timer.setInterval(max(1, meta['interval']))
        timer.timeout.connect(lambda m=meta, it=item: self._frame_tick(m, it))
        timer.start()
        meta['timer'] = timer
        self._frame_tick(meta, item)

    def _frame_tick(self, meta: dict, item: QTreeWidgetItem):
        self._send_frame(meta)
        meta['progress'] += 1
        self._set_progress(item, meta['progress'])
        if meta['count'] > 0:
            meta['_remaining'] -= 1
            if meta['_remaining'] <= 0:
                self._stop_meta(meta)
                self._tree.viewport().update()
                self._update_run_buttons()

    def _seq_tick(self, meta: dict, item: QTreeWidgetItem):
        members = meta['members']
        if not members:
            self._stop_meta(meta)
            self._update_run_buttons()
            return
        if meta['_seq_idx'] >= len(members):
            meta['_pass'] += 1
            if meta['count'] > 0 and meta['_pass'] >= meta['count']:
                self._stop_meta(meta)
                self._tree.viewport().update()
                self._update_run_buttons()
                return
            meta['_seq_idx'] = 0
        m = members[meta['_seq_idx']]
        meta['_seq_idx'] += 1
        self._send_frame(m)
        meta['progress'] += 1
        self._set_progress(item, meta['progress'])

    def _send_frame(self, meta: dict) -> bool:
        """异步发送一帧, 返回是否成功入队; 失败可见反馈 (本轮运行只提示一次)
        硬件 send 可能阻塞 (ZLG 总线无ACK时~1.5s/帧), 必须走 send_async,
        真正的硬件失败由 dm.send_failed 信号节流上报 (见 _on_dm_send_failed)。"""
        ch = meta.get('channel') or self._channel_key
        if not ch:
            return self._send_failed(meta, tr("未选择通道"))
        if meta['src'] == 'custom':
            if not meta['is_fd'] and not meta.get('is_remote') \
                    and len(meta['data']) > 8:
                self._trunc_warn(meta)   # 经典CAN数据超8字节将被驱动截断
            ok = self._dm.send_async(
                ch, meta['id'], bytes(meta['data']),
                meta['is_extended'], meta['is_fd'],
                is_remote=bool(meta.get('is_remote')),
                is_brs=bool(meta.get('is_brs')))
        else:
            codec = self._hub.get_codec(ch)
            if codec is None:
                return self._send_failed(
                    meta, tr("通道未绑定DBC, 无法编码数据库帧") + f": {ch}")
            try:
                out = codec.encode_message(meta['name'], dict(meta['phys']))
            except (ValueError, TypeError, KeyError):
                out = None
            if out is None:
                return self._send_failed(
                    meta, tr("数据库帧编码失败") + f": {meta['name']}")
            # 帧类型以类型列用户选择为准 (DBC未标VFrameFormat时 out.is_fd 恒 False,
            # 若按 out.is_fd 发送, FD报文会被降级为经典CAN并截断为8字节)
            is_fd = bool(meta.get('is_fd'))
            if not is_fd and len(out.data) > 8:
                self._trunc_warn(meta)   # 数据库帧经典CAN超8字节同样被截断
            ok = self._dm.send_async(
                ch, out.message_id, bytes(out.data), out.is_extended,
                is_fd, is_remote=False,
                is_brs=bool(meta.get('is_brs')) and is_fd)
        if not ok:
            return self._send_failed(
                meta, tr("发送队列已满(硬件无应答积压)") + f": {ch}")
        return True

    def _send_failed(self, meta: dict, msg: str) -> bool:
        """发送失败: 记日志 + 提示条警示 (一轮运行只提示一次, 周期失败不刷屏)"""
        logger.warning(f"仿真发送: {msg}")
        if not meta.get('_err_shown'):
            meta['_err_shown'] = True
            self._flash_hint(tr("发送失败: ") + msg)
        return False

    def _trunc_warn(self, meta: dict):
        """经典CAN单帧最多8字节, 超出部分驱动静默截断: 提示条警示 (一轮运行一次)"""
        if meta.get('_trunc_warned'):
            return
        meta['_trunc_warned'] = True
        self._flash_hint(tr("经典CAN单帧最多8字节, 超出部分已截断(请改用CAN FD类型)"))

    def _on_dm_send_failed(self, channel_key: str, reason: str):
        """硬件异步发送失败 (dm侧已按通道节流 2s): 提示条警示, 不打断周期发送"""
        self._flash_hint(f"{tr('发送失败')}[{channel_key}]: {reason}")

    def _stop_meta(self, meta: dict):
        timer = meta.pop('timer', None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _set_progress(self, item: QTreeWidgetItem, value: int):
        """进度列已移除; 仅保留 meta['progress'] 计数供逻辑使用"""
        pass

    def _start_all(self):
        """启动全部启用行: 先自动连接涉及通道 (连接即可发), 再逐行启动"""
        errs = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            meta = self._item_meta(item)
            if not meta or not meta['enabled'] or meta.get('timer') is not None:
                continue
            ok, err = self._ensure_meta_ready(meta)
            if ok:
                self._start_meta(meta, item)
            else:
                errs.append(f"{meta.get('name') or tr('未命名')}: {err}")
        if errs:
            self._flash_hint(tr("部分行启动失败: ") + "; ".join(errs[:3]))
        self._tree.viewport().update()
        self._update_run_buttons()

    def _stop_all(self):
        it = self._tree.invisibleRootItem()
        self._stop_items(it)
        self._tree.viewport().update()
        self._update_run_buttons()

    def _stop_items(self, parent: QTreeWidgetItem):
        for i in range(parent.childCount()):
            item = parent.child(i)
            meta = self._item_meta(item)
            if meta:
                self._stop_meta(meta)
            self._stop_items(item)

    def _on_running_changed(self, running: bool):
        if not running:
            self._stop_all()

    # ------------------------------------------------------------------ #
    #  进制切换
    # ------------------------------------------------------------------ #

    def _reformat_all(self):
        it = self._tree.invisibleRootItem()
        self._reformat_items(it)
        self._refresh_raw_field()

    def _reformat_items(self, parent: QTreeWidgetItem):
        for i in range(parent.childCount()):
            item = parent.child(i)
            meta = self._item_meta(item)
            if meta and meta['kind'] == 'frame':
                item.setText(COL_ID, self._ui.fmt_id(meta['id']))
            self._reformat_items(item)

    # ------------------------------------------------------------------ #
    #  解析工具
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_id(text: str) -> Optional[int]:
        try:
            t = text.strip()
            return int(t, 16) if t.lower().startswith("0x") else int(t)
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    #  公共接口
    # ------------------------------------------------------------------ #

    def set_channel(self, channel_key: str):
        self._channel_key = channel_key
        self.retranslateUi()

    def closeEvent(self, event):
        self._stop_all()
        super().closeEvent(event)
