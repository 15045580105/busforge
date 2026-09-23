"""
ProjectTree - 项目导航树

支持多项目管理：可同时创建多个项目，点击切换。
所有节点图标使用 QPainter 绘制，与工具栏风格统一。
支持: 创建项目 / 保存 / 导出 / 导入 / 多项目切换
"""

import json
import logging
import math
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QMenu, QFileDialog, QMessageBox, QInputDialog,
    QStyledItemDelegate, QStyle, QApplication, QStyleOptionViewItem,
    QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QRectF, QRect, QPointF, QSize
from PySide6.QtGui import (
    QAction, QFont, QPainter, QColor, QPen, QBrush, QPainterPath, QIcon, QPalette
)

from app.devices.device_manager import DeviceManager
from app.datahub.data_hub import DataHub
from app.common.ui_settings import UISettings
from app.common.workspace import WorkspaceManager
from app.common.i18n import tr

logger = logging.getLogger(__name__)


# ============================================================
# 项目管理器 - 管理多项目列表和切换
# ============================================================

class ProjectInfo:
    """单个项目的元数据"""
    def __init__(self, name: str, file_path: str = "", project_id: str = ""):
        self.name = name
        self.file_path = file_path  # .bfproj 文件路径，空表示未保存
        # 稳定唯一标识，用作 DeviceManager 工程池的键（index 会随增删变动）
        # 会话恢复时传入已有 project_id 以保证设备池键一致
        self.project_id = project_id or uuid.uuid4().hex[:12]


class ProjectManager:
    """管理多个项目，支持创建/切换/删除"""

    def __init__(self):
        self._projects: list[ProjectInfo] = []
        self._active_index: int = -1

    @property
    def projects(self) -> list[ProjectInfo]:
        return self._projects

    @property
    def active_project(self) -> Optional[ProjectInfo]:
        if 0 <= self._active_index < len(self._projects):
            return self._projects[self._active_index]
        return None

    @property
    def active_index(self) -> int:
        return self._active_index

    @property
    def project_count(self) -> int:
        return len(self._projects)

    def create_project(self, name: str, project_id: str = "") -> ProjectInfo:
        """创建新项目并设为当前活动项目 (project_id 为空则自动生成)"""
        info = ProjectInfo(name, project_id=project_id)
        self._projects.append(info)
        self._active_index = len(self._projects) - 1
        return info

    def switch_to(self, index: int) -> Optional[ProjectInfo]:
        """切换到指定项目"""
        if 0 <= index < len(self._projects):
            self._active_index = index
            return self._projects[index]
        return None

    def remove_project(self, index: int) -> Optional[ProjectInfo]:
        """删除项目"""
        if 0 <= index < len(self._projects):
            info = self._projects.pop(index)
            if self._active_index >= len(self._projects):
                self._active_index = len(self._projects) - 1
            return info
        return None

    def rename_project(self, index: int, new_name: str):
        """重命名项目"""
        if 0 <= index < len(self._projects):
            self._projects[index].name = new_name

    def set_file_path(self, index: int, path: str):
        """设置项目文件路径（保存后调用）"""
        if 0 <= index < len(self._projects):
            self._projects[index].file_path = path


# ============================================================
# 树节点图标绘制 - QPainter 绘制，与工具栏风格统一
# ============================================================

def _draw_icon_folder(painter, rect):
    """文件夹图标 - 项目节点"""
    painter.save()
    c = QColor("#f0b429")
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    r = rect.adjusted(1, 3, -1, -1)
    painter.drawRoundedRect(r, 2, 2)
    tab = QRectF(r.left(), r.top() - 3, r.width() * 0.4, 4)
    painter.drawRoundedRect(tab, 1, 1)
    painter.restore()


def _draw_icon_source(painter, rect):
    """信号源图标 - Source节点"""
    painter.save()
    c = QColor("#4a7fb5")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), 1.5, 1.5)
    for r_factor in [0.3, 0.55, 0.8]:
        r = rect.width() * r_factor / 2
        painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), -60 * 16, 120 * 16)
    painter.restore()


def _draw_icon_monitor(painter, rect):
    """显示器图标 - Monitor节点"""
    painter.save()
    c = QColor("#4a7fb5")
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    r = rect.adjusted(1, 1, -1, -4)
    painter.drawRoundedRect(r, 2, 2)
    inner = r.adjusted(2, 2, -2, -2)
    painter.setBrush(QBrush(QColor("#e0e7ee")))
    painter.drawRoundedRect(inner, 1, 1)
    painter.setBrush(QBrush(c))
    base = QRectF(rect.center().x() - 4, r.bottom(), 8, 3)
    painter.drawRect(base)
    painter.restore()


def _draw_icon_bus(painter, rect, color="#4a7fb5"):
    """总线连接器图标 - CAN/LIN/INTERNET"""
    painter.save()
    c = QColor(color)
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(cx - 5, cy - 4), QPointF(cx - 5, cy + 4))
    painter.drawLine(QPointF(cx + 5, cy - 4), QPointF(cx + 5, cy + 4))
    painter.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
    painter.setBrush(QBrush(c))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(cx, cy), 2, 2)
    painter.restore()


def _draw_icon_device(painter, rect):
    """芯片/设备图标"""
    painter.save()
    c = QColor("#5a6c7d")
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    r = rect.adjusted(2, 2, -2, -2)
    painter.drawRoundedRect(r, 2, 2)
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 1.5))
    for y_off in [-3, 0, 3]:
        painter.drawLine(QPointF(r.left() - 2, cy + y_off), QPointF(r.left(), cy + y_off))
        painter.drawLine(QPointF(r.right(), cy + y_off), QPointF(r.right() + 2, cy + y_off))
    painter.restore()


def _draw_icon_channel(painter, rect):
    """通道/插孔图标"""
    painter.save()
    c = QColor("#78909c")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), 5, 5)
    painter.drawPoint(QPointF(cx, cy))
    painter.restore()


def _draw_icon_database(painter, rect):
    """数据库圆柱图标"""
    painter.save()
    c = QColor("#8d6e63")
    cx, cy = rect.center().x(), rect.center().y()
    w, h = rect.width() * 0.7, rect.height() * 0.7
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    painter.drawEllipse(QRectF(cx - w/2, cy - h/2 - 2, w, 5))
    painter.drawRect(QRectF(cx - w/2, cy - h/2, w, h))
    painter.drawEllipse(QRectF(cx - w/2, cy + h/2 - 3, w, 5))
    painter.restore()


def _draw_icon_trace(painter, rect):
    """波形/Trace图标"""
    painter.save()
    c = QColor("#26a69a")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(cx - 7, cy)
    path.lineTo(cx - 4, cy - 4)
    path.lineTo(cx - 1, cy + 3)
    path.lineTo(cx + 2, cy - 3)
    path.lineTo(cx + 5, cy + 2)
    path.lineTo(cx + 7, cy)
    painter.drawPath(path)
    painter.restore()


def _draw_icon_signal(painter, rect):
    """信号波形图标"""
    painter.save()
    c = QColor("#42a5f5")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(cx - 7, cy + 2)
    path.cubicTo(cx - 4, cy - 5, cx - 1, cy + 5, cx + 2, cy - 3)
    path.cubicTo(cx + 4, cy - 6, cx + 6, cy + 1, cx + 7, cy)
    painter.drawPath(path)
    painter.restore()


