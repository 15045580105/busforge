"""
ToolbarWidget - 顶部工具栏

布局:
  ─────────────────────────────────────────────────  <- 工具栏(浅灰背景, 与下方明显区分)
  [图标] [图标] [图标] | [图标] [图标] [图标] | ...   <- 按钮栏
  文字   文字   文字     文字   文字   文字
  ─────────────────────────────────────────────────  <- 底部分隔线

图标使用 QPainter 绘制，保持正方形等比例，不拉伸。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QSize
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QFontMetrics
)

from app.common.ui_settings import UISettings
from app.common.i18n import tr


# ============================================================
# 图标绘制函数 - 用 QPainter 绘制专业彩色图标
# 所有图标在正方形区域内绘制，保持等比例不拉伸
# ============================================================

def _draw_folder_icon(painter: QPainter, rect: QRectF, color="#f0b429"):
    """绘制文件夹图标"""
    painter.save()
    c = QColor(color)
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    # 文件夹主体
    r = rect.adjusted(2, 4, -2, -2)
    painter.drawRoundedRect(r, 3, 3)
    # 文件夹顶部标签
    tab = QRectF(r.left(), r.top() - 4, r.width() * 0.45, 5)
    painter.drawRoundedRect(tab, 2, 2)
    painter.restore()


def _draw_save_icon(painter: QPainter, rect: QRectF, color="#888888"):
    """绘制保存(软盘)图标"""
    painter.save()
    c = QColor(color)
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(130), 1))
    r = rect.adjusted(3, 2, -3, -2)
    painter.drawRoundedRect(r, 2, 2)
    # 软盘标签区域
    label_rect = QRectF(r.left() + 4, r.top() + 2, r.width() - 8, r.height() * 0.35)
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawRect(label_rect)
    # 底部金属条
    metal = QRectF(r.left() + 3, r.bottom() - 7, r.width() - 6, 5)
    painter.setBrush(QBrush(c.lighter(140)))
    painter.drawRect(metal)
    painter.restore()


def _draw_save_all_icon(painter: QPainter, rect: QRectF, color="#888888"):
    """绘制保存所有(双软盘)图标"""
    painter.save()
    c = QColor(color)
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(130), 1))
    r1 = rect.adjusted(5, 2, -1, -2)
    painter.drawRoundedRect(r1, 2, 2)
    r2 = rect.adjusted(1, 5, -5, -2)
    painter.setBrush(QBrush(c.lighter(110)))
    painter.drawRoundedRect(r2, 2, 2)
    painter.setPen(QPen(QColor("#ffffff"), 1))
    font = QFont("Segoe UI", 5, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(r2, Qt.AlignmentFlag.AlignCenter, "ALL")
    painter.restore()


def _draw_play_icon(painter: QPainter, rect: QRectF, color="#4caf50"):
    """绘制运行(播放)图标"""
    painter.save()
    c = QColor(color)
    cx, cy = rect.center().x(), rect.center().y()
    radius = min(rect.width(), rect.height()) / 2 - 2
    painter.setBrush(QBrush(c))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    painter.setBrush(QBrush(QColor("#ffffff")))
    path = QPainterPath()
    tri_left = cx - radius * 0.35
    tri_top = cy - radius * 0.45
    tri_bot = cy + radius * 0.45
    tri_right = cx + radius * 0.45
    path.moveTo(tri_left, tri_top)
    path.lineTo(tri_right, cy)
    path.lineTo(tri_left, tri_bot)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def _draw_stop_icon(painter: QPainter, rect: QRectF, color="#e53935"):
    """绘制终止(停止)图标"""
    painter.save()
    c = QColor(color)
    cx, cy = rect.center().x(), rect.center().y()
    radius = min(rect.width(), rect.height()) / 2 - 2
    painter.setBrush(QBrush(c))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    sq = radius * 0.45
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawRect(QRectF(cx - sq, cy - sq, sq * 2, sq * 2))
    painter.restore()


def _draw_pause_icon(painter: QPainter, rect: QRectF, color="#f59e0b"):
    """绘制暂停(双竖条)图标"""
    painter.save()
    c = QColor(color)
    painter.setBrush(QBrush(c))
    painter.setPen(Qt.PenStyle.NoPen)
    cx, cy = rect.center().x(), rect.center().y()
    bar_h = rect.height() * 0.62
    bar_w = rect.width() * 0.18
    gap = rect.width() * 0.14
    painter.drawRoundedRect(
        QRectF(cx - gap - bar_w, cy - bar_h / 2, bar_w, bar_h), 1.5, 1.5)
    painter.drawRoundedRect(
        QRectF(cx + gap, cy - bar_h / 2, bar_w, bar_h), 1.5, 1.5)
    painter.restore()


def _draw_clear_icon(painter: QPainter, rect: QRectF, color="#90a4ae"):
    """绘制清除(垃圾桶)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    w = rect.width() * 0.5
    h = rect.height() * 0.55
    top = cy - h / 2
    # 桶盖横杆 + 提手
    painter.drawLine(QPointF(cx - w * 0.7, top), QPointF(cx + w * 0.7, top))
    painter.drawRoundedRect(QRectF(cx - w * 0.2, top - 3, w * 0.4, 3), 1, 1)
    # 桶身
    painter.drawRoundedRect(QRectF(cx - w / 2, top, w, h), 1.5, 1.5)
    # 桶身内双竖线
    painter.drawLine(QPointF(cx - w * 0.16, top + 2.5),
                     QPointF(cx - w * 0.16, top + h - 2.5))
    painter.drawLine(QPointF(cx + w * 0.16, top + 2.5),
                     QPointF(cx + w * 0.16, top + h - 2.5))
    painter.restore()


