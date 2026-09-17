"""
Trace面板 - 报文展示 (纯展示层)

数据源: DataHub 推送 (register kinds={frame, stats})。
本面板只做表格写入与显示过滤, 不做解码/通道路由/统计计算。
"""

import logging
import time
from collections import deque

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QLineEdit, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame,
    QMenu, QAbstractItemView, QStyle, QProxyStyle
)
from PySide6.QtCore import (Qt, QTimer, Signal, QPoint, QPointF,
                            QRect, QRectF, QEvent)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPixmap,
    QLinearGradient, QPolygonF
)

from app.core.data_hub import (
    DataHub, KIND_FRAME, KIND_MESSAGE, KIND_STATS,
)
from app.core.device_manager import DeviceManager
from app.core.ui_settings import UISettings
from app.core.i18n import tr
from app.models.dto import FrameDTO
from app.ui.toolbar_widget import _ToolButton

logger = logging.getLogger(__name__)

# 列: 时间(秒, 微秒级6位小数)/通道/方向/ID/名称/DLC + 单列数据 (后缀随进制动态拼接)
ALL_COLUMNS = [
    "时间(s)", "通道", "方向", "ID", "报文名", "DLC", "数据",
]
# 列索引
_COL_CH = 1
_COL_DIR = 2
_COL_ID = 3        # 随进制重格式化
_COL_NAME = 4
_COL_DLC = 5
_COL_DATA = 6      # 随进制重格式化
# 可筛选列 (除时间列外全部, 漏斗过滤)
_FILTER_COLS = (_COL_CH, _COL_DIR, _COL_ID, _COL_NAME, _COL_DLC, _COL_DATA)
# 单列不重复值累积上限 (数据列载荷多变, 防止无限增长)
_DISTINCT_CAP = 2000
# Trace 临时存储上限 (停止监控时滚动模式全量展示)
_HISTORY_CAP = 10000
# item 数据角色 (UserRole=0x0100; 直接用整型避免枚举运算)
_ROLE_FRAME = 0x0100    # 行存 FrameDTO
_ROLE_FILLED = 0x0101   # 信号子行已懒填充标记
_ROLE_CHILD_IDX = 0x0102  # 信号子行序号 (覆盖模式排序时保信号原序)
_ROLE_TABS = 0x0103     # 行绝对时间 (距运行零点秒数)
_ROLE_TDELTA = 0x0104   # 行相对时间 (与同(通道,ID)上一帧的时间差)


class _TraceItem(QTreeWidgetItem):
    """排序感知的行 item: 时间/DLC/ID 按数值比较, 信号子行按原序"""

    @staticmethod
    def _num(text: str, col: int):
        if col == 0:                      # 时间列 (秒)
            return float(text)
        if col == _COL_DLC:
            return int(text)
        if col == _COL_ID:                # 随进制: 0x5F / 95
            return int(text, 16) if text.lower().startswith("0x") else int(text)
        return None

    def __lt__(self, other):
        # 信号子行: 按填充序号保原序 (排序不搅乱信号列表)
        if self.parent() is not None and other.parent() is not None:
            return (self.data(0, _ROLE_CHILD_IDX) or 0) < \
                   (other.data(0, _ROLE_CHILD_IDX) or 0)
        tw = self.treeWidget()
        col = tw.sortColumn() if tw is not None else 0
        try:
            va = self._num(self.text(col), col)
            vb = self._num(other.text(col), col)
            if va is not None and vb is not None:
                return va < vb
        except ValueError:
            pass
        return self.text(col) < other.text(col)


def _funnel_path(x: float, y: float) -> QPainterPath:
    """11x11 漏斗字形路径 (绘制于表头 section 内, 与背景一体无控件边框)"""
    path = QPainterPath()
    path.moveTo(x, y)
    path.lineTo(x + 11, y)
    path.lineTo(x + 7, y + 5)
    path.lineTo(x + 7, y + 9)
    path.lineTo(x + 5, y + 10)
    path.lineTo(x + 5, y + 5)
    path.closeSubpath()
    return path


class _BranchIndicatorStyle(QProxyStyle):
    """Trace 树分支展开指示符: 矢量自绘加/减号取代 QSS 位图

    QSS image:url() 位图不随 devicePixelRatio 缩放 (高DPI下拉伸模糊),
    且可能与原生样式箭头叠加产生重影; 代理样式直接矢量绘制, 任何缩放比都清晰。"""

    BOX = 12.0   # 方框边长 (逻辑像素)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_IndicatorBranch \
                and option.state & QStyle.StateFlag.State_Children:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = option.rect
            box = QRectF(r.x() + (r.width() - self.BOX) / 2,
                         r.y() + (r.height() - self.BOX) / 2,
                         self.BOX, self.BOX)
            # 圆角小方框 (暖灰边 + 近白底)
            painter.setPen(QColor("#93a0ac"))
            painter.setBrush(QColor("#f6f8fa"))
            painter.drawRoundedRect(box, 2, 2)
            # 横杠 (闭合态再补竖杠成加号)
            painter.setPen(QColor("#54616d"))
            cx, cy = box.center().x(), box.center().y()
            painter.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
            if not option.state & QStyle.StateFlag.State_Open:
                painter.drawLine(QPointF(cx, cy - 3), QPointF(cx, cy + 3))
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