def _draw_icon_graphy(painter, rect):
    """图表/Graphy图标"""
    painter.save()
    c = QColor("#ab47bc")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(cx - 6, cy - 6), QPointF(cx - 6, cy + 6))
    painter.drawLine(QPointF(cx - 6, cy + 6), QPointF(cx + 7, cy + 6))
    painter.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    path = QPainterPath()
    path.moveTo(cx - 4, cy + 4)
    path.lineTo(cx - 1, cy)
    path.lineTo(cx + 2, cy + 2)
    path.lineTo(cx + 5, cy - 4)
    painter.drawPath(path)
    painter.restore()


def _draw_icon_panel(painter, rect):
    """面板/仪表盘图标"""
    painter.save()
    c = QColor("#78909c")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    r = rect.adjusted(1, 1, -1, -1)
    painter.drawRoundedRect(r, 2, 2)
    painter.setBrush(QBrush(QColor("#e0e7ee")))
    s = r.width() * 0.35
    painter.drawRect(QRectF(cx - s - 1, cy - s - 1, s * 0.9, s * 0.9))
    painter.drawRect(QRectF(cx + 1, cy - s - 1, s * 0.9, s * 0.9))
    painter.drawRect(QRectF(cx - s - 1, cy + 1, s * 0.9, s * 0.9))
    painter.drawRect(QRectF(cx + 1, cy + 1, s * 0.9, s * 0.9))
    painter.restore()


def _draw_icon_uds(painter, rect):
    """扳手/UDS诊断图标"""
    painter.save()
    c = QColor("#ef5350")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(cx - 4, cy + 5), QPointF(cx + 4, cy - 5))
    painter.drawEllipse(QPointF(cx + 4, cy - 5), 3, 3)
    painter.restore()