def _draw_refresh_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制刷新(环形箭头)图标"""
    painter.save()
    c = QColor(color)
    pen = QPen(c, 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) / 2 - 3
    painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 60 * 16, 280 * 16)
    # 箭头: 位于 60° 弧起点, 指向切线方向
    ax = cx + r * 0.5
    ay = cy - r * 0.866
    path = QPainterPath()
    path.moveTo(ax - 4, ay - 2)
    path.lineTo(ax + 3, ay - 3)
    path.lineTo(ax + 1, ay + 4)
    path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(c))
    painter.drawPath(path)
    painter.restore()


def _draw_export_icon(painter: QPainter, rect: QRectF, color="#2f855a"):
    """绘制导出(托盘+向上箭头)图标"""
    painter.save()
    c = QColor(color)
    pen = QPen(c, 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    w = rect.width() * 0.62
    h = rect.height() * 0.42
    # 托盘 (开口向上的 U)
    painter.drawPolyline([
        QPointF(cx - w / 2, cy - 1),
        QPointF(cx - w / 2, cy + h / 2),
        QPointF(cx + w / 2, cy + h / 2),
        QPointF(cx + w / 2, cy - 1),
    ])
    # 向上箭杆 + 箭头
    painter.drawLine(QPointF(cx, cy - h), QPointF(cx, cy + 1))
    painter.drawPolyline([
        QPointF(cx - 4, cy - h + 4),
        QPointF(cx, cy - h),
        QPointF(cx + 4, cy - h + 4),
    ])
    painter.restore()


def _draw_auto_icon(painter: QPainter, rect: QRectF, color="#f59e0b"):
    """绘制跟随运行(环形箭头+中心记录点)图标"""
    painter.save()
    c = QColor(color)
    pen = QPen(c, 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) / 2 - 3
    painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 30 * 16, 300 * 16)
    # 箭头: 位于 30° 弧起点
    ax = cx + r * 0.866
    ay = cy - r * 0.5
    path = QPainterPath()
    path.moveTo(ax - 3, ay - 4)
    path.lineTo(ax + 4, ay - 1)
    path.lineTo(ax - 1, ay + 4)
    path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(c))
    painter.drawPath(path)
    # 中心记录点 (红)
    painter.setBrush(QBrush(QColor("#e53935")))
    dr = max(2.5, r * 0.28)
    painter.drawEllipse(QRectF(cx - dr, cy - dr, dr * 2, dr * 2))
    painter.restore()


def _draw_scroll_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制滚动模式(列表+下箭头)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    x0 = rect.left() + rect.width() * 0.22
    x1 = rect.left() + rect.width() * 0.62
    for t in (0.28, 0.5, 0.72):
        y = rect.top() + rect.height() * t
        painter.drawLine(QPointF(x0, y), QPointF(x1, y))
    # 右侧下箭头: 新帧持续向下滚入
    ax = rect.left() + rect.width() * 0.78
    ay0 = rect.top() + rect.height() * 0.24
    ay1 = rect.top() + rect.height() * 0.74
    painter.drawLine(QPointF(ax, ay0), QPointF(ax, ay1))
    painter.drawLine(QPointF(ax - 3, ay1 - 3.5), QPointF(ax, ay1))
    painter.drawLine(QPointF(ax + 3, ay1 - 3.5), QPointF(ax, ay1))
    painter.restore()


def _draw_overwrite_icon(painter: QPainter, rect: QRectF, color="#7e57c2"):
    """绘制覆盖模式(下箭头落入基线=原位覆盖)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ax = rect.center().x()
    ay0 = rect.top() + rect.height() * 0.16
    ay1 = rect.top() + rect.height() * 0.58
    painter.drawLine(QPointF(ax, ay0), QPointF(ax, ay1))
    painter.drawLine(QPointF(ax - 3.5, ay1 - 4), QPointF(ax, ay1))
    painter.drawLine(QPointF(ax + 3.5, ay1 - 4), QPointF(ax, ay1))
    # 基线: 同键行原位被覆盖
    y = rect.top() + rect.height() * 0.8
    painter.drawLine(QPointF(rect.left() + rect.width() * 0.24, y),
                     QPointF(rect.right() - rect.width() * 0.24, y))
    painter.restore()