class _TraceHeaderView(QHeaderView):
    """Trace 表头 - 分层渐变圆柱凸起质感 + 自绘漏斗筛选 (CANoe 式)

    性能设计 (面向大量报文流):
    - 背景为竖向多停点渐变, 预渲染成窄条 QPixmap 缓存, paintSection 只做
      位图拉伸 blit + 几条边线 + 漏斗矢量字形, 无常量外开销;
    - 漏斗直接画在 section 里 (非子控件), 完美嵌入渐变背景,
      列宽变化/水平滚动无需任何重排; 表头独立于 viewport, 数据流零刷新。
    """

    filter_clicked = Signal(int)   # 漏斗被点击 (列索引)
    sort_cleared = Signal()        # 第三次点击取消排序

    TITLE_H = 24    # 单行表头: 列名 + 右侧自绘漏斗

    def __init__(self, table: QTreeWidget):
        super().__init__(Qt.Orientation.Horizontal, table)
        self._funnel_cols: set[int] = set()      # 可筛选列
        self._active_funnels: set[int] = set()   # 有筛选条件的列
        self._sort_clicks = False    # 列头点击排序开关 (覆盖模式才开)
        self._hover = -1          # hover 的 section
        self._hover_funnel = -1   # hover 的漏斗所在列
        self._bg_pm: QPixmap | None = None
        self._title_font = QFont()
        self._title_font.setBold(True)
        self.setMouseTracking(True)
        self.setFixedHeight(self.TITLE_H)

    # ---- 漏斗 (自绘, 无子控件) ----

    def add_funnel(self, col: int):
        """登记可筛选列"""
        self._funnel_cols.add(col)

    def set_funnel_active(self, col: int, active: bool):
        """切换漏斗激活态 (有筛选条件时钢蓝高亮), 只重绘该列"""
        if active:
            self._active_funnels.add(col)
        else:
            self._active_funnels.discard(col)
        self.updateSection(col)

    def _funnel_rect(self, col: int) -> QRect:
        """漏斗命中/绘制区: 列右缘 16x16 (列过窄/隐藏时为空)"""
        sw = self.sectionSize(col)
        if sw < 34:
            return QRect()
        return QRect(self.sectionViewportPosition(col) + sw - 20,
                     (self.height() - 16) // 2, 16, 16)

    def funnel_anchor_pos(self, col: int) -> QPoint:
        """漏斗图标左下的屏幕坐标 (筛选弹窗锚点)"""
        return self.mapToGlobal(self._funnel_rect(col).bottomLeft()
                                + QPoint(0, 2))

    def resizeEvent(self, event):
        self._bg_pm = None    # 高度变化则缓存失效重建
        super().resizeEvent(event)

    # ---- 绘制 ----

    def _bg_pixmap(self) -> QPixmap:
        """圆柱凸起的分层渐变底: 与宽度无关, 缓存窄条横向拉伸 (含高DPI)"""
        h = self.height()
        if self._bg_pm is None or self._bg_pm.height() != h:
            dpr = self.devicePixelRatioF()
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0.00, QColor("#fbfdff"))   # 顶高光
            grad.setColorAt(0.38, QColor("#e9eef5"))   # 柱面反射带
            grad.setColorAt(0.46, QColor("#dbe2eb"))
            grad.setColorAt(0.56, QColor("#c7d0db"))   # 柱面中线 (视觉凸点)
            grad.setColorAt(1.00, QColor("#a9b4c2"))   # 底部压暗
            pm = QPixmap(int(32 * dpr), int(h * dpr))
            pm.setDevicePixelRatio(dpr)
            p = QPainter(pm)
            p.fillRect(0, 0, 32, h, grad)
            p.end()
            self._bg_pm = pm
        return self._bg_pm

    def paintSection(self, painter: QPainter, rect: QRect, logical: int):
        painter.save()
        # 1. 渐变底 (缓存位图拉伸, 不重算渐变)
        painter.drawPixmap(rect, self._bg_pixmap())

        rgt, bot = rect.right(), rect.bottom()
        # 2. hover 提亮 (画在文字下)
        if logical == self._hover:
            painter.fillRect(QRect(rect.left(), rect.top() + 1,
                                   rect.width(), rect.height() - 2),
                             QColor(255, 255, 255, 46))

        # 3. 立体边界: 顶高光 / 左亮右暗 / 底压线 -> 浮雕凸起
        painter.setPen(QColor("#ffffff"))
        painter.drawLine(rect.left(), rect.top(), rgt, rect.top())
        painter.setPen(QColor("#f4f7fa"))
        painter.drawLine(rect.left(), rect.top(), rect.left(), bot)
        painter.setPen(QColor("#96a1ad"))
        painter.drawLine(rgt, rect.top(), rgt, bot)
        painter.setPen(QColor("#8b96a3"))
        painter.drawLine(rect.left(), bot, rgt, bot)

        # 4. 列名 (先亮影再正文 -> 立体字; 右侧预留漏斗/排序三角区防遮挡)
        reserved = 4
        if logical in self._funnel_cols:
            reserved += 20
        if self.isSortIndicatorShown() \
                and self.sortIndicatorSection() == logical:
            reserved += 12
        text = self.model().headerData(
            logical, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        text = str(text or "")
        title = QRect(rect.left(), rect.top(),
                      max(8, rect.width() - reserved), rect.height())
        painter.setFont(self._title_font)
        painter.setPen(QColor("#f8fafc"))
        painter.drawText(title.translated(0, 1),
                         Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(QColor("#2f3b4a"))
        painter.drawText(title, Qt.AlignmentFlag.AlignCenter, text)

        # 5. 排序指示小三角 (漏斗左侧/无漏斗时右缘, 主题强调色)
        if self.isSortIndicatorShown() \
                and self.sortIndicatorSection() == logical:
            cx = rgt - (26 if logical in self._funnel_cols else 10)
            cy = rect.top() + rect.height() // 2
            if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder:
                pts = [(cx - 4, cy + 3), (cx + 4, cy + 3), (cx, cy - 3)]
            else:
                pts = [(cx - 4, cy - 3), (cx + 4, cy - 3), (cx, cy + 3)]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#4a7fb5"))
            painter.drawPolygon(
                QPolygonF([QPointF(px, py) for px, py in pts]))

        # 6. 漏斗 (自绘嵌入背景; hover 衬柔和圆角底, 激活态钢蓝)
        if logical in self._funnel_cols:
            fr = self._funnel_rect(logical)
            if not fr.isEmpty():
                if logical == self._hover_funnel:
                    painter.setRenderHint(
                        QPainter.RenderHint.Antialiasing)
                    painter.setPen(QColor("#96a1ad"))
                    painter.setBrush(QColor(255, 255, 255, 70))
                    painter.drawRoundedRect(fr.adjusted(-2, -2, 2, 2), 3, 3)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(
                    "#2f6ba3" if logical in self._active_funnels
                    else "#5d6874"))
                painter.drawPath(_funnel_path(fr.x() + 2.5, fr.y() + 2.5))
        painter.restore()

    # ---- 交互 (边界调宽优先; 其次漏斗; 再次排序; hover 只重绘涉及列) ----

    def _near_boundary(self, x: int) -> bool:
        """x 是否在某列边界 ±3px 内 (列宽拖拽手柄区, 优先级最高)"""
        for col in range(self.count()):
            if abs(x - (self.sectionViewportPosition(col)
                        + self.sectionSize(col))) <= 3:
                return True
        return False

    def set_sort_clicks(self, on: bool):
        """覆盖模式启用列头点击排序 (滚动模式关指示器与点击);
        时间列不参与排序: 指示器落在时间列时不显示"""
        self._sort_clicks = on
        self.setSortIndicatorShown(on and self.sortIndicatorSection() != 0)

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        idx = self.logicalIndexAt(pos)
        if event.button() == Qt.MouseButton.LeftButton \
                and not self._near_boundary(pos.x()) \
                and idx in self._funnel_cols \
                and self._funnel_rect(idx).contains(pos):
            self.filter_clicked.emit(idx)
            return    # 漏斗点击不触发排序
        if event.button() == Qt.MouseButton.LeftButton \
                and self._sort_clicks and not self._near_boundary(pos.x()) \
                and idx > 0:    # 时间列(0)不排序, 点击无动作
            # 三击循环: 升序 -> 降序 -> 取消 (恢复首次出现顺序)
            same = self.isSortIndicatorShown() \
                and self.sortIndicatorSection() == idx
            if same and self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder:
                self.setSortIndicator(idx, Qt.SortOrder.DescendingOrder)
            elif same:
                self.setSortIndicatorShown(False)   # 第三下: 取消排序
                self.sort_cleared.emit()
            else:
                self.setSortIndicator(idx, Qt.SortOrder.AscendingOrder)
                # 隐藏态下 setSortIndicator 不一定自动点亮: 显式开指示器
                self.setSortIndicatorShown(True)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        idx = self.logicalIndexAt(pos)
        fidx = -1
        if not self._near_boundary(pos.x()) and idx in self._funnel_cols \
                and self._funnel_rect(idx).contains(pos):
            fidx = idx
        if fidx != self._hover_funnel:
            old, self._hover_funnel = self._hover_funnel, fidx
            if old >= 0:
                self.updateSection(old)
            if fidx >= 0:
                self.updateSection(fidx)
        # 光标: 仅漏斗上手型; 其他位置交还 Qt (边界处显示调宽双箭头)
        if fidx >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        if idx != self._hover:
            old, self._hover = self._hover, idx
            if old >= 0:
                self.updateSection(old)
            if idx >= 0:
                self.updateSection(idx)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover >= 0:
            old, self._hover = self._hover, -1
            self.updateSection(old)
        if self._hover_funnel >= 0:
            old, self._hover_funnel = self._hover_funnel, -1
            self.updateSection(old)
        self.unsetCursor()
        super().leaveEvent(event)


class _ColumnFilterPopup(QFrame):
    """CANoe 式列筛选弹窗: 搜索框 + 该列已出现的不重复值勾选列表

    勾选语义: 全部勾选 = 不过滤(emit None); 部分勾选 = 只显示勾选值(emit set);
    全部不勾 = 该列无值可通过(emit 空 set)。
    搜索框只影响可见项; 全选/全不选按钮作用于当前可见项。
    """

    selection_changed = Signal(int, object)   # 列索引, None=不过滤 / set=勾选集

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("filterPopup")
        self._col = -1
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("搜索过滤条件..."))
        self._search.textChanged.connect(self._apply_search)
        lay.addWidget(self._search)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        all_btn = QPushButton(tr("全选"))
        all_btn.setProperty("btnRole", "neutral")
        all_btn.clicked.connect(lambda: self._check_visible(True))
        btn_row.addWidget(all_btn)
        none_btn = QPushButton(tr("全不选"))
        none_btn.setProperty("btnRole", "neutral")
        none_btn.clicked.connect(lambda: self._check_visible(False))
        btn_row.addWidget(none_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._list = QListWidget()
        self._list.setMinimumSize(180, 160)
        self._list.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self._list)

    def open_for(self, col: int, global_pos: QPoint, values: list, checked):
        """打开弹窗; values: [(原始值, 显示文本)] 已排序; checked: None=全选/set"""
        self._col = col
        self._loading = True
        self._search.clear()
        self._list.clear()
        for v, text in values:
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, v)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked
                             if (checked is not None and v not in checked)
                             else Qt.CheckState.Checked)
            self._list.addItem(it)
        self._loading = False
        self.move(global_pos)
        self.show()
        self._search.setFocus()

    def _apply_search(self, text: str):
        """按输入过滤可见项 (不改变勾选状态)"""
        needle = text.strip().lower()
        for i in range(self._list.count()):
            it = self._list.item(i)
            it.setHidden(bool(needle) and needle not in it.text().lower())

    def _check_visible(self, on: bool):
        """全选/全不选: 只作用于搜索后可见的项"""
        self._loading = True
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self._list.count()):
            it = self._list.item(i)
            if not it.isHidden():
                it.setCheckState(state)
        self._loading = False
        self._emit_selection()

    def _on_item_changed(self, _item):
        if not self._loading:
            self._emit_selection()

    def _emit_selection(self):
        """汇总勾选: 全勾=None(不过滤), 否则=勾选值集合"""
        checked = set()
        total = self._list.count()
        for i in range(total):
            it = self._list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                checked.add(it.data(Qt.ItemDataRole.UserRole))
        self.selection_changed.emit(
            self._col, None if len(checked) == total else checked)