def _draw_icon_script(painter, rect):
    """代码/脚本图标"""
    painter.save()
    c = QColor("#66bb6a")
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(cx - 4, cy - 6), QPointF(cx - 4, cy + 6))
    painter.drawLine(QPointF(cx - 4, cy + 6), QPointF(cx + 4, cy + 6))
    painter.drawLine(QPointF(cx + 4, cy + 6), QPointF(cx + 4, cy - 3))
    painter.drawLine(QPointF(cx + 4, cy - 3), QPointF(cx + 1, cy - 6))
    painter.drawLine(QPointF(cx + 1, cy - 6), QPointF(cx - 4, cy - 6))
    painter.setPen(QPen(c, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p1 = QPainterPath()
    p1.moveTo(cx - 2, cy - 2)
    p1.lineTo(cx - 4, cy)
    p1.lineTo(cx - 2, cy + 2)
    painter.drawPath(p1)
    p2 = QPainterPath()
    p2.moveTo(cx + 2, cy - 2)
    p2.lineTo(cx + 4, cy)
    p2.lineTo(cx + 2, cy + 2)
    painter.drawPath(p2)
    painter.restore()


def _draw_icon_dbc_file(painter, rect):
    """DBC 文件图标 - 已导入的 DBC 实例子节点 (与上层容器圆柱区分)"""
    painter.save()
    c = QColor("#8d6e63")
    painter.setBrush(QBrush(QColor("#efe6e2")))
    painter.setPen(QPen(c, 1.2))
    r = rect.adjusted(2, 1, -2, -1)
    fold = 4
    path = QPainterPath()
    path.moveTo(r.left(), r.top())
    path.lineTo(r.right() - fold, r.top())
    path.lineTo(r.right(), r.top() + fold)
    path.lineTo(r.right(), r.bottom())
    path.lineTo(r.left(), r.bottom())
    path.closeSubpath()
    painter.drawPath(path)
    painter.setPen(QPen(c, 1.2))
    for y_off in [3, 6, 9]:
        painter.drawLine(QPointF(r.left() + 2, r.top() + fold + y_off),
                         QPointF(r.right() - 2, r.top() + fold + y_off))
    painter.restore()


def _draw_icon_transmit(painter, rect):
    """仿真发送图标 - 发送箭头"""
    painter.save()
    c = QColor("#26a69a")
    painter.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    path = QPainterPath()
    path.moveTo(cx - 6, cy)
    path.lineTo(cx + 6, cy)
    path.moveTo(cx + 2, cy - 4)
    path.lineTo(cx + 6, cy)
    path.lineTo(cx + 2, cy + 4)
    painter.drawPath(path)
    painter.restore()


def _draw_icon_sim(painter, rect):
    """仿真图标 - 函数发生器: 方框内正弦波"""
    painter.save()
    c = QColor("#26a69a")
    painter.setPen(QPen(c, 1.4))
    painter.setBrush(QBrush(QColor("#e2f3f1")))
    r = rect.adjusted(1, 2, -1, -2)
    painter.drawRoundedRect(r, 2, 2)
    painter.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cy = rect.center().y()
    path = QPainterPath()
    path.moveTo(r.left() + 2, cy)
    path.cubicTo(r.left() + r.width() * 0.25, cy - 4,
                 r.left() + r.width() * 0.35, cy - 4,
                 r.left() + r.width() * 0.5, cy)
    path.cubicTo(r.left() + r.width() * 0.65, cy + 4,
                 r.left() + r.width() * 0.75, cy + 4,
                 r.right() - 2, cy)
    painter.drawPath(path)
    painter.restore()


def _draw_monitor_frame(painter, rect):
    """真实监控实例标识: 窗口外框 + 标题栏线, 与功能分类图标区分"""
    painter.save()
    c = QColor("#5a6c7d")
    painter.setPen(QPen(c, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    painter.drawRoundedRect(r, 2, 2)
    ty = r.top() + 3.5
    painter.drawLine(QPointF(r.left() + 1, ty), QPointF(r.right() - 1, ty))
    painter.restore()


def _draw_icon_logger(painter, rect):
    """Logger 图标 - 记录盘: 外圈 + 红芯"""
    painter.save()
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) * 0.32
    painter.setPen(QPen(QColor("#5a6c7d"), 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#e53935")))
    painter.drawEllipse(QPointF(cx, cy), r * 0.42, r * 0.42)
    painter.restore()


# 图标绘制函数映射
ICON_DRAWERS = {
    "project": _draw_icon_folder,
    "source": _draw_icon_source,
    "monitor": _draw_icon_monitor,
    "can_category": lambda p, r: _draw_icon_bus(p, r, "#4a7fb5"),
    "lin_category": lambda p, r: _draw_icon_bus(p, r, "#78909c"),
    "internet_category": lambda p, r: _draw_icon_bus(p, r, "#26a69a"),
    "device": _draw_icon_device,
    "channel": _draw_icon_channel,
    "sim": _draw_icon_sim,
    "database": _draw_icon_database,
    "channel_dbc": _draw_icon_database,
    "dbc_instance": _draw_icon_dbc_file,
    "trace": _draw_icon_trace,
    "signal": _draw_icon_signal,
    "graphy": _draw_icon_graphy,
    "panel": _draw_icon_panel,
    "uds": _draw_icon_uds,
    "script": _draw_icon_script,
    "transmit": _draw_icon_transmit,
    "logger": _draw_icon_logger,
}


# ============================================================
# 自定义树节点代理 - QPainter 绘制图标 + 文字
# ============================================================

class _TreeIconDelegate(QStyledItemDelegate):
    """为树节点绘制自定义图标，替代 emoji"""
    ICON_SIZE = 16

    def paint(self, painter, option, index):
        """绘制树节点 - 背景交给样式原语, 图标与文字仅自绘一次, 避免重复覆盖"""
        try:
            role = index.data(Qt.ItemDataRole.UserRole)
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""

            # 1. 用样式原语绘制背景/选中/悬停/焦点框, 清空文字与图标避免默认绘制叠加
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            opt.icon = QIcon()
            opt.decorationSize = QSize(0, 0)
            widget = option.widget
            style = widget.style() if widget is not None else QApplication.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

            # 2. 图标位置 (option.rect 已含缩进偏移, 无需再按深度累加)
            icon_size = self.ICON_SIZE
            icon_x = option.rect.left() + 4
            icon_rect = QRectF(
                icon_x,
                option.rect.center().y() - icon_size / 2,
                icon_size, icon_size
            )
            if role and role in ICON_DRAWERS:
                if role in PANEL_TYPES:
                    kind = index.data(Qt.ItemDataRole.UserRole + 1)
                    if kind == "panel_instance":
                        # 真实监控界面: 窗口外框 + 内部彩色图形
                        _draw_monitor_frame(painter, icon_rect)
                        ICON_DRAWERS[role](
                            painter, icon_rect.adjusted(2.5, 4.5, -1.5, -1.5))
                    else:
                        # 功能分类: 半透明图形, 表示"功能"而非打开的界面
                        painter.save()
                        painter.setOpacity(0.5)
                        ICON_DRAWERS[role](painter, icon_rect)
                        painter.restore()
                elif role in CATEGORY_LIKE:
                    # 容器大标签: 半透明, 与其下实例子节点区分 (参照 monitor 分类)
                    painter.save()
                    painter.setOpacity(0.5)
                    ICON_DRAWERS[role](painter, icon_rect)
                    painter.restore()
                else:
                    ICON_DRAWERS[role](painter, icon_rect)

            # 2.5 通道状态点 + 未绑定标记: 橙=未绑定 灰=已绑定未连 绿=连接 蓝=运行占有
            unbound = False
            if role == "channel":
                dm = DeviceManager.instance()
                ckey = index.data(Qt.ItemDataRole.UserRole + 1) or ""
                ch = dm.get_channel(ckey)
                dot_color = "#9aa9b5"
                if not dm.channel_bound(ckey):
                    dot_color = "#e8a33d"
                    unbound = True
                elif dm.channel_state(ckey) == "connected":
                    acq = ch is not None and dm.is_acquired(ch.device_id)
                    dot_color = "#2f7fd0" if acq else "#39b568"
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(dot_color)))
                painter.drawEllipse(
                    QPointF(icon_rect.right() - 1, icon_rect.top() + 1), 3, 3)

            # 2.6 运行徽标 (运行中项目根节点): 蓝色倒三角
            tree = self.parent()
            ridx = getattr(tree, "running_project_index", None)
            if role == "project" and ridx is not None \
                    and index.data(Qt.ItemDataRole.UserRole + 1) == ridx:
                bx, by = icon_rect.right() - 6, icon_rect.top()
                badge = QPainterPath()
                badge.moveTo(bx, by)
                badge.lineTo(bx + 6, by)
                badge.lineTo(bx + 3, by + 5)
                badge.closeSubpath()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#2f7fd0")))
                painter.drawPath(badge)

            # 3. 文字仅绘制一次, 颜色随选中状态切换
            text_left = int(icon_x + icon_size + 6)
            text_rect = QRect(
                text_left,
                option.rect.top(),
                option.rect.right() - text_left,
                option.rect.height()
            )
            if option.state & QStyle.StateFlag.State_Selected:
                text_color = opt.palette.color(QPalette.ColorRole.HighlightedText)
            elif unbound:
                text_color = QColor("#c9821f")
            else:
                text_color = opt.palette.color(QPalette.ColorRole.Text)

            draw_text = str(text)
            if unbound:
                draw_text = f"{draw_text}  {tr('(未绑定设备)')}"

            painter.setFont(opt.font)
            painter.setPen(text_color)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                draw_text
            )

            painter.restore()

        except Exception as e:
            logger.debug(f"TreeIconDelegate paint error: {e}")

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 24)


# ============================================================
# 面板类型
# ============================================================

PANEL_TYPES = {
    "trace": "报文监控",
    "signal": "信号监控",
    "graphy": "图表",
    "panel": "面板",
    "uds": "诊断",
    "script": "脚本",
    "transmit": "仿真发送",
    "logger": "Logger",
}

# 面板实例 id 前缀 (稳定 ascii, 与显示名解耦, 便于持久化/计数)
PANEL_ID_PREFIX = {
    "trace": "Trace",
    "signal": "Signal",
    "graphy": "Graphy",
    "panel": "Panel",
    "uds": "UDS",
    "script": "Script",
    "transmit": "Transmit",
    "logger": "Logger",
}

# 容器大标签节点 (半透明绘制, 与实例子节点图标区分)
CATEGORY_LIKE = {"channel_dbc"}

# 面板分类: 监控类挂 Monitor, 仿真类挂 仿真 (与 Monitor 同级)
MONITOR_PANELS = ["trace", "signal", "graphy", "uds", "logger"]
SIM_PANELS = ["transmit", "panel", "script"]


# ============================================================
# 项目树主组件
# ============================================================

class ProjectTree(QWidget):
    """项目导航树 - 支持多项目管理和切换"""

    device_manage_requested = Signal(str)   # device_id: 打开统一设备管理面板
    channel_manage_requested = Signal(str)  # channel_key: 打开面板并定位通道
    panel_created = Signal(str, str, object, str)
    panel_close_requested = Signal(str)
    panel_activate_requested = Signal(str)   # panel_id: 双击实例节点->激活右侧标签
    project_created = Signal(str)
    project_loaded = Signal(str)
    project_switched = Signal(int)  # 项目切换信号，参数为项目索引

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = ProjectManager()
        self._dm = DeviceManager.instance()
        self._hub = DataHub.instance()
        self._panel_counter: dict[str, int] = {}
        self._panel_nodes: dict[str, QTreeWidgetItem] = {}
        # panel_id -> {"type", "channel_key", "project_id"} (供会话持久化)
        self._panel_meta: dict[str, dict] = {}
        # panel_id -> 活动 widget (导出面板状态用; 工程切换时清空)
        self._panel_widgets: dict[str, object] = {}
        # 会话恢复中: 抑制逐工程 project_switched 发射 (末尾统一发一次)
        self._restoring: bool = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._tree = QTreeWidget()
        self._tree.setObjectName("projectTree")
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setDragDropMode(QTreeWidget.DragDropMode.NoDragDrop)
        self._tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setIndentation(20)
        self._tree.setIconSize(QSize(16, 16))
        self._tree.setItemDelegate(_TreeIconDelegate(self._tree))
        self._tree.running_project_index = None
        self._dm.device_state_changed.connect(self._refresh_state_dots)
        self._dm.channel_state_changed.connect(self._refresh_state_dots)
        self._dm.pool_changed.connect(self._refresh_state_dots)
        # DBC 绑定变化 -> 刷新通道下 DBC 固定节点标签
        self._hub.dbc_changed.connect(self._on_dbc_changed)
        # 语言切换 -> 重译空提示/重绘节点
        UISettings.instance().language_changed.connect(
            lambda _l: self.retranslateUi())
        # 设备/通道结构变化 -> 自动保存
        self._dm.pool_changed.connect(lambda: self.autosave())
        # 工程切换后旧面板 dock 已移除, 清掉 widget 引用防串状态
        self.project_switched.connect(
            lambda _i: self._panel_widgets.clear())
        layout.addWidget(self._tree)
        self._show_empty_hint()

    def retranslateUi(self):
        """按当前语言重译固定文本 (空提示/分类节点); 菜单/对话框为按需构建自动生效"""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == "empty_hint":
                item.setText(0, tr("右键创建新项目..."))
            self._retranslate_nodes(item)
        self._tree.viewport().update()

    def _retranslate_nodes(self, node):
        """递归重译分类节点显示名 (面板类型/仿真), 实例 id 为 ascii 不变"""
        role = node.data(0, Qt.ItemDataRole.UserRole)
        kind = node.data(0, Qt.ItemDataRole.UserRole + 1)
        if role == "source":
            node.setText(0, tr("总线"))
        elif role == "monitor":
            node.setText(0, tr("监控"))
        elif role == "sim":
            node.setText(0, tr("仿真"))
        if kind == "category" and role in PANEL_TYPES:
            node.setText(0, tr(PANEL_TYPES[role]))
        if kind == "panel_instance":
            pid = node.data(0, Qt.ItemDataRole.UserRole + 2)
            node.setText(0, self._instance_display(pid, role))
        for c in range(node.childCount()):
            self._retranslate_nodes(node.child(c))

    def _instance_display(self, panel_id: str, panel_type: str) -> str:
        """实例节点显示名: 本地化标签_序号; panel_id 保持 ascii 供持久化/停靠"""
        prefix = PANEL_ID_PREFIX.get(panel_type, "")
        if prefix and panel_id.startswith(prefix + "_"):
            label = tr(PANEL_TYPES.get(panel_type, panel_type))
            return f"{label}_{panel_id[len(prefix) + 1:]}"
        return panel_id

    def _refresh_state_dots(self, *args):
        """设备/通道状态变化 -> 重绘树 (状态点由委托绘制)"""
        self._tree.viewport().update()

    def _show_empty_hint(self):
        self._tree.clear()
        self._panel_nodes.clear()
        item = QTreeWidgetItem(self._tree, [tr("右键创建新项目...")])
        item.setData(0, Qt.ItemDataRole.UserRole, "empty_hint")
        font = item.font(0)
        font.setItalic(True)
        item.setFont(0, font)

    def _clear_empty_hint(self):
        """移除"右键创建新项目"占位提示 (有真实工程时)"""
        for i in range(self._tree.topLevelItemCount() - 1, -1, -1):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == "empty_hint":
                self._tree.takeTopLevelItem(i)

    @property
    def project_manager(self) -> ProjectManager:
        return self._manager

    @property
    def project_name(self) -> str:
        """当前活动项目名称"""
        active = self._manager.active_project
        return active.name if active else ""

    # ---- 项目管理 ----

    def create_project(self, name: str = ""):
        """创建新项目，不影响已有项目"""
        if not name:
            # 自动生成递增名称
            base_name = "MyProject"
            count = self._manager.project_count + 1
            name = f"{base_name}{count}"
            name, ok = QInputDialog.getText(
                self, tr("新建项目"), tr("项目名称:"), text=name)
            if not ok or not name.strip():
                return
        name = name.strip()
        # 检查重名
        for proj in self._manager.projects:
            if proj.name == name:
                QMessageBox.warning(
                    self, tr("重名提示"),
                    tr("项目 '{name}' 已存在，请使用其他名称").format(name=name))
                return
        info = self._manager.create_project(name)
        self._dm.register_project(info.project_id, name)
        self._build_project_tree(info, name)
        self._refresh_tree_display()
        self.project_created.emit(name)
        self.project_switched.emit(self._manager.active_index)
        self.autosave()
        logger.info(f"项目已创建: {name} (共{self._manager.project_count}个)")

    def _build_project_tree(self, info: ProjectInfo, name: str):
        """为指定项目构建树结构"""
        self._clear_empty_hint()
        proj = QTreeWidgetItem(self._tree, [name])
        proj.setData(0, Qt.ItemDataRole.UserRole, "project")
        proj.setData(0, Qt.ItemDataRole.UserRole + 1, self._manager.project_count - 1)
        proj.setExpanded(True)

        src = QTreeWidgetItem(proj, [tr("总线")])
        src.setData(0, Qt.ItemDataRole.UserRole, "source")
        src.setExpanded(True)
        for cname, role in [("CAN", "can_category"),
                            ("LIN", "lin_category"),
                            ("INTERNET", "internet_category")]:
            item = QTreeWidgetItem(src, [cname])
            item.setData(0, Qt.ItemDataRole.UserRole, role)
            item.setExpanded(True)

        self._build_category(proj, "monitor", tr("监控"), MONITOR_PANELS)
        self._build_category(proj, "sim", tr("仿真"), SIM_PANELS)

    def _build_category(self, proj, role: str, title: str, ptypes: list):
        """在项目下构建一个面板分类节点 (Monitor / 仿真) 及其类型子节点"""
        node = QTreeWidgetItem(proj, [title])
        node.setData(0, Qt.ItemDataRole.UserRole, role)
        node.setExpanded(True)
        for ptype in ptypes:
            item = QTreeWidgetItem(node, [tr(PANEL_TYPES[ptype])])
            item.setData(0, Qt.ItemDataRole.UserRole, ptype)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, "category")
            item.setExpanded(True)
        return node

    def _refresh_tree_display(self):
        """刷新树显示：展开当前项目，折叠其他项目"""
        active_idx = self._manager.active_index
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            item_idx = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if item_idx == active_idx:
                item.setExpanded(True)
            else:
                item.setExpanded(False)
        # 刷新树以显示展开按钮
        self._tree.viewport().update()

    def _owner_project_index(self, item) -> Optional[int]:
        """向上查找节点所属工程的索引"""
        node = item
        while node is not None:
            if node.data(0, Qt.ItemDataRole.UserRole) == "project":
                return node.data(0, Qt.ItemDataRole.UserRole + 1)
            node = node.parent()
        return None

    def _ensure_active_project(self, item) -> bool:
        """若节点属于非活动工程，先切换过去（触发 dm 换池/刷新面板）"""
        idx = self._owner_project_index(item)
        if idx is None:
            return False
        if idx != self._manager.active_index:
            self._manager.switch_to(idx)
            self._refresh_tree_display()
            self.project_switched.emit(idx)
        return True

    def _on_item_clicked(self, item, column):
        """点击项目节点时切换活动项目"""
        role = item.data(0, Qt.ItemDataRole.UserRole)
        if role == "project":
            idx = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if idx != self._manager.active_index:
                self._manager.switch_to(idx)
                self._refresh_tree_display()
                self.project_switched.emit(idx)
                logger.info(f"切换到项目: {self._manager.active_project.name}")
        elif role == "channel":
            self._ensure_active_project(item)
            self.channel_manage_requested.emit(
                item.data(0, Qt.ItemDataRole.UserRole + 1) or "")

    def save_project(self) -> bool:
        """保存当前活动工程到配置保存目录 (自动保存模型: 立即落盘, 无对话框)"""
        active = self._manager.active_project
        if not active:
            QMessageBox.warning(self, tr("提示"), tr("请先创建项目"))
            return False
        self.autosave()
        return True

    def _write_project(self, idx: int, path: str,
                       update_path: bool = True) -> bool:
        """按索引序列化工程并写入指定路径 (不切换活动工程)"""
        data = self._serialize_project(idx)
        if not WorkspaceManager.write_project(path, data):
            return False
        if update_path:
            self._manager.set_file_path(idx, str(path))
        logger.info(f"项目已保存: {path}")
        return True

    def save_all_projects(self) -> int:
        """保存全部工程到配置保存目录 (自动保存)"""
        self.autosave()
        return self._manager.project_count

    # ---- 右键菜单 ----

    def export_project(self) -> bool:
        """导出当前活动工程到自选路径 (不影响自动保存目录)"""
        active = self._manager.active_project
        if not active:
            QMessageBox.warning(self, tr("提示"), tr("请先创建项目"))
            return False
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出项目..."), f"{active.name}.bfproj",
            "BusForge Project (*.bfproj);;All Files (*)")
        if not path:
            return False
        return self._write_project(self._manager.active_index, path,
                                   update_path=False)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        role = item.data(0, Qt.ItemDataRole.UserRole) if item else "empty"
        kind = item.data(0, Qt.ItemDataRole.UserRole + 1) if item else None
        menu = QMenu(self)

        if role in ("empty", "empty_hint"):
            act = QAction(tr("新建项目..."), self)
            act.triggered.connect(lambda: self.create_project())
            menu.addAction(act)
        elif role == "project":
            proj_idx = item.data(0, Qt.ItemDataRole.UserRole + 1)
            menu.addAction(tr("重命名项目..."), lambda: self._rename_project(item, proj_idx))
            menu.addSeparator()
            menu.addAction(tr("保存项目"), self.save_project)
            menu.addAction(tr("导出项目..."), self.export_project)
            if self._manager.project_count > 1:
                menu.addSeparator()
                del_act = QAction(tr("删除项目"), self)
                del_act.triggered.connect(lambda: self._delete_project(proj_idx))
                menu.addAction(del_act)
        elif role == "source":
            menu.addAction(tr("导入项目..."), self.import_project)
        elif role in ("can_category", "lin_category"):
            self._ensure_active_project(item)
            bus = "can" if role == "can_category" else "lin"
            menu.addAction(tr("添加通道"), lambda: self._add_channel(item, bus))
        elif role == "channel":
            self._ensure_active_project(item)
            key = item.data(0, Qt.ItemDataRole.UserRole + 1)
            bind_label = tr("绑定设备...") if not self._dm.channel_bound(key) \
                else tr("重新绑定设备...")
            menu.addAction(bind_label,
                           lambda: self.channel_manage_requested.emit(key))
            menu.addSeparator()
            menu.addAction(tr("移除通道"), lambda: self._remove_channel(key))
        elif role == "channel_dbc":
            # 固定大标签: 右键仅创建(导入) DBC, 可导入多个
            self._ensure_active_project(item)
            key = item.data(0, Qt.ItemDataRole.UserRole + 1)
            menu.addAction(tr("导入DBC..."), lambda: self._import_dbc(key))
        elif role == "dbc_instance":
            # 已导入的 DBC 实例: 右键删除 (与 IG/Generator 实例一致)
            self._ensure_active_project(item)
            key = item.data(0, Qt.ItemDataRole.UserRole + 1)
            name = item.data(0, Qt.ItemDataRole.UserRole + 2)
            menu.addAction(tr("删除 DBC"), lambda: self._remove_dbc(key, name))
        elif kind == "category":
            self._build_panel_create_menu(menu, item, role)
        elif kind == "panel_instance":
            panel_id = item.data(0, Qt.ItemDataRole.UserRole + 2)
            act = QAction(tr("关闭面板"), self)
            act.triggered.connect(lambda: self._close_panel(panel_id))
            menu.addAction(act)

        if menu.actions():
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    def import_project(self) -> bool:
        """导入项目（作为新项目添加）"""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("导入项目"), "",
            "BusForge Project (*.bfproj);;All Files (*)")
        if not path:
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            info = self.load_project_from_data(data, file_path=path)
            # 切换到该工程 (widget 编排: 停运行/关面板/换活动池/刷新设备面板)
            self.project_switched.emit(self._manager.active_index)
            self._refresh_tree_display()
            self.project_loaded.emit(info.name)
            logger.info(f"项目已导入: {path}")
            return True
        except Exception as e:
            QMessageBox.critical(self, tr("导入失败"), str(e))
            return False

    def load_project_from_data(self, data: dict,
                               file_path: str = "") -> ProjectInfo:
        """从工程数据字典创建工程 (结构/设备/通道/面板节点)。

        不发射 project_switched, 供文件导入与会话恢复共用。
        新工程创建后即为活动工程 (供 _rebuild_* 定位)。
        """
        name = data.get('project_name', 'Imported')
        pid = data.get('project_id', '')
        info = self._manager.create_project(name, project_id=pid)
        info.file_path = file_path or data.get('file_path', '')
        self._build_project_tree(info, name)
        # 导入设备/通道完整定义到该工程池
        self._dm.import_project(info.project_id, data)
        # 依据导入的定义重建通道节点
        self._rebuild_channel_nodes(data)
        # 重建面板树节点 (不创建 dock; 活动工程面板由 restore_session 统一创建)
        self._rebuild_panel_nodes(info, data.get('panels', []))
        return info

    def restore_session(self, projects: list, active_index: int):
        """从工作空间会话恢复全部工程 (结构/设备/通道/面板)。

        逐工程加载时不发射 project_switched; 全部就绪后切到活动工程并发射一次,
        再为活动工程创建面板 dock。
        """
        if not projects:
            return
        self._restoring = True
        try:
            for data in projects:
                try:
                    self.load_project_from_data(data)
                except Exception as e:
                    logger.error(f"会话工程恢复失败: {e}")
        finally:
            self._restoring = False
        count = self._manager.project_count
        if count == 0:
            self._show_empty_hint()
            return
        target = active_index if 0 <= active_index < count else count - 1
        self._manager.switch_to(target)
        self._refresh_tree_display()
        self.project_switched.emit(target)
        # 活动工程的面板 dock 由 project_switched 处理器统一重建 (见 BusForgeWidget)
        logger.info(f"会话已恢复: {count} 个工程, 活动={target}")

    def restore_active_panels(self):
        """为当前活动工程重建面板 dock (切回工程/删除其他工程后恢复编辑区)"""
        self._restore_active_panel_docks()

    def _restore_active_panel_docks(self):
        """为活动工程已恢复的面板树节点创建 dock widget"""
        active = self._manager.active_project
        if not active:
            return
        for pid, meta in list(self._panel_meta.items()):
            if meta.get('project_id') != active.project_id:
                continue
            widget = self._create_panel_widget(
                meta['type'], meta.get('channel_key', ''))
            if widget is None:
                continue
            self._register_panel_widget(pid, widget)
            self.panel_created.emit(
                pid, meta['type'], widget, meta.get('channel_key', ''))

    def _register_panel_widget(self, panel_id: str, widget):
        """登记面板 widget: 恢复其持久化状态并挂接变更自动保存"""
        self._panel_widgets[panel_id] = widget
        state = (self._panel_meta.get(panel_id) or {}).get('state')
        if state and hasattr(widget, 'import_state'):
            try:
                widget.import_state(state)
            except Exception as e:
                logger.error(f"面板状态恢复失败({panel_id}): {e}")
        if hasattr(widget, 'state_dirty'):
            try:
                widget.state_dirty.connect(self.autosave)
            except Exception:
                pass

    def _rebuild_panel_nodes(self, info: ProjectInfo, panels: list):
        """从会话数据重建面板树节点 (挂到该工程 Monitor 分类下), 并登记 _panel_meta。

        不创建 dock widget — 活动工程的面板 dock 由 restore_session 统一创建。
        """
        for p in panels:
            ptype = p.get('type', '')
            panel_id = p.get('panel_id', '')
            channel_key = p.get('channel_key', '')
            if not ptype or not panel_id:
                continue
            parent = self._find_panel_parent(ptype, channel_key)
            if parent is None:
                continue
            tree_item = QTreeWidgetItem(parent, [panel_id])
            tree_item.setData(0, Qt.ItemDataRole.UserRole, ptype)
            tree_item.setData(0, Qt.ItemDataRole.UserRole + 1, "panel_instance")
            tree_item.setData(0, Qt.ItemDataRole.UserRole + 2, panel_id)
            tree_item.setText(0, self._instance_display(panel_id, ptype))
            self._panel_nodes[panel_id] = tree_item
            self._panel_meta[panel_id] = {
                'type': ptype, 'channel_key': channel_key,
                'project_id': info.project_id,
                'state': p.get('state'),   # 面板持久化状态 (如仿真发送帧列表)
            }
            self._bump_panel_counter(ptype, panel_id)

    def _bump_panel_counter(self, panel_type: str, panel_id: str):
        """根据已恢复的 panel_id (如 Trace_2) 抬高计数器, 避免新建面板重名"""
        label = PANEL_ID_PREFIX.get(
            panel_type, PANEL_TYPES.get(panel_type, panel_type))
        prefix = f"{label}_"
        if panel_id.startswith(prefix):
            tail = panel_id[len(prefix):]
            if tail.isdigit():
                n = int(tail)
                if n > self._panel_counter.get(panel_type, 0):
                    self._panel_counter[panel_type] = n

    def _rename_project(self, item, proj_idx):
        name, ok = QInputDialog.getText(
            self, tr("重命名"), tr("新项目名称:"), text=self._manager.projects[proj_idx].name)
        if ok and name.strip():
            new_name = name.strip()
            pid = self._manager.projects[proj_idx].project_id
            self._manager.rename_project(proj_idx, new_name)
            self._dm.set_project_name(pid, new_name)
            item.setText(0, new_name)
            self.autosave()  # 改名后重写新文件并删除旧文件

    def _delete_project(self, proj_idx):
        """删除指定项目"""
        info = self._manager.projects[proj_idx]
        old_path = info.file_path
        reply = QMessageBox.question(
            self, tr("确认删除"),
            tr("确定要删除项目 '{name}' 吗？").format(name=info.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        # 删除活动工程且正在运行: 先停轮询再断开设备,
        # 避免收数/发送路径访问已关闭的硬件实例 (闪退风险)
        if proj_idx == self._manager.active_index and self._hub.running:
            self._hub.stop_polling()
            self.set_running_badge(None)
        # 删除该工程的设备池 (若为活动工程则先断开其连接)。延后广播，避免树结构
        # 尚未完成更新时触发设备面板和自动保存重入。
        self._dm.unregister_project(info.project_id, emit=False)
        # 清理该工程的面板元数据/节点引用 (随树节点一并移除)
        for pid in [p for p, m in self._panel_meta.items()
                    if m.get('project_id') == info.project_id]:
            self._panel_meta.pop(pid, None)
            self._panel_nodes.pop(pid, None)
            self._panel_widgets.pop(pid, None)
        # 找到对应的树节点并移除
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole + 1) == proj_idx:
                self._tree.takeTopLevelItem(i)
                break
        self._manager.remove_project(proj_idx)
        # 删除工程对应的存档文件
        WorkspaceManager.remove_project_file(old_path)
        self._reindex_project_nodes()
        if self._manager.project_count > 0:
            self._manager.switch_to(min(proj_idx, self._manager.project_count - 1))
            self._refresh_tree_display()
            self._dm.pool_changed.emit()
            self.project_switched.emit(self._manager.active_index)
        else:
            self._show_empty_hint()
            # 已无工程: 通知 widget 停运行/关面板/清空活动工程池 (与清空工作空间一致)
            self._dm.pool_changed.emit()
            self.project_switched.emit(-1)
        self.autosave()
        logger.info(f"项目已删除: {info.name}")

    def delete_project(self, idx: int):
        """公共入口: 删除指定工程 (含确认对话框)"""
        if 0 <= idx < self._manager.project_count:
            self._delete_project(idx)

    def close_all_projects(self):
        """关闭全部工程 (清空树/设备池/面板), 用于清空工作空间"""
        # 先通知 widget 停运行/关面板 dock/将活动工程置 None
        self.project_switched.emit(-1)
        for info in list(self._manager.projects):
            self._dm.unregister_project(info.project_id)
        self._manager._projects.clear()
        self._manager._active_index = -1
        self._panel_meta.clear()
        self._panel_nodes.clear()
        self._panel_widgets.clear()
        self._panel_counter.clear()
        self._show_empty_hint()
        logger.info("已关闭全部工程 (工作空间已清空)")

    def _reindex_project_nodes(self):
        """删除后重排顶层工程节点的索引，与 projects 列表顺序对齐"""
        idx = 0
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == "project":
                item.setData(0, Qt.ItemDataRole.UserRole + 1, idx)
                idx += 1

    def _find_project_item(self, proj_idx: int):
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == "project" \
                    and item.data(0, Qt.ItemDataRole.UserRole + 1) == proj_idx:
                return item
        return None

    def _collect_refs(self, proj_idx: int, role: str) -> list:
        item = self._find_project_item(proj_idx)
        out = []
        if not item:
            return out
        stack = [item]
        while stack:
            n = stack.pop()
            if n.data(0, Qt.ItemDataRole.UserRole) == role:
                out.append(n.data(0, Qt.ItemDataRole.UserRole + 1))
            for c in range(n.childCount()):
                stack.append(n.child(c))
        return out

    def collect_project_channels(self, proj_idx: int = None) -> list[str]:
        """项目引用的软件通道 key 列表 (运行工程用)"""
        idx = self._manager.active_index if proj_idx is None else proj_idx
        return self._collect_refs(idx, "channel")

    def set_running_badge(self, proj_idx):
        """项目根节点运行徽标 (None 清除)"""
        self._tree.running_project_index = proj_idx
        self._tree.viewport().update()

    def _serialize_project(self, proj_idx: int = None) -> dict:
        """序列化指定工程 (存完整设备/通道/面板定义, 含面板状态)"""
        idx = self._manager.active_index if proj_idx is None else proj_idx
        info = self._manager.projects[idx]
        export = self._dm.export_project(info.project_id)
        panels = []
        for pid, m in self._panel_meta.items():
            if m.get('project_id') != info.project_id:
                continue
            entry = {'type': m['type'], 'panel_id': pid,
                     'channel_key': m.get('channel_key', '')}
            # 活动面板从 widget 实时导出状态; 非活动工程用上次已存状态
            w = self._panel_widgets.get(pid)
            if w is not None and hasattr(w, 'export_state'):
                try:
                    m['state'] = w.export_state()
                except Exception as e:
                    logger.error(f"面板状态导出失败({pid}): {e}")
            if m.get('state') is not None:
                entry['state'] = m['state']
            panels.append(entry)
        return {
            'project_name': info.name,
            'project_id': info.project_id,
            'file_path': info.file_path,
            'version': '0.3.0',
            'devices': export['devices'],
            'channels': export['channels'],
            'panels': panels,
        }

    def serialize_all_projects(self) -> list:
        """序列化全部工程 (供工作空间会话持久化, 不切换活动工程)"""
        return [self._serialize_project(i)
                for i in range(self._manager.project_count)]

    def autosave(self):
        """自动保存: 全部工程 .bfproj + 会话索引 落盘到配置保存目录。

        创建/更改/删除时调用; 未绑定配置(离屏测试)或会话恢复中时跳过。
        工程改名导致路径变化时同步删除旧文件。
        """
        if not WorkspaceManager.is_bound() or self._restoring:
            return
        try:
            sd = WorkspaceManager.save_dir()
            sd.mkdir(parents=True, exist_ok=True)
            for i, info in enumerate(self._manager.projects):
                path = WorkspaceManager.project_file(info.name)
                if info.file_path and Path(info.file_path) != path:
                    WorkspaceManager.remove_project_file(info.file_path)
                WorkspaceManager.write_project(
                    path, self._serialize_project(i))
                info.file_path = str(path)
            WorkspaceManager.save(
                self.serialize_all_projects(), self._manager.active_index)
        except Exception as e:
            logger.error(f"自动保存失败: {e}")

    def _add_channel(self, category_item, bus_type: str):
        """在 CAN/LIN 分类下添加一个未绑定的软件通道, 并引导用户去设备管理绑定"""
        if self._dm.active_project is None:
            QMessageBox.warning(self, tr("提示"), tr("请先创建或选择一个工程"))
            return
        key = self._dm.suggest_channel_key(bus_type)
        ok, err = self._dm.assign_channel(key, device_id="", bus_type=bus_type)
        if not ok:
            QMessageBox.warning(self, tr("添加通道失败"), err)
            return
        self._add_channel_node(category_item, key)
        logger.info(f"软件通道已添加: {key} (未绑定设备)")
        self._prompt_bind_device(key)

    def _add_channel_node(self, parent_item, key: str):
        """在分类节点下添加软件通道引用节点, 并挂固定子节点 DBC"""
        ch_item = QTreeWidgetItem(parent_item, [key])
        ch_item.setData(0, Qt.ItemDataRole.UserRole, "channel")
        ch_item.setData(0, Qt.ItemDataRole.UserRole + 1, key)
        ch_item.setToolTip(
            0, tr("未绑定设备时不可用: 右键→绑定设备, 或到设备管理设置"))
        # 固定子节点: DBC 为大标签容器, 导入的每个 DBC 作为可删除的子实例
        dbc_item = QTreeWidgetItem(ch_item, ["DBC"])
        dbc_item.setData(0, Qt.ItemDataRole.UserRole, "channel_dbc")
        dbc_item.setData(0, Qt.ItemDataRole.UserRole + 1, key)
        dbc_item.setToolTip(0, tr("右键/双击导入 DBC 文件 (可多个)"))
        parent_item.setExpanded(True)
        ch_item.setExpanded(True)

    def _on_dbc_changed(self, channel_key: str, dbc):
        """DBC 列表变化 -> 重建对应通道 DBC 大标签下的实例子节点"""
        self._refresh_dbc_nodes(channel_key)

    def _refresh_dbc_nodes(self, channel_key: str):
        """按中台当前 DBC 列表重建通道 DBC 大标签下的实例子节点"""
        container = self._find_channel_sub_node(channel_key, "channel_dbc")
        if container is None:
            return
        for i in range(container.childCount() - 1, -1, -1):
            container.removeChild(container.child(i))
        for dbc in self._hub.list_channel_dbc(channel_key):
            item = QTreeWidgetItem(container, [dbc.name])
            item.setData(0, Qt.ItemDataRole.UserRole, "dbc_instance")
            item.setData(0, Qt.ItemDataRole.UserRole + 1, channel_key)
            item.setData(0, Qt.ItemDataRole.UserRole + 2, dbc.name)
            item.setToolTip(
                0, tr("{path} (右键删除)").format(path=dbc.source_path or dbc.name))
        container.setExpanded(True)
        self._tree.viewport().update()

    def _remove_dbc(self, channel_key: str, dbc_name: str):
        """删除通道已导入的指定 DBC (中台移除+回写配置, 节点由 dbc_changed 刷新)"""
        reply = QMessageBox.question(
            self, tr("确认删除"),
            tr("从通道 {key} 移除 DBC '{name}'?").format(
                key=channel_key, name=dbc_name))
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._hub.unload_channel_dbc(channel_key, dbc_name)

    def _find_channel_sub_node(self, channel_key: str, role: str):
        """在活动工程树中定位通道下的固定子节点 (channel_dbc)"""
        active_idx = self._manager.active_index
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            if root.data(0, Qt.ItemDataRole.UserRole) != "project":
                continue
            if root.data(0, Qt.ItemDataRole.UserRole + 1) != active_idx:
                continue
            stack = [root]
            while stack:
                n = stack.pop()
                if n.data(0, Qt.ItemDataRole.UserRole) == role \
                        and n.data(0, Qt.ItemDataRole.UserRole + 1) == channel_key:
                    return n
                for c in range(n.childCount()):
                    stack.append(n.child(c))
        return None

    def _find_panel_parent(self, panel_type: str, channel_key: str):
        """面板实例统一挂到其所属分类 (Monitor / 仿真) 下"""
        return self._find_panel_category(panel_type)

    def _prompt_bind_device(self, key: str):
        """添加通道后明确引导: 需到设备管理添加并绑定设备, 否则通道不可用"""
        box = QMessageBox(self)
        box.setWindowTitle(tr("通道已创建"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            tr("软件通道 {key} 已创建, 但尚未绑定设备, 暂时无法收发。").format(key=key))
        box.setInformativeText(
            tr("请到【设备管理】添加硬件设备, 并为该通道绑定设备的硬件通道后再运行。"))
        bind_btn = box.addButton(tr("打开设备管理"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("稍后"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is bind_btn:
            self.channel_manage_requested.emit(key)

    def _remove_channel(self, key: str):
        """移除软件通道 (工程池 + 树节点)"""
        if self._dm.channel_state(key) == "connected":
            QMessageBox.warning(self, tr("提示"), tr("通道连接中, 请先断开再移除"))
            return
        reply = QMessageBox.question(
            self, tr("确认移除"), tr("移除软件通道 '{key}'?").format(key=key))
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._dm.remove_channel(key)
        item = self._find_project_item(self._manager.active_index)
        if item:
            self._strip_channel_node(item, key)
        logger.info(f"软件通道已移除: {key}")

    def _strip_channel_node(self, node, key: str):
        for c in range(node.childCount() - 1, -1, -1):
            child = node.child(c)
            if child.data(0, Qt.ItemDataRole.UserRole) == "channel" \
                    and child.data(0, Qt.ItemDataRole.UserRole + 1) == key:
                node.removeChild(child)
            else:
                self._strip_channel_node(child, key)

    def _import_dbc(self, channel_key: str):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("导入DBC文件"), "", "DBC Files (*.dbc);;All Files (*)")
        if not path:
            return
        if not self._hub.load_channel_dbc_file(channel_key, path):
            QMessageBox.critical(
                self, tr("DBC导入失败"), tr("解析失败: {path}").format(path=path))

    def _build_panel_create_menu(self, menu, item, panel_type):
        label = tr(PANEL_TYPES.get(panel_type, panel_type))
        act = QAction(tr("创建 {label}").format(label=label), self)
        act.triggered.connect(lambda: self.create_panel(panel_type))
        menu.addAction(act)

    # ---- 双击 ----

    def _on_double_click(self, item, column):
        role = item.data(0, Qt.ItemDataRole.UserRole)
        kind = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if role == "empty_hint":
            self.create_project()
        elif role == "channel_dbc":
            # 双击 DBC 固定节点 -> 导入/重新导入
            self._ensure_active_project(item)
            self._import_dbc(item.data(0, Qt.ItemDataRole.UserRole + 1))
        elif kind == "panel_instance":
            panel_id = item.data(0, Qt.ItemDataRole.UserRole + 2)
            # 双击真实监控实例节点 -> 切换/激活右侧对应标签页
            self.panel_activate_requested.emit(panel_id)

    # ---- 通道节点重建 ----

    def _rebuild_channel_nodes(self, data: dict):
        """从工程文件的通道定义重建通道节点 (挂到 CAN/LIN 分类下)"""
        proj_item = self._find_project_item(self._manager.active_index)
        if not proj_item:
            return
        cat_map = {}
        for i in range(proj_item.childCount()):
            src = proj_item.child(i)
            if src.data(0, Qt.ItemDataRole.UserRole) == "source":
                for j in range(src.childCount()):
                    cat = src.child(j)
                    cat_map[cat.data(0, Qt.ItemDataRole.UserRole)] = cat
        for c in data.get('channels', []):
            key = c.get('key', '')
            role = "lin_category" if c.get('bus_type', 'can') == "lin" \
                else "can_category"
            parent = cat_map.get(role) or cat_map.get("can_category")
            if parent:
                self._add_channel_node(parent, key)
                # 会话/导入恢复: 通道已存 dbc_paths(兼容旧 dbc_path) 且文件存在则重新加载
                paths = c.get('dbc_paths') or []
                if not paths and c.get('dbc_path'):
                    paths = [c['dbc_path']]
                for p in paths:
                    if p and Path(p).exists():
                        self._hub.load_channel_dbc_file(key, p)

    # ---- 面板操作 ----

    def create_panel(self, panel_type, panel_id="", channel_key=""):
        active = self._manager.active_project
        if not active:
            return
        if not panel_id:
            count = self._panel_counter.get(panel_type, 0) + 1
            self._panel_counter[panel_type] = count
            label = PANEL_ID_PREFIX.get(
                panel_type, PANEL_TYPES.get(panel_type, panel_type))
            panel_id = f"{label}_{count}"
        widget = self._create_panel_widget(panel_type, channel_key)
        if widget is None:
            return
        parent = self._find_panel_parent(panel_type, channel_key)
        if parent:
            tree_item = QTreeWidgetItem(parent, [panel_id])
            tree_item.setData(0, Qt.ItemDataRole.UserRole, panel_type)
            tree_item.setData(0, Qt.ItemDataRole.UserRole + 1, "panel_instance")
            tree_item.setData(0, Qt.ItemDataRole.UserRole + 2, panel_id)
            tree_item.setText(0, self._instance_display(panel_id, panel_type))
            self._panel_nodes[panel_id] = tree_item
        # 登记面板元数据 (供会话持久化)
        self._panel_meta[panel_id] = {
            'type': panel_type, 'channel_key': channel_key,
            'project_id': active.project_id,
        }
        self._register_panel_widget(panel_id, widget)
        self.panel_created.emit(panel_id, panel_type, widget, channel_key)
        self.autosave()

    def _close_panel(self, panel_id):
        item = self._panel_nodes.pop(panel_id, None)
        self._panel_meta.pop(panel_id, None)
        self._panel_widgets.pop(panel_id, None)
        if item:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
        self.panel_close_requested.emit(panel_id)
        self.autosave()

    def _find_panel_category(self, panel_type):
        """在活动项目中查找面板类型分类节点 (Monitor / 仿真 下)"""
        active_idx = self._manager.active_index
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            if root.data(0, Qt.ItemDataRole.UserRole) == "project":
                proj_idx = root.data(0, Qt.ItemDataRole.UserRole + 1)
                if proj_idx == active_idx:
                    for j in range(root.childCount()):
                        child = root.child(j)
                        if child.data(0, Qt.ItemDataRole.UserRole) \
                                in ("monitor", "sim"):
                            for k in range(child.childCount()):
                                grand = child.child(k)
                                if grand.data(0, Qt.ItemDataRole.UserRole) == panel_type:
                                    return grand
        return None

    def _create_panel_widget(self, panel_type, channel_key):
        try:
            if panel_type == "trace":
                from app.monitors.trace_view import TraceView
                return TraceView(channel_key=channel_key)
            elif panel_type == "signal":
                from app.monitors.signal_monitor import SignalMonitorPanel
                return SignalMonitorPanel(channel_key=channel_key)
            elif panel_type == "graphy":
                from app.monitors.graphy_view import GraphyView
                return GraphyView(channel_key=channel_key)
            elif panel_type == "panel":
                from app.ui.panel_editor.custom_panel import CustomPanel
                return CustomPanel()
            elif panel_type == "uds":
                from app.diagnostic.diagnostic import DiagnosticPanel
                return DiagnosticPanel(channel_key=channel_key)
            elif panel_type == "script":
                from app.script.script_editor import ScriptEditorPanel
                return ScriptEditorPanel()
            elif panel_type == "transmit":
                from app.transmit.transmit_panel import TransmitPanel
                return TransmitPanel(channel_key=channel_key)
            elif panel_type == "logger":
                from app.recorder.logger_panel import LoggerPanel
                return LoggerPanel(channel_key=channel_key)
            else:
                logger.warning(f"未知面板类型: {panel_type}")
                return None
        except Exception as e:
            logger.error(f"创建面板失败({panel_type}): {e}")
            from PySide6.QtWidgets import QLabel
            lbl = QLabel(f"面板加载失败: {panel_type}\n{e}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return lbl

    # ---- 公共查询 ----

    def get_channel_keys(self):
        """全局所有软件通道 key (外部查询)"""
        return [c.key for c in self._dm.list_channels()]