def _draw_abs_time_icon(painter: QPainter, rect: QRectF, color="#00897b"):
    """绘制绝对时间(时钟)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) * 0.32
    painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    # 分针/时针
    painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.62))
    painter.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.45, cy + r * 0.28))
    painter.restore()


def _draw_delta_time_icon(painter: QPainter, rect: QRectF, color="#00897b"):
    """绘制相对时间(Δt 时间差)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.4))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(8, int(rect.height() * 0.46)))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Δt")
    painter.restore()


def _draw_find_prev_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制查找上一个(放大镜+上箭头)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = rect.center().x() - rect.width() * 0.06
    cy = rect.center().y() - rect.height() * 0.06
    r = min(rect.width(), rect.height()) * 0.28
    painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    # 镜柄
    painter.drawLine(QPointF(cx + r * 0.75, cy + r * 0.75),
                     QPointF(cx + r * 1.5, cy + r * 1.5))
    # 镜内上箭头
    painter.drawLine(QPointF(cx, cy + r * 0.5), QPointF(cx, cy - r * 0.45))
    painter.drawLine(QPointF(cx - r * 0.35, cy - r * 0.1),
                     QPointF(cx, cy - r * 0.45))
    painter.drawLine(QPointF(cx + r * 0.35, cy - r * 0.1),
                     QPointF(cx, cy - r * 0.45))
    painter.restore()


def _draw_find_next_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制查找下一个(放大镜+下箭头)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = rect.center().x() - rect.width() * 0.06
    cy = rect.center().y() - rect.height() * 0.06
    r = min(rect.width(), rect.height()) * 0.28
    painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    # 镜柄
    painter.drawLine(QPointF(cx + r * 0.75, cy + r * 0.75),
                     QPointF(cx + r * 1.5, cy + r * 1.5))
    # 镜内下箭头
    painter.drawLine(QPointF(cx, cy - r * 0.5), QPointF(cx, cy + r * 0.45))
    painter.drawLine(QPointF(cx - r * 0.35, cy + r * 0.1),
                     QPointF(cx, cy + r * 0.45))
    painter.drawLine(QPointF(cx + r * 0.35, cy + r * 0.1),
                     QPointF(cx, cy + r * 0.45))
    painter.restore()