class TraceView(QWidget):
    """Trace报文监控面板 - 全局统一单实例, 通道可切换"""

    def __init__(self, channel_key: str = "", parent=None):
        super().__init__(parent)
        self._hub = DataHub.instance()
        self._dm = DeviceManager.instance()
        self._ui = UISettings.instance()
        self._sub_id = f"trace_{id(self):x}"
        self._channel_key = channel_key or ""
        self._frames_buffer: list[FrameDTO] = []
        self._displayed_count = 0
        self._paused = False
        self._max_rows = 100              # 滚动模式只保留最近100行
        self._mode = "scroll"             # scroll=追加滚动 / overwrite=同(通道,ID)原位覆盖
        self._ow_items: dict[tuple, QTreeWidgetItem] = {}   # 覆盖模式行索引
        self._time_mode = "abs"         # abs=距零点 / delta=同(通道,ID)相邻帧时间差
        self._last_ts: dict[tuple, float] = {}   # 各键上一帧时间戳 (相对时间用)
        self._history: deque = deque(maxlen=_HISTORY_CAP)  # 帧临时存储
        self._t0: float | None = None   # 相对时间原点 (运行启动时刻, CANoe 式)
        self._hub_running = False       # 中台运行态 (清空时决定是否保原点)
        # 列筛选: 各列已出现的不重复值 (漏斗弹窗数据源, 随报文流累积)
        self._distinct: dict[int, set] = {c: set() for c in _FILTER_COLS}
        # 各列勾选状态: None=不过滤 / set=仅显示勾选值 (空set=全不显示)
        self._checked: dict[int, set | None] = {c: None for c in _FILTER_COLS}
        self._rx_count = 0
        self._tx_count = 0
        self._monitoring = False        # 监控态: 默认不开启, 点开始监控才订阅收帧

        self._setup_ui()
        self._hub.push.connect(self._on_push)

        # 全局进制/语言切换 -> 重格式化已显示行 / 重译表头
        self._ui.number_format_changed.connect(
            lambda _f: self._reformat_all())
        self._ui.language_changed.connect(self._on_language_changed)

        # 50ms批量刷新
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(50)
        self._refresh_timer.timeout.connect(self._refresh_table)
        self._refresh_timer.start()
        # 新一轮运行重置相对时间原点
        self._hub.running_changed.connect(self._on_running_changed)

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ---- 工具栏 (预留: 后续功能按钮在 addStretch 前扩展) ----
        toolbar_wrap = QWidget()
        toolbar_wrap.setObjectName("panelToolbar")
        toolbar_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        toolbar = QHBoxLayout(toolbar_wrap)
        toolbar.setContentsMargins(6, 4, 6, 4)
        toolbar.setSpacing(4)

        self._start_mon_btn = _ToolButton("run", "开始监控", "开始监控")
        self._start_mon_btn.clicked.connect(self._start_monitor)
        toolbar.addWidget(self._start_mon_btn)
        self._pause_btn = _ToolButton("pause", "暂停", "暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.clicked.connect(self._toggle_pause)
        toolbar.addWidget(self._pause_btn)
        self._stop_mon_btn = _ToolButton("stop", "停止监控", "停止监控", True)
        self._stop_mon_btn.clicked.connect(self._stop_monitor)
        toolbar.addWidget(self._stop_mon_btn)
        self._clear_btn = _ToolButton("clear", "清除", "清除")
        self._clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(self._clear_btn)
        self._update_monitor_buttons()
        toolbar.addSpacing(8)

        # 模式选择 (一个按钮两种状态): 滚动=追加流 / 覆盖=同(通道,ID)只留最新
        self._mode_btn = _ToolButton("scroll", "滚动模式", "滚动模式")
        self._mode_btn.setCheckable(True)
        self._mode_btn.clicked.connect(self._toggle_mode)
        toolbar.addWidget(self._mode_btn)
        toolbar.addSpacing(8)

        # 时间显示 (一个按钮两种状态): 绝对=距零点 / 相对=同标识相邻帧时间差
        self._time_btn = _ToolButton("abs_time", "绝对时间", "绝对时间")
        self._time_btn.setCheckable(True)
        self._time_btn.clicked.connect(self._toggle_time)
        toolbar.addWidget(self._time_btn)
        toolbar.addSpacing(8)

        # 查找: 输入框 + 上一个/下一个 (Enter=下一个, Shift+Enter=上一个)
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText(tr("查找: ID/报文名/数据"))
        self._find_edit.setClearButtonEnabled(True)
        self._find_edit.setFixedWidth(180)
        self._find_edit.installEventFilter(self)
        toolbar.addWidget(self._find_edit)
        self._find_prev_btn = _ToolButton("find_prev", "上一个", "上一个")
        self._find_prev_btn.clicked.connect(self._find_prev)
        toolbar.addWidget(self._find_prev_btn)
        self._find_next_btn = _ToolButton("find_next", "下一个", "下一个")
        self._find_next_btn.clicked.connect(self._find_next)
        toolbar.addWidget(self._find_next_btn)

        toolbar.addStretch()
        layout.addWidget(toolbar_wrap)

        # ---- 报文表格 (QTreeWidget: 可解析报文 CANoe 式展开信号子行) ----
        self._table = QTreeWidget()
        self._table.setColumnCount(len(ALL_COLUMNS))
        # 自定义表头: 圆柱凸起渐变 + 列头漏斗筛选 (CANoe 式);
        # 表头背景渐变预渲染缓存, 不随数据流刷新
        header = _TraceHeaderView(self._table)
        self._table.setHeader(header)
        self._header = header
        for col in _FILTER_COLS:
            header.add_funnel(col)
        header.filter_clicked.connect(self._on_funnel_clicked)
        # 列筛选弹窗 (单例复用)
        self._popup = _ColumnFilterPopup(self)
        self._popup.selection_changed.connect(self._on_col_filter)
        self._apply_headers()

        # CANoe 风格: 无网格、报文叠报文顺序排列、等宽字体紧凑行
        self._table.setRootIsDecorated(True)      # 展开标识 (仅可解析报文显示)
        self._table.setIndentation(14)
        self._table.setUniformRowHeights(True)    # 大量行性能关键
        self._table.setAlternatingRowColors(False)
        self._table.setFont(QFont("Consolas", 9))
        # CANoe 式分支图标: 矢量代理样式自绘加/减号 (仅本树, 不影响其他面板;
        # 不用 QSS image:url 位图 -- 高DPI下模糊且与原生箭头叠印出重影)
        self._branch_style = _BranchIndicatorStyle(self._table.style())
        self._table.setStyle(self._branch_style)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 排序按模式: 滚动模式禁用 (时间流), 覆盖模式列头点击由表头自管重排
        self._table.setSortingEnabled(False)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        header.sort_cleared.connect(self._on_sort_cleared)
        self._table.itemExpanded.connect(self._on_item_expanded)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(40)   # 防列名与漏斗挤压
        header.setSectionsMovable(True)    # 拖拽调整列顺序
        header.setFirstSectionMovable(False)   # 时间列固定首位 (树展开箭头所在列)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_column_menu)

        widths = [110, 70, 66, 90, 150, 70, 220]
        for i, w in enumerate(widths):
            self._table.setColumnWidth(i, w)
        layout.addWidget(self._table)

        self._stats_label = QLabel("总帧: 0 | RX: 0 | TX: 0")
        self._stats_label.setStyleSheet("color: #6c7086; padding: 2px;")
        layout.addWidget(self._stats_label)

    def _apply_headers(self):
        """表头: 按语言翻译 + 数据列后缀随进制"""
        cols = [tr(c) for c in ALL_COLUMNS]
        suffix = "Hex" if self._ui.is_hex() else "Dec"
        cols[_COL_DATA] = f"{tr('数据')}({suffix})"
        self._table.setHeaderLabels(cols)

    # ------------------------------------------------------------------ #
    #  订阅 (开始监控时注册, 切通道即重新注册)
    # ------------------------------------------------------------------ #

    def _resubscribe(self):
        if not self._monitoring:
            return   # 未开启监控: 保持未订阅状态
        # KIND_MESSAGE 不消费其推送, 只为让中台对本通道帧做 DBC 解码
        # (解码按 通道+ID 查该通道绑定的 DBC, 信号挂到 FrameDTO.signals)
        kinds = {KIND_FRAME, KIND_MESSAGE, KIND_STATS}
        channels = [self._channel_key] if self._channel_key else None
        if self._hub.get_subscription(self._sub_id):
            self._hub.update_subscription(
                self._sub_id, kinds=kinds, channels=channels)
        else:
            self._hub.register(self._sub_id, kinds, channels=channels)

    def _on_push(self, sid: str, kind: str, payload):
        """中台推送 - 只收数据不做计算"""
        if sid != self._sub_id:
            return
        if kind == KIND_FRAME:
            if not self._paused:
                # 累积各列已出现的不重复值 (漏斗弹窗数据源)
                dch = self._distinct[_COL_CH]
                ddir = self._distinct[_COL_DIR]
                did = self._distinct[_COL_ID]
                dnm = self._distinct[_COL_NAME]
                ddlc = self._distinct[_COL_DLC]
                ddata = self._distinct[_COL_DATA]
                for f in payload:
                    dch.add(f.channel_key)
                    ddir.add(f.direction)
                    did.add(f.id)
                    dnm.add(f.name)
                    ddlc.add(f.dlc)
                    if len(ddata) < _DISTINCT_CAP:   # 载荷多变, 防无限增长
                        ddata.add(bytes(f.data))
                self._frames_buffer.extend(payload)
                self._history.extend(payload)   # 临时存储 (停止监控时全量回看)
        elif kind == KIND_STATS:
            # payload 为所选通道的统计快照
            self._rx_count = sum(s.rx_count for s in payload)
            self._tx_count = sum(s.tx_count for s in payload)
            self._stats_label.setText(
                f"总帧: {self._rx_count + self._tx_count} | "
                f"RX: {self._rx_count} | TX: {self._tx_count}")

    # ------------------------------------------------------------------ #
    #  展示
    # ------------------------------------------------------------------ #

    def _refresh_table(self):
        if not self._frames_buffer:
            return
        batch = self._frames_buffer[:200]
        self._frames_buffer = self._frames_buffer[200:]

        for frame in batch:
            if not self._matches_filter(frame):
                continue
            if self._mode == "overwrite":
                self._upsert_overwrite(frame)
            else:
                self._append_scroll(frame)
    
        if self._mode == "scroll" and self._table.topLevelItemCount() > 0:
            self._table.scrollToBottom()
    
    def _append_scroll(self, frame: FrameDTO, abs_rel: float = None,
                       delta: float = None, cap: bool = True):
        """滚动模式: 按时间追加; cap=True 只保留最近 _max_rows 行; 不可展开不排序"""
        if cap and self._table.topLevelItemCount() >= self._max_rows:
            self._table.takeTopLevelItem(0)
        if abs_rel is None:
            abs_rel, delta = self._calc_times(frame)
        item = _TraceItem([
            self._fmt_time(abs_rel, delta),
            frame.channel_key,
            frame.direction,
            self._ui.fmt_id(frame.id),
            frame.name,
            str(frame.dlc),
            self._ui.fmt_data(frame.data),
        ])
        if frame.direction == "TX":
            for c in range(len(ALL_COLUMNS)):
                item.setForeground(c, QColor("#2f7fd0"))
        # 存下 DTO 供进制切换重格式化 (滚动模式不设展开标识=不可展开)
        item.setData(0, _ROLE_FRAME, frame)
        item.setData(0, _ROLE_TABS, abs_rel)
        item.setData(0, _ROLE_TDELTA, delta)
        self._table.addTopLevelItem(item)
        self._displayed_count += 1
    
    def _upsert_overwrite(self, frame: FrameDTO, abs_rel: float = None,
                          delta: float = None):
        """覆盖模式: (通道,ID) 唯一键原位覆盖为最新帧; 可展开可列头排序"""
        key = (frame.channel_key, frame.id)
        item = self._ow_items.get(key)
        if item is None:
            item = _TraceItem([""] * len(ALL_COLUMNS))
            self._ow_items[key] = item
            self._table.addTopLevelItem(item)
            self._displayed_count += 1
        if abs_rel is None:
            abs_rel, delta = self._calc_times(frame)
        was_filled = bool(item.data(0, _ROLE_FILLED))
        item.setText(0, self._fmt_time(abs_rel, delta))
        item.setText(1, frame.channel_key)
        item.setText(2, frame.direction)
        item.setText(3, self._ui.fmt_id(frame.id))
        item.setText(4, frame.name)
        item.setText(5, str(frame.dlc))
        item.setText(6, self._ui.fmt_data(frame.data))
        for c in range(len(ALL_COLUMNS)):
            if frame.direction == "TX":
                item.setForeground(c, QColor("#2f7fd0"))
            else:   # TX->RX 翻转时清回默认前景
                item.setData(c, Qt.ItemDataRole.ForegroundRole, None)
        item.setData(0, _ROLE_FRAME, frame)
        item.setData(0, _ROLE_TABS, abs_rel)
        item.setData(0, _ROLE_TDELTA, delta)
        item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
            if frame.signals else
            QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        if was_filled:   # 信号子行随新 DTO: 清掉, 展开态则立即重填
            item.setData(0, _ROLE_FILLED, False)
            item.takeChildren()
            if item.isExpanded():
                self._on_item_expanded(item)

    def _calc_times(self, frame: FrameDTO) -> tuple[float, float]:
        """计算行时间: (绝对=距零点秒, 相对=与同(通道,ID)上一帧时间差)"""
        if self._t0 is None:
            self._t0 = frame.timestamp   # 未运行时入表: 首帧兕底原点
        # 运行零点前到达的残留帧 (如跨进程时钟差) 钳到 0.000000
        abs_rel = max(0.0, frame.timestamp - self._t0)
        key = (frame.channel_key, frame.id)
        prev = self._last_ts.get(key)
        delta = max(0.0, frame.timestamp - prev) if prev is not None else 0.0
        self._last_ts[key] = frame.timestamp
        return abs_rel, delta

    def _fmt_time(self, abs_rel: float, delta: float) -> str:
        """按当前时间显示模式格式化时间列"""
        v = delta if self._time_mode == "delta" else abs_rel
        return f"{v:.6f}"

    def _replay_history(self, limit: int | None):
        """滚动模式由临时历史重建表: limit=None 全量 (停止监控), 否则最近 limit 条"""
        self._table.setUpdatesEnabled(False)
        try:
            while self._table.topLevelItemCount():
                self._table.takeTopLevelItem(0)
            self._ow_items.clear()
            self._last_ts.clear()   # 按回放顺序重算相对时间
            frames = list(self._history)[-limit:] if limit \
                else list(self._history)
            for f in frames:
                if self._matches_filter(f):
                    self._append_scroll(f, cap=False)
        finally:
            self._table.setUpdatesEnabled(True)

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """首次展开: 用 DTO 已解码信号填充子行 (UI 只展示, 不做解码)"""
        if item.data(0, _ROLE_FILLED):
            return
        frame = item.data(0, _ROLE_FRAME)
        if frame is None or not frame.signals:
            return
        item.setData(0, _ROLE_FILLED, True)
        gray = QColor("#6c7280")
        last = len(frame.signals) - 1
        for i, sv in enumerate(frame.signals):
            if sv.value_desc:
                val = f"{sv.value_desc} (0x{sv.raw:X})"
            else:
                val = f"{sv.phys:g} {sv.unit}".strip()
            # 树形引导符: 与父行报文名形成层次 (CANoe 式信号列表)
            guide = "└─ " if i == last else "├─ "
            # 名称放第 0 列并跨列: 文本随树缩进落在小加号正下方,
            # 形成 CANoe 式树线连接感 (时间列不适用于信号行)
            child = QTreeWidgetItem([f"{guide}{sv.name}: {val}"])
            child.setForeground(0, gray)
            child.setData(0, _ROLE_CHILD_IDX, i)   # 覆盖模式排序保信号原序
            item.addChild(child)
            # 入树后再置跨列 (入树前设置会被忽略)
            child.setFirstColumnSpanned(True)

    def _reformat_all(self):
        """进制切换: 重格式化已显示行的 ID/数据列 + 刷新表头"""
        self._apply_headers()
        for i in range(self._table.topLevelItemCount()):
            item = self._table.topLevelItem(i)
            frame = item.data(0, _ROLE_FRAME)
            if frame is None:
                continue
            item.setText(_COL_ID, self._ui.fmt_id(frame.id))
            item.setText(_COL_DATA, self._ui.fmt_data(frame.data))

    def _matches_filter(self, frame: FrameDTO) -> bool:
        """显示过滤: 列勾选集为 None 不过滤, 否则值必须在勾选集内"""
        ch = self._checked[_COL_CH]
        if ch is not None and frame.channel_key not in ch:
            return False
        dr = self._checked[_COL_DIR]
        if dr is not None and frame.direction not in dr:
            return False
        ids = self._checked[_COL_ID]
        if ids is not None and frame.id not in ids:
            return False
        nm = self._checked[_COL_NAME]
        if nm is not None and frame.name not in nm:
            return False
        dlc = self._checked[_COL_DLC]
        if dlc is not None and frame.dlc not in dlc:
            return False
        data = self._checked[_COL_DATA]
        if data is not None and bytes(frame.data) not in data:
            return False
        return True

    # ------------------------------------------------------------------ #
    #  交互
    # ------------------------------------------------------------------ #

    def _on_funnel_clicked(self, col: int):
        """打开列筛选弹窗: 列出该列已出现的不重复值 (ID/DLC按数值排序)"""
        vals = self._distinct.get(col) or set()
        if col == _COL_ID:
            items = [(v, self._ui.fmt_id(v)) for v in sorted(vals)]
        elif col == _COL_DATA:
            items = [(v, self._ui.fmt_data(v)) for v in sorted(vals)]
        else:
            items = [(v, str(v)) for v in sorted(vals)]
        self._popup.open_for(col, self._header.funnel_anchor_pos(col),
                             items, self._checked[col])

    def _on_col_filter(self, col: int, checked):
        """勾选变化 -> 更新过滤条件 + 漏斗激活态 + 重筛已显示行"""
        self._checked[col] = checked
        self._header.set_funnel_active(col, checked is not None)
        self._refilter_rows()

    def _refilter_rows(self):
        """按当前勾选条件重筛已显示行 (行存了 DTO, 纯内存判断)"""
        for i in range(self._table.topLevelItemCount()):
            it = self._table.topLevelItem(i)
            f = it.data(0, _ROLE_FRAME)
            # 隐藏父行即整组隐藏 (含已展开的信号子行)
            it.setHidden(f is not None and not self._matches_filter(f))

    def _on_language_changed(self, _lang):
        """语言切换: 重译表头 + 工具栏按钮"""
        self._apply_headers()
        for btn in (self._start_mon_btn, self._pause_btn, self._stop_mon_btn,
                    self._clear_btn, self._find_prev_btn, self._find_next_btn):
            btn.setText(tr(btn._text_key))
            btn.setToolTip(tr(btn._tooltip_key))
        # 暂停按钮文字由状态驱动, 循环后再按当前态覆盖
        self._pause_btn.setText(tr("继续") if self._paused else tr("暂停"))
        # 模式按钮文字/提示同样由状态驱动
        mode_label = tr("覆盖模式") if self._mode == "overwrite" \
            else tr("滚动模式")
        self._mode_btn.setText(mode_label)
        self._mode_btn.setToolTip(mode_label)
        # 时间显示按钮文字/提示同样由状态驱动
        time_label = tr("相对时间") if self._time_mode == "delta" \
            else tr("绝对时间")
        self._time_btn.setText(time_label)
        self._time_btn.setToolTip(time_label)
        self._find_edit.setPlaceholderText(tr("查找: ID/报文名/数据"))

    def _start_monitor(self):
        """开始监控: 订阅中台推送 (面板创建时默认不订阅)"""
        if self._monitoring:
            return
        self._monitoring = True
        self._resubscribe()
        if self._mode == "scroll":
            # 恢复 live 滚动: 先回放到最近 100 行再继续追加
            self._replay_history(self._max_rows)
        self._update_monitor_buttons()

    def _stop_monitor(self):
        """停止监控: 注销订阅, 不再接收新帧 (已显示内容保留, 可继续查看/筛选)"""
        if not self._monitoring:
            return
        self._monitoring = False
        self._hub.unregister(self._sub_id)
        if self._mode == "scroll":
            # 停止监控: 滚动模式展示临时历史全量 (一万条)
            self._replay_history(None)
        if self._paused:   # 停止即解除暂停, 避免下次开始仍处冻结态
            self._paused = False
            self._pause_btn.setChecked(False)
            self._pause_btn.setText(tr("暂停"))
            self._pause_btn._icon_key = "pause"
        self._update_monitor_buttons()

    def _update_monitor_buttons(self):
        self._start_mon_btn.setEnabled(not self._monitoring)
        self._pause_btn.setEnabled(self._monitoring)
        self._stop_mon_btn.setEnabled(self._monitoring)

    def _toggle_pause(self, checked):
        self._paused = checked
        self._pause_btn.setText(tr("继续") if checked else tr("暂停"))
        # 图标随状态: 暂停中显示运行三角, 提示点击即恢复
        self._pause_btn._icon_key = "run" if checked else "pause"
        self._pause_btn.update()

    def _toggle_mode(self, checked: bool):
        """模式切换 (一个按钮两种状态): checked=覆盖 / unchecked=滚动"""
        self._mode = "overwrite" if checked else "scroll"
        label = tr("覆盖模式") if checked else tr("滚动模式")
        self._mode_btn.setText(label)
        self._mode_btn.setToolTip(label)
        self._mode_btn._icon_key = "overwrite" if checked else "scroll"
        self._mode_btn.update()
        self._rebuild_for_mode()

    def _toggle_time(self, checked: bool):
        """时间显示切换 (一个按钮两种状态): checked=相对(同标识相邻帧时间差)"""
        self._time_mode = "delta" if checked else "abs"
        label = tr("相对时间") if checked else tr("绝对时间")
        self._time_btn.setText(label)
        self._time_btn.setToolTip(label)
        self._time_btn._icon_key = "delta_time" if checked else "abs_time"
        self._time_btn.update()
        # 已显示行按行存的双时间重刷时间列
        for i in range(self._table.topLevelItemCount()):
            it = self._table.topLevelItem(i)
            a = it.data(0, _ROLE_TABS)
            d = it.data(0, _ROLE_TDELTA)
            if a is not None:
                it.setText(0, self._fmt_time(a, d or 0.0))

    # ------------------------------------------------------------------ #
    #  查找 (工具栏: 输入框 + 上/下一个, 环绕式)
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj, event):
        """查找输入框回车快捷: Enter=下一个, Shift+Enter=上一个"""
        if obj is self._find_edit \
                and event.type() == QEvent.Type.KeyPress \
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._find_prev()
            else:
                self._find_next()
            return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _find_haystack(item: QTreeWidgetItem) -> str:
        """行匹配素材: ID(hex/dec) + 报文名 + 通道 + 方向 + 数据(连续/空格hex)"""
        f = item.data(0, _ROLE_FRAME)
        if f is None:
            return ""
        raw = bytes(f.data).hex()
        spaced = " ".join(raw[i:i + 2] for i in range(0, len(raw), 2))
        return (f"{f.id:x} {f.id} {f.name} {f.channel_key} "
                f"{f.direction} {raw} {spaced}").lower()

    def _find_step(self, backward: bool):
        """从当前选中行出发环绕查找; 命中选中并居中滚动, 未命中输入框红框闪示"""
        kw = self._find_edit.text().strip().lower()
        if not kw:
            return
        n = self._table.topLevelItemCount()
        if n == 0:
            return self._flash_find(False)
        cur = self._table.currentItem()
        start = self._table.indexOfTopLevelItem(cur) if cur is not None else -1
        if backward:
            seq = list(range(start - 1, -1, -1)) + list(range(n - 1, start, -1))
        else:
            seq = list(range(start + 1, n)) + list(range(0, start + 1))
        for i in seq:
            it = self._table.topLevelItem(i)
            if it.isHidden():   # 被漏斗过滤隐藏的行跳过
                continue
            if kw in self._find_haystack(it):
                self._table.clearSelection()
                self._table.setCurrentItem(it)
                self._table.scrollToItem(
                    it, QAbstractItemView.ScrollHint.PositionAtCenter)
                self._flash_find(True)
                return
        self._flash_find(False)

    def _find_next(self):
        self._find_step(False)

    def _find_prev(self):
        self._find_step(True)

    def _flash_find(self, ok: bool):
        """查找反馈: 未命中时输入框红框闪示 600ms"""
        if ok:
            self._find_edit.setStyleSheet("")
            return
        self._find_edit.setStyleSheet(
            "QLineEdit { border: 1px solid #e53935; }")
        QTimer.singleShot(600, lambda: self._find_edit.setStyleSheet(""))

    def _rebuild_for_mode(self):
        """按新模式语义重建已有行: 覆盖=同(通道,ID)去重留最新, 滚动=恢复时间序并截顶"""
        rows = []
        for i in range(self._table.topLevelItemCount()):
            it = self._table.topLevelItem(i)
            f = it.data(0, _ROLE_FRAME)
            if f is not None:
                # 连同已算好的绝对/相对时间一起搬移 (重建不重算时间差)
                rows.append((f, it.data(0, _ROLE_TABS),
                             it.data(0, _ROLE_TDELTA)))
        while self._table.topLevelItemCount():
            self._table.takeTopLevelItem(0)
        self._ow_items.clear()
        if self._mode == "overwrite":
            seen: dict[tuple, tuple] = {}
            for f, a, d in rows:
                seen[(f.channel_key, f.id)] = (f, a, d)   # 后到帧覆盖先到帧
            for f, a, d in seen.values():
                self._upsert_overwrite(f, a, d)
            hdr = self._table.header()
            hdr.set_sort_clicks(True)   # 覆盖模式: 列头可点击排序 (时间列除外)
            # 已有行按当前排序列重排一次 (数值感知; 指示器未显示=未排序)
            if hdr.isSortIndicatorShown():
                self._on_sort_changed(hdr.sortIndicatorSection(),
                                      hdr.sortIndicatorOrder())
        else:
            if not self._monitoring:
                # 停止态切回滚动: 展示临时历史全量
                self._replay_history(None)
            else:
                for f, a, d in rows[-self._max_rows:]:
                    self._append_scroll(f, a, d)
            self._table.header().set_sort_clicks(False)

    def _on_sort_changed(self, col: int, order):
        """覆盖模式列头排序: Python 端数值感知重排顶层行 (子行随父行)"""
        if self._mode != "overwrite" or col <= 0:   # 时间列不排序
            return
        items = [self._table.takeTopLevelItem(0)
                 for _ in range(self._table.topLevelItemCount())]
        items.sort(key=lambda it: self._sort_key(it, col),
                   reverse=order == Qt.SortOrder.DescendingOrder)
        for i, it in enumerate(items):
            self._table.insertTopLevelItem(i, it)

    @staticmethod
    def _sort_key(item: QTreeWidgetItem, col: int):
        """排序键: 时间/DLC/ID 按数值, 其余列按字符串 (元组保类型同质)"""
        num = _TraceItem._num(item.text(col), col)
        if num is None:
            return (1, 0.0, item.text(col))
        return (0, float(num), "")

    def _on_sort_cleared(self):
        """取消排序 (第三下点击): 覆盖模式行恢复首次出现顺序"""
        if self._mode != "overwrite":
            return
        # _ow_items 为插入序字典, 按其顺序重排顶层行
        for i, it in enumerate(self._ow_items.values()):
            self._table.insertTopLevelItem(i, it)

    def _on_running_changed(self, running: bool):
        self._hub_running = running
        if running:
            # 以运行启动时刻为零点 (CANoe 测量起点), 与首帧何时到无关;
            # 启动前积压帧已被中台 begin_polling 丢弃, 不会拉偏时间轴
            self._t0 = time.time()

    def _clear(self):
        self._table.clear()
        self._ow_items.clear()
        self._last_ts.clear()
        self._history.clear()
        self._frames_buffer.clear()
        self._displayed_count = 0
        if not self._hub_running:
            self._t0 = None   # 运行中清空保原点 (CANoe 测量时间不重置)

    def _on_column_menu(self, pos):
        header = self._table.header()
        logical_index = header.logicalIndexAt(pos)
        if logical_index < 0:
            return
        menu = QMenu(self)
        hitem = self._table.headerItem()
        for i in range(self._table.columnCount()):
            col_name = hitem.text(i) if hitem else ALL_COLUMNS[i]
            action = menu.addAction(col_name)
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(i))
            action.toggled.connect(
                lambda checked, idx=i: self._table.setColumnHidden(
                    idx, not checked))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def set_channel(self, channel_key: str):
        """切换订阅通道 (重新订阅; 列头漏斗的通道过滤不受影响)"""
        self._channel_key = channel_key or ""
        self._resubscribe()
        self._clear()

    def closeEvent(self, event):
        self._hub.unregister(self._sub_id)
        super().closeEvent(event)