def _draw_logger_icon(painter: QPainter, rect: QRectF, color="#5a6c7d"):
    """绘制 Logger (记录盘: 外圈+红芯) 图标"""
    painter.save()
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) * 0.32
    painter.setPen(QPen(QColor(color), 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e53935"))
    painter.drawEllipse(QPointF(cx, cy), r * 0.42, r * 0.42)
    painter.restore()


def _draw_offline_icon(painter: QPainter, rect: QRectF, color="#78909c"):
    """绘制脱机运行(电脑)图标"""
    painter.save()
    c = QColor(color)
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    r = rect.adjusted(2, 1, -2, -6)
    painter.drawRoundedRect(r, 2, 2)
    inner = r.adjusted(2, 2, -2, -2)
    painter.setBrush(QBrush(QColor("#e0e0e0")))
    painter.drawRoundedRect(inner, 1, 1)
    painter.setBrush(QBrush(c))
    base = QRectF(rect.center().x() - 5, r.bottom(), 10, 4)
    painter.drawRect(base)
    painter.restore()


def _draw_hexdec_icon(painter: QPainter, rect: QRectF, color="#00897b"):
    """绘制进制切换(0x)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(2, 3, -2, -3)
    painter.drawRoundedRect(r, 3, 3)
    painter.setPen(QPen(c))
    font = QFont("Consolas", 8, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "0x")
    painter.restore()


def _draw_language_icon(painter: QPainter, rect: QRectF, color="#5a6c7d"):
    """绘制语言切换(中/A)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(2, 3, -2, -3)
    painter.drawRoundedRect(r, 3, 3)
    painter.setPen(QPen(c))
    font = QFont("Microsoft YaHei", 7, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "中A")
    painter.restore()


def _draw_settings_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制配置(齿轮)图标"""
    painter.save()
    c = QColor(color)
    cx, cy = rect.center().x(), rect.center().y()
    outer_r = min(rect.width(), rect.height()) / 2 - 2
    inner_r = outer_r * 0.45
    painter.setBrush(QBrush(c))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2))
    painter.setBrush(QBrush(QColor("#eceae5")))
    painter.drawEllipse(QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2))
    painter.setBrush(QBrush(c))
    import math
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        tooth_x = cx + math.cos(rad) * (outer_r - 1)
        tooth_y = cy + math.sin(rad) * (outer_r - 1)
        painter.drawEllipse(QRectF(tooth_x - 2.5, tooth_y - 2.5, 5, 5))
    painter.restore()


def _draw_help_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制帮助(问号)图标"""
    painter.save()
    c = QColor(color)
    cx, cy = rect.center().x(), rect.center().y()
    radius = min(rect.width(), rect.height()) / 2 - 2
    painter.setBrush(QBrush(c))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    painter.setPen(QPen(QColor("#ffffff"), 2.5, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(cx - 3, cy - 3)
    path.cubicTo(cx - 3, cy - 7, cx + 3, cy - 7, cx + 3, cy - 3)
    path.cubicTo(cx + 3, cy - 1, cx, cy, cx, cy + 2)
    painter.drawPath(path)
    painter.drawPoint(QPointF(cx, cy + 5))
    painter.restore()


def _draw_info_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制关于(信息)图标"""
    painter.save()
    c = QColor(color)
    cx, cy = rect.center().x(), rect.center().y()
    radius = min(rect.width(), rect.height()) / 2 - 2
    painter.setBrush(QBrush(c))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    painter.setPen(QPen(QColor("#ffffff"), 2.5, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(cx, cy - 1), QPointF(cx, cy + 5))
    painter.drawPoint(QPointF(cx, cy - 5))
    painter.restore()


def _draw_device_icon(painter: QPainter, rect: QRectF, color="#5a6c7d"):
    """绘制设备管理(芯片+状态点)图标"""
    painter.save()
    c = QColor(color)
    painter.setBrush(QBrush(c))
    painter.setPen(QPen(c.darker(120), 1))
    r = rect.adjusted(4, 4, -4, -4)
    painter.drawRoundedRect(r, 2, 2)
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(QPen(c, 2))
    for off in (-4, 0, 4):
        painter.drawLine(QPointF(r.left() - 3, cy + off), QPointF(r.left(), cy + off))
        painter.drawLine(QPointF(r.right(), cy + off), QPointF(r.right() + 3, cy + off))
        painter.drawLine(QPointF(cx + off, r.top() - 3), QPointF(cx + off, r.top()))
        painter.drawLine(QPointF(cx + off, r.bottom()), QPointF(cx + off, r.bottom() + 3))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#39b568"))
    painter.drawEllipse(QPointF(cx, cy), 3, 3)
    painter.restore()


def _draw_tile_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """绘制平铺窗口(左右双窗格)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    mid = rect.center().x()
    left = QRectF(rect.left() + 1, rect.top() + 3,
                  mid - rect.left() - 2.5, rect.height() - 6)
    right = QRectF(mid + 1.5, rect.top() + 3,
                   rect.right() - mid - 2.5, rect.height() - 6)
    painter.drawRoundedRect(left, 2, 2)
    painter.drawRoundedRect(right, 2, 2)
    painter.restore()


def _draw_tabify_icon(painter: QPainter, rect: QRectF, color="#5a6c7d"):
    """绘制标签组(窗口+双标签页)图标"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    body = QRectF(rect.left() + 1, rect.top() + 7,
                  rect.width() - 2, rect.height() - 9)
    painter.drawRoundedRect(body, 2, 2)
    tw = (rect.width() - 8) / 2
    t1 = QRectF(rect.left() + 2, rect.top() + 2, tw, 6)
    t2 = QRectF(rect.left() + 4 + tw, rect.top() + 2, tw, 6)
    painter.setBrush(c)
    painter.drawRoundedRect(t1, 1.5, 1.5)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(t2, 1.5, 1.5)
    painter.restore()


def _draw_add_frame_icon(painter: QPainter, rect: QRectF, color="#4a7fb5"):
    """添加CAN帧: 报文矩形 + 绿色加号"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.6))
    painter.setBrush(QBrush(QColor("#e6eef6")))
    r = rect.adjusted(2, 6, -7, -6)
    painter.drawRoundedRect(r, 2, 2)
    painter.setPen(QPen(c, 1.2))
    painter.drawLine(QPointF(r.left() + 3, r.center().y()),
                     QPointF(r.right() - 3, r.center().y()))
    painter.setPen(QPen(QColor("#39b568"), 2.2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    cx, cy = rect.right() - 5, rect.top() + 6
    painter.drawLine(QPointF(cx - 3.5, cy), QPointF(cx + 3.5, cy))
    painter.drawLine(QPointF(cx, cy - 3.5), QPointF(cx, cy + 3.5))
    painter.restore()


def _draw_add_fd_icon(painter: QPainter, rect: QRectF, color="#7e57c2"):
    """添加CAN FD帧: 报文矩形 + FD 字样 + 加号"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.6))
    painter.setBrush(QBrush(QColor("#ede7f6")))
    r = rect.adjusted(2, 6, -7, -6)
    painter.drawRoundedRect(r, 2, 2)
    painter.setPen(QPen(c))
    painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "FD")
    painter.setPen(QPen(QColor("#39b568"), 2.2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    cx, cy = rect.right() - 5, rect.top() + 6
    painter.drawLine(QPointF(cx - 3.5, cy), QPointF(cx + 3.5, cy))
    painter.drawLine(QPointF(cx, cy - 3.5), QPointF(cx, cy + 3.5))
    painter.restore()


def _draw_add_db_icon(painter: QPainter, rect: QRectF, color="#00897b"):
    """从数据库添加帧: 数据库圆柱 + 加号"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.4))
    painter.setBrush(QBrush(QColor("#e0f2f1")))
    body = QRectF(rect.left() + 2, rect.top() + 7,
                  rect.width() - 10, rect.height() - 10)
    painter.drawRoundedRect(body, 2, 2)
    painter.drawEllipse(QRectF(rect.left() + 2, rect.top() + 4,
                               rect.width() - 10, 6))
    painter.setPen(QPen(QColor("#39b568"), 2.2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    cx, cy = rect.right() - 5, rect.top() + 6
    painter.drawLine(QPointF(cx - 3.5, cy), QPointF(cx + 3.5, cy))
    painter.drawLine(QPointF(cx, cy - 3.5), QPointF(cx, cy + 3.5))
    painter.restore()


def _draw_add_seq_icon(painter: QPainter, rect: QRectF, color="#ef6c00"):
    """添加序列: 三行列表 + 加号"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    x0 = rect.left() + 3
    for i, y in enumerate((rect.top() + 7, rect.top() + 12, rect.top() + 17)):
        painter.drawLine(QPointF(x0, y), QPointF(x0 + 11 - i * 2, y))
    painter.setPen(QPen(QColor("#39b568"), 2.2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    cx, cy = rect.right() - 5, rect.top() + 6
    painter.drawLine(QPointF(cx - 3.5, cy), QPointF(cx + 3.5, cy))
    painter.drawLine(QPointF(cx, cy - 3.5), QPointF(cx, cy + 3.5))
    painter.restore()


def _draw_remove_icon(painter: QPainter, rect: QRectF, color="#e53935"):
    """删除: 垃圾桶"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 1.5))
    painter.setBrush(QBrush(QColor("#fde8e8")))
    body = QRectF(rect.left() + 5, rect.top() + 8,
                  rect.width() - 10, rect.height() - 11)
    painter.drawRoundedRect(body, 2, 2)
    painter.setPen(QPen(c, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(rect.left() + 3, rect.top() + 7),
                     QPointF(rect.right() - 3, rect.top() + 7))
    painter.drawLine(QPointF(rect.center().x() - 3, rect.top() + 4),
                     QPointF(rect.center().x() + 3, rect.top() + 4))
    painter.restore()


def _draw_up_icon(painter: QPainter, rect: QRectF, color="#5a6c7d"):
    """上移: 向上箭头"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    path = QPainterPath()
    path.moveTo(cx - 5, cy + 1)
    path.lineTo(cx, cy - 5)
    path.lineTo(cx + 5, cy + 1)
    painter.drawPath(path)
    painter.drawLine(QPointF(cx, cy - 4), QPointF(cx, cy + 6))
    painter.restore()


def _draw_down_icon(painter: QPainter, rect: QRectF, color="#5a6c7d"):
    """下移: 向下箭头"""
    painter.save()
    c = QColor(color)
    painter.setPen(QPen(c, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    path = QPainterPath()
    path.moveTo(cx - 5, cy - 1)
    path.lineTo(cx, cy + 5)
    path.lineTo(cx + 5, cy - 1)
    painter.drawPath(path)
    painter.drawLine(QPointF(cx, cy + 4), QPointF(cx, cy - 6))
    painter.restore()


# 图标绘制函数映射
ICON_DRAWERS = {
    "new_project": _draw_folder_icon,
    "save_project": _draw_save_icon,
    "save_all": _draw_save_all_icon,
    "run": _draw_play_icon,
    "stop": _draw_stop_icon,
    "pause": _draw_pause_icon,
    "clear": _draw_clear_icon,
    "refresh": _draw_refresh_icon,
    "export": _draw_export_icon,
    "auto": _draw_auto_icon,
    "scroll": _draw_scroll_icon,
    "overwrite": _draw_overwrite_icon,
    "abs_time": _draw_abs_time_icon,
    "delta_time": _draw_delta_time_icon,
    "find_prev": _draw_find_prev_icon,
    "find_next": _draw_find_next_icon,
    "logger": _draw_logger_icon,
    "offline_run": _draw_offline_icon,
    "hexdec": _draw_hexdec_icon,
    "language": _draw_language_icon,
    "settings": _draw_settings_icon,
    "help_requested": _draw_help_icon,
    "about_requested": _draw_info_icon,
    "device_manage": _draw_device_icon,
    "tile": _draw_tile_icon,
    "tabify": _draw_tabify_icon,
    "add_can": _draw_add_frame_icon,
    "add_fd": _draw_add_fd_icon,
    "add_db": _draw_add_db_icon,
    "add_seq": _draw_add_seq_icon,
    "remove_item": _draw_remove_icon,
    "move_up": _draw_up_icon,
    "move_down": _draw_down_icon,
}


# ============================================================
# 按钮配置
# ============================================================

# 按钮组: 每组是一个列表, 组间有分隔线
# (图标key, 文字标签(中文原文=翻译key), tooltip(中文原文=key), 信号名, 是否危险)
BUTTON_GROUPS = [
    [
        ("new_project", "新建工程", "新建工程", "new_project", False),
        ("save_project", "保存", "保存工程", "save_project", False),
        ("save_all", "保存所有", "保存所有工程", "save_all", False),
    ],
    [
        ("run", "运行工程", "运行工程", "run", False),
        ("stop", "终止", "终止运行", "stop", True),
        ("offline_run", "脱机运行", "脱机运行", "offline_run", False),
    ],
    [
        ("tile", "平铺窗口", "所有面板平铺同时显示", "tile_windows", False),
        ("tabify", "标签组", "所有面板合并回标签切换", "tabify_windows", False),
    ],
    [
        ("device_manage", "设备管理", "当前工程设备管理", "device_manage", False),
        ("settings", "全局配置", "全局配置", "settings", False),
        ("help_requested", "帮助文档", "帮助文档", "help_requested", False),
        ("about_requested", "关于", "关于BusForge", "about_requested", False),
    ],
]

# 状态切换按钮组: 文字为当前状态指示 (HEX/DEC, 中/EN), 由 UISettings 驱动刷新
# (图标key, 信号名, tooltip中文key)
TOGGLE_GROUPS = [
    [
        ("hexdec", "toggle_number_format", "切换十进制/十六进制显示"),
        ("language", "toggle_language", "切换中英文"),
    ],
]


# ============================================================
# 自定义图标按钮 - 图标保持正方形等比例，不拉伸
# ============================================================

class _ToolButton(QPushButton):
    """图标在上、文字在下的工具按钮，图标由 QPainter 绘制"""

    def __init__(self, icon_key: str, text: str, tooltip: str,
                 is_danger: bool = False, parent=None):
        super().__init__(parent)
        self._icon_key = icon_key
        self._is_danger = is_danger
        self._label = ""   # 自绘文本 (基类文本置空, 避免与自绘文字重影)
        # 中文原文作为翻译 key (静态按钮用); 切换按钮文字由状态驱动
        self._text_key = text
        self._tooltip_key = tooltip
        self.setToolTip(tr(tooltip))
        self.setText(tr(text))
        self.setMinimumSize(52, 40)
        self.setMaximumHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("toolBtn", "danger" if is_danger else "normal")

    def setText(self, text: str):
        """文本仅自绘: 存到 _label, 基类文本置空以免 QSS/基类再画一份"""
        self._label = text
        super().setText("")

    def text(self) -> str:
        return self._label

    def sizeHint(self) -> QSize:
        """基类文本已置空, 需按自绘文字宽度给出尺寸, 避免长文本被裁切"""
        fm = QFontMetrics(QFont("Microsoft YaHei", 8))
        tw = fm.horizontalAdvance(self._label) + 14
        return QSize(max(52, tw), 40)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event):
        """先交基类/QSS 绘制背景边框, 再自绘勾选底+图标+文字"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 勾选态自绘实色底+边框 (不依赖 QSS, 确保白字始终有深色背景)
        if self.isChecked():
            bg = QColor("#5a8fc4") if self.underMouse() else QColor("#4a7fb5")
            painter.setPen(QPen(QColor("#3d6f9f"), 1))
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)

        w = self.width()
        h = self.height()

        # 图标区域: 正方形，居中于上半部分
        icon_size = min(w - 8, int(h * 0.55))
        icon_x = (w - icon_size) / 2
        icon_y = 2
        icon_rect = QRectF(icon_x, icon_y, icon_size, icon_size)

        drawer = ICON_DRAWERS.get(self._icon_key)
        if drawer:
            if not self.isEnabled():
                painter.setOpacity(0.35)   # 禁用: 图标置灰
            drawer(painter, icon_rect)
            if not self.isEnabled():
                painter.setOpacity(1.0)

        # 文字: 下半部分居中 (勾选态白字, 禁用变灰)
        text_rect = QRectF(0, h * 0.58, w, h * 0.42)
        if not self.isEnabled():
            pen_color = QColor("#9a9a9a")
        elif self.isChecked():
            pen_color = QColor("#ffffff")
        else:
            pen_color = QColor("#333333")
        painter.setPen(QPen(pen_color))
        font = QFont("Microsoft YaHei", 8)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._label)


# ============================================================
# 工具栏主组件
# ============================================================

class ToolbarWidget(QWidget):
    """顶部工具栏: 分组按钮栏，与下方工作区明显区分"""

    new_project = Signal()
    save_project = Signal()
    save_all = Signal()
    run = Signal()
    stop = Signal()
    offline_run = Signal()
    settings = Signal()
    device_manage = Signal()
    help_requested = Signal()
    about_requested = Signal()
    # 状态切换 (进制 / 语言)
    toggle_number_format = Signal()
    toggle_language = Signal()
    # 窗口管理 (平铺同显 / 合并标签组)
    tile_windows = Signal()
    tabify_windows = Signal()

    def set_running(self, running: bool):
        """运行状态联动: 运行中->运行/脱机置灰、终止可用; 停止后反之"""
        for name in ("run", "offline_run"):
            btn = self._buttons.get(name)
            if btn is not None:
                btn.setEnabled(not running)
        btn = self._buttons.get("stop")
        if btn is not None:
            btn.setEnabled(bool(running))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons = {}
        self._static_buttons = []          # 需随语言重译的按钮
        self._btn_hexdec = None
        self._btn_lang = None
        self._ui = UISettings.instance()
        self.setMaximumHeight(50)  # 紧凑高度
        self._setup_ui()
        self._connect_signals()
        # 订阅全局状态: 语言切换重译, 进制切换刷新按钮文字
        self._ui.language_changed.connect(lambda _l: self.retranslateUi())
        self._ui.number_format_changed.connect(
            lambda _f: self._refresh_toggles())
        self.retranslateUi()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- 按钮栏 ----
        btn_bar = QWidget()
        btn_bar.setMaximumHeight(44)
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(6, 2, 6, 2)
        btn_layout.setSpacing(1)

        last_gi = len(BUTTON_GROUPS) - 1
        for gi, group in enumerate(BUTTON_GROUPS):
            if gi > 0:
                btn_layout.addWidget(self._make_vsep())
            # 在最后一组(设备管理/配置/帮助/关于)之前插入"进制/语言"切换组
            if gi == last_gi:
                self._build_toggle_group(btn_layout)
                btn_layout.addWidget(self._make_vsep())
            for icon_key, text, tooltip, sig_name, is_danger in group:
                btn = _ToolButton(icon_key, text, tooltip, is_danger)
                btn_layout.addWidget(btn)
                self._buttons[sig_name] = btn
                self._static_buttons.append(btn)
            btn_layout.addSpacing(4)

        btn_layout.addStretch()
        layout.addWidget(btn_bar)

        # ---- 底部分隔线 (明显区分工具栏和工作区) ----
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #a09c96; max-height: 2px;")
        layout.addWidget(sep)

    @staticmethod
    def _make_vsep() -> QFrame:
        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setStyleSheet("background-color: #b8b4ae; max-width: 1px;")
        return vsep

    def _build_toggle_group(self, btn_layout):
        """构建进制/语言状态切换按钮组 (成组, 置于设备管理之前)"""
        for group in TOGGLE_GROUPS:
            for icon_key, sig_name, tooltip in group:
                btn = _ToolButton(icon_key, "", tooltip)
                btn_layout.addWidget(btn)
                self._buttons[sig_name] = btn
                if sig_name == "toggle_number_format":
                    self._btn_hexdec = btn
                elif sig_name == "toggle_language":
                    self._btn_lang = btn
            btn_layout.addSpacing(4)

    def _connect_signals(self):
        signal_map = {
            "new_project": self.new_project,
            "save_project": self.save_project,
            "save_all": self.save_all,
            "run": self.run,
            "stop": self.stop,
            "offline_run": self.offline_run,
            "settings": self.settings,
            "device_manage": self.device_manage,
            "help_requested": self.help_requested,
            "about_requested": self.about_requested,
            "toggle_number_format": self.toggle_number_format,
            "toggle_language": self.toggle_language,
            "tile_windows": self.tile_windows,
            "tabify_windows": self.tabify_windows,
        }
        for sig_name, signal in signal_map.items():
            btn = self._buttons.get(sig_name)
            if btn:
                btn.clicked.connect(signal.emit)

    # ------------------------------------------------------------------ #
    #  国际化 / 状态刷新
    # ------------------------------------------------------------------ #

    def retranslateUi(self):
        """按当前语言重设全部按钮文本/tooltip"""
        for btn in self._static_buttons:
            btn.setText(tr(btn._text_key))
            btn.setToolTip(tr(btn._tooltip_key))
        if self._btn_hexdec is not None:
            self._btn_hexdec.setToolTip(tr("切换十进制/十六进制显示"))
        if self._btn_lang is not None:
            self._btn_lang.setToolTip(tr("切换中英文"))
        self._refresh_toggles()

    def _refresh_toggles(self):
        """切换按钮文字反映当前状态 (HEX/DEC, 中/EN)"""
        if self._btn_hexdec is not None:
            self._btn_hexdec.setText("HEX" if self._ui.is_hex() else "DEC")
        if self._btn_lang is not None:
            self._btn_lang.setText(
                "中" if self._ui.language == "zh_CN" else "EN")
