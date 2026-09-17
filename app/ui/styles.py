"""
BusForge QSS样式 - 暖灰专业工业风

配色参考真实工业软件 (CANoe/LabVIEW/MATLAB):
- 主背景: #eceae5 (暖灰)
- 面板色: #f2f0eb (浅暖灰)
- 侧栏色: #e4e2dd (中暖灰)
- 文字色: #333333 (深灰, 非纯黑)
- 强调色: #4a7fb5 (钢蓝)
- 选中态: #c5d8e8 (淡蓝)
- 边框色: #c8c4be (暖灰边框)
"""

import os

# 复选框"选中"对勾图标 (运行时按需生成, 供QSS indicator引用)
_RES_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "resources"))
_CHECK_ICON_PATH = os.path.join(_RES_DIR, "checkbox_checked.png").replace("\\", "/")
_DOWN_ARROW_PATH = os.path.join(_RES_DIR, "combo_down_arrow.png").replace("\\", "/")
_DOWN_ARROW_GRAY_PATH = os.path.join(_RES_DIR, "combo_down_arrow_gray.png").replace("\\", "/")


def _ensure_check_icon() -> str:
    """生成白底蓝勾的选中态图标PNG (QSS的url()不支持data URI, 需用文件路径)"""
    if os.path.exists(_CHECK_ICON_PATH):
        return _CHECK_ICON_PATH
    try:
        from PySide6.QtCore import Qt, QPointF
        from PySide6.QtGui import QImage, QPainter, QPen, QColor
        size = 32
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#4a7fb5"))
        pen.setWidthF(3.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([
            QPointF(size * 0.20, size * 0.54),
            QPointF(size * 0.42, size * 0.75),
            QPointF(size * 0.80, size * 0.27),
        ])
        p.end()
        os.makedirs(_RES_DIR, exist_ok=True)
        img.save(_CHECK_ICON_PATH)
    except Exception:
        pass
    return _CHECK_ICON_PATH


def _ensure_combo_arrows():
    """生成QComboBox下拉箭头图标PNG (自定义::drop-down后Windows不再绘默认箭头)"""
    try:
        from PySide6.QtCore import Qt, QPointF
        from PySide6.QtGui import QImage, QPainter, QColor, QPolygonF
        for path, color in ((_DOWN_ARROW_PATH, "#555555"),
                            (_DOWN_ARROW_GRAY_PATH, "#a5a099")):
            if os.path.exists(path):
                continue
            w, h = 24, 16
            img = QImage(w, h, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawPolygon(QPolygonF([
                QPointF(3, 3), QPointF(w - 3, 3), QPointF(w / 2, h - 3),
            ]))
            p.end()
            os.makedirs(_RES_DIR, exist_ok=True)
            img.save(path)
    except Exception:
        pass

# ============================================================
# 暖灰专业工业风主题 - Soft Tech
# ============================================================

SOFT_TECH = """
/* ---- 全局 ---- */
QWidget {
    background-color: #eceae5;
    color: #333333;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow {
    background-color: #eceae5;
}

/* ---- 菜单栏 ---- */
QMenuBar {
    background-color: #f2f0eb;
    color: #333333;
    border-bottom: 1px solid #c8c4be;
    padding: 2px 4px;
    font-size: 13px;
}
QMenuBar::item {
    padding: 4px 12px;
}
QMenuBar::item:selected {
    background-color: #c5d8e8;
}
QMenu {
    background-color: #f2f0eb;
    border: 1px solid #c0bcb6;
    padding: 3px;
}
QMenu::item {
    padding: 5px 28px;
}
QMenu::item:selected {
    background-color: #c5d8e8;
}
QMenu::separator {
    height: 1px;
    background: #c8c4be;
    margin: 3px 8px;
}

/* ---- 工具栏按钮 (自定义ToolButton) ---- */
QPushButton[toolBtn="normal"] {
    background-color: transparent;
    color: #333333;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px;
}
QPushButton[toolBtn="normal"]:hover {
    background-color: #e4e2dd;
    border-color: #c0bcb6;
}
QPushButton[toolBtn="normal"]:pressed {
    background-color: #c5d8e8;
}
/* 可勾选工具按钮的开启态: 实色钢蓝底+深钢蓝边框 (文字由控件自绘为白色), 选中/取消对比明显 */
QPushButton[toolBtn="normal"]:checked {
    background-color: #4a7fb5;
    border-color: #3d6f9f;
}
QPushButton[toolBtn="normal"]:checked:hover {
    background-color: #5a8fc4;
}
QPushButton[toolBtn="danger"] {
    background-color: transparent;
    color: #c53030;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px;
}
QPushButton[toolBtn="danger"]:hover {
    background-color: #fde8e8;
    border-color: #e53935;
}
QPushButton[toolBtn="danger"]:pressed {
    background-color: #f5c6c6;
}

/* ---- 标签页 (工具栏顶部Tab) ---- */
QTabBar {
    background-color: #f2f0eb;
    border-bottom: none;
}
QTabBar::tab {
    background-color: #e8ecf1;
    color: #666666;
    padding: 6px 18px;
    border: 1px solid #c8c4be;
    border-bottom: none;
    margin-right: 1px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background-color: #f2f0eb;
    color: #4a7fb5;
    border-bottom: 2px solid #f2f0eb;
    font-weight: 700;
}
QTabBar::tab:hover:!selected {
    background-color: #e4e2dd;
}

/* ---- 表格 ---- */
QTableWidget, QTableView {
    background-color: #fafbfc;
    alternate-background-color: #f4f5f6;
    color: #333333;
    gridline-color: #eceef1;
    border: 1px solid #dcdfe4;
    border-radius: 4px;
    selection-background-color: #c5d8e8;
    selection-color: #1f2d3d;
}
QHeaderView::section {
    background-color: #f7f8fa;
    color: #55606e;
    padding: 7px 8px;
    border: none;
    border-right: 1px solid #e8eaee;
    border-bottom: 2px solid #d9dde3;
    font-weight: 600;
    font-size: 12px;
}
QHeaderView::section:last {
    border-right: none;
}
QHeaderView::section:hover {
    background-color: #eef1f5;
}

/* ---- 树形视图 ---- */
QTreeWidget, QTreeView {
    background-color: #fafbfc;
    alternate-background-color: #f4f5f6;
    color: #333333;
    border: 1px solid #dcdfe4;
    border-radius: 4px;
    selection-background-color: #c5d8e8;
    selection-color: #1f2d3d;
    outline: none;
    font-size: 13px;
}
QTreeWidget::item, QTreeView::item {
    padding: 2px 4px;
    color: #333333;
}
/* 树内行内控件/编辑框: 紧凑贴合单元格, 完美适配不留白 */
QTreeWidget QComboBox, QTreeWidget QSpinBox, QTreeWidget QDoubleSpinBox,
QTreeWidget QLineEdit {
    padding: 1px 4px;
}
QTreeWidget QPushButton {
    padding: 2px 6px;
    min-width: 40px;
}
/* 工程树保留侧栏底色 (无表头), 不随数据表格变白 */
QTreeWidget#projectTree {
    background-color: #e8ecf1;
    alternate-background-color: #e2e8ef;
    border: none;
    border-radius: 0;
    selection-background-color: #c5d8e8;
}
/* 树行不加悬停高亮: 鼠标滑过绝不能看起来像选中 (选中只能由点击产生) */
QTreeWidget::item:selected, QTreeView::item:selected {
    background-color: #c5d8e8;
}
/* 注意: 不要为 ::branch 设置样式规则, 否则 Qt 在匹配状态下不再绘制原生展开箭头 */

/* ---- 输入框 ---- */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #c0bcb6;
    padding: 5px 8px;
    selection-background-color: #c5d8e8;
    selection-color: #333333;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #4a7fb5;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background-color: #c5c0b9;
    color: #888888;
    border-color: #b0aba4;
}
/* hex 字节格行内编辑器: 27px 小格, 零 padding 保证两位字符完整可见 */
QLineEdit#hexCellEditor {
    padding: 0 2px;
    border-color: #4a7fb5;
}
/* 列表头漏斗筛选按钮: 透明底, 悬浮淡显 */
QToolButton#hdrFilterBtn {
    border: none;
    background: transparent;
}
QToolButton#hdrFilterBtn:hover {
    background: #dde3ea;
    border-radius: 3px;
}
/* 列头筛选弹窗 (ID 输入) */
QFrame#filterPopup {
    background: #ffffff;
    border: 1px solid #c9d1dc;
    border-radius: 4px;
}
/* ---- 下拉框 ---- */
QComboBox {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #c0bcb6;
    padding: 5px 8px;
    min-width: 60px;
}
QComboBox:hover {
    border-color: #4a7fb5;
}
QComboBox:disabled {
    background-color: #d6d2ca;
    color: #96928b;
    border: 1px solid #b3aea6;
}
QComboBox:disabled::drop-down {
    background-color: #d6d2ca;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    image: url(@DOWN_ARROW@);
    width: 10px;
    height: 7px;
}
QComboBox::down-arrow:disabled {
    image: url(@DOWN_ARROW_GRAY@);
}
QComboBox QAbstractItemView {
    background-color: #f2f0eb;
    border: 1px solid #c0bcb6;
    selection-background-color: #c5d8e8;
}

/* ---- 按钮 ---- */
QPushButton {
    background-color: #e4e2dd;
    color: #333333;
    border: 1px solid #c0bcb6;
    padding: 5px 14px;
    min-width: 50px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #d8d5cf;
    border-color: #a09c96;
}
QPushButton:pressed {
    background-color: #c5d8e8;
    border-color: #4a7fb5;
}
QPushButton:disabled {
    background-color: #c5c0b9;
    color: #888888;
    border-color: #b0aba4;
}
QPushButton#primaryBtn {
    background-color: #4a7fb5;
    color: #ffffff;
    border-color: #3d6f9f;
}
QPushButton#primaryBtn:hover {
    background-color: #5a8fc4;
}
QPushButton#dangerBtn {
    background-color: #c53030;
    color: #ffffff;
    border-color: #a82418;
}
QPushButton#dangerBtn:hover {
    background-color: #d43525;
}
QPushButton#successBtn {
    background-color: #2f855a;
    color: #ffffff;
    border-color: #246638;
}

/* ---- 面板语义按钮 (柔和低饱和 soft 风格; 通过动态属性 btnRole 区分角色) ----
   success=启动/运行, danger=停止/删除, primary=添加/主操作, neutral=次要操作
   浅色底 + 同色系深色字 + 柔和边框: 有色彩层次便于辨认, 但低饱和不艳丽,
   与暖灰工业风协调; 不影响上方 #primaryBtn/#dangerBtn/#successBtn 实色按钮 */
QPushButton[btnRole="success"] {
    background-color: #e4efe7;
    color: #2f6b46;
    border: 1px solid #b6d2c0;
    font-weight: 600;
}
QPushButton[btnRole="success"]:hover {
    background-color: #d5e7db;
    border-color: #94bda4;
}
QPushButton[btnRole="success"]:pressed {
    background-color: #c5dccd;
}
QPushButton[btnRole="success"]:disabled {
    background-color: #e7e5e0;
    color: #a5a29c;
    border-color: #d0ccc5;
    font-weight: 600;
}
QPushButton[btnRole="danger"] {
    background-color: #f5e6e4;
    color: #a5372f;
    border: 1px solid #e3c1bc;
    font-weight: 600;
}
QPushButton[btnRole="danger"]:hover {
    background-color: #eed5d1;
    border-color: #d5a49d;
}
QPushButton[btnRole="danger"]:pressed {
    background-color: #e7c5c0;
}
QPushButton[btnRole="danger"]:disabled {
    background-color: #e7e5e0;
    color: #a5a29c;
    border-color: #d0ccc5;
    font-weight: 600;
}
QPushButton[btnRole="primary"] {
    background-color: #e6eef6;
    color: #35618f;
    border: 1px solid #c1d4e7;
    font-weight: 600;
}
QPushButton[btnRole="primary"]:hover {
    background-color: #d7e5f1;
    border-color: #a3c1dc;
}
QPushButton[btnRole="primary"]:pressed {
    background-color: #c8daea;
}
QPushButton[btnRole="primary"]:disabled {
    background-color: #e7e5e0;
    color: #a5a29c;
    border-color: #d0ccc5;
    font-weight: 600;
}
QPushButton[btnRole="neutral"] {
    background-color: #ebe9e4;
    color: #4a4741;
    border: 1px solid #d0ccc5;
}
QPushButton[btnRole="neutral"]:hover {
    background-color: #e0ded7;
    border-color: #b8b4ac;
}
QPushButton[btnRole="neutral"]:pressed {
    background-color: #d5d2ca;
}
QPushButton[btnRole="neutral"]:disabled {
    background-color: #e7e5e0;
    color: #a5a29c;
    border-color: #d0ccc5;
}

/* ---- 文本区域 ---- */
QTextEdit, QPlainTextEdit {
    background-color: #f2f0eb;
    color: #333333;
    border: 1px solid #c8c4be;
    padding: 6px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    selection-background-color: #c5d8e8;
}

/* ---- 滚动条 ---- */
QScrollBar:vertical {
    background-color: #eceae5;
    width: 10px;
}
QScrollBar::handle:vertical {
    background-color: #b0aca6;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background-color: #908c86;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background-color: #eceae5;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background-color: #b0aca6;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #908c86;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ---- 分组框 ---- */
QGroupBox {
    border: 1px solid #c8c4be;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: 600;
    font-size: 13px;
    color: #333333;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #333333;
}

/* ---- 分割条 ---- */
QSplitter::handle {
    background-color: #d8dce2;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}
QSplitter::handle:hover {
    background-color: #4a7fb5;
}

/* ---- 状态栏 ---- */
QStatusBar {
    background-color: #4a7fb5;
    color: #ffffff;
    border: none;
    padding: 3px 10px;
    font-size: 12px;
}
QStatusBar::item {
    border: none;
}

/* ---- 进度条 ---- */
QProgressBar {
    background-color: #e4e2dd;
    border: 1px solid #c0bcb6;
    text-align: center;
    color: #333333;
    height: 6px;
}
QProgressBar::chunk {
    background-color: #4a7fb5;
}

/* ---- 复选框 ---- */
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #a09c96;
    background-color: #ffffff;
    border-radius: 2px;
}
QCheckBox::indicator:checked {
    background-color: #ffffff;
    border: 1px solid #4a7fb5;
    image: url(@CHECK_ICON@);
}

/* ---- 单选框 ---- */
QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #a09c96;
    background-color: #ffffff;
    border-radius: 8px;
}
QRadioButton::indicator:checked {
    background-color: #4a7fb5;
    border-color: #4a7fb5;
}

/* ---- 标签 ---- */
QLabel {
    color: #333333;
    background-color: transparent;
}
/* 禁用字段占位: 明显置灰 (Windows原生风格不绘制QComboBox disabled背景) */
QLabel#disabledField {
    background-color: #cfcac2;
    color: #8b8780;
    border: 1px solid #b0aba4;
    padding: 5px 8px;
}
QLabel#TreeHeader {
    background-color: #e8ecf1;
    color: #333333;
    font-weight: bold;
    font-size: 13px;
    border-bottom: 1px solid #c8c4be;
    padding-left: 8px;
}
/* 面板顶部用法提示条: 柔和底色 + 左侧强调竖线, 与内容区分层 */
QLabel#hintBar {
    background-color: #eef1f5;
    color: #55524b;
    border: 1px solid #d7dbe0;
    border-left: 3px solid #4a7fb5;
    border-radius: 3px;
    padding: 6px 10px;
    font-size: 12px;
}
/* 提示条运行反馈(失败警示): 淡红底 + 红竖线, 4s 后恢复 */
QLabel#hintBar[alert="true"] {
    background-color: #f7e9e7;
    color: #8f3a33;
    border: 1px solid #ddbeb9;
    border-left: 3px solid #b3502f;
}
/* 面板主体背景: 暖灰底让白色表格卡片化浮于其上, 避免全白空旷 */
QWidget#transmitPanel {
    background-color: #f0f2f4;
}
/* 面板工具栏条块: 浅底+边框, 与内容区明确区分不连成一片 */
QWidget#panelToolbar {
    background-color: #f2f0eb;
    border: 1px solid #d8d5cf;
    border-radius: 5px;
}

/* ---- 面板分节标题: 钢蓝强调色 + 底部分隔线, 让配置区层次清晰 ---- */
QLabel#sectionHeader {
    color: #35618f;
    font-weight: 700;
    font-size: 13px;
    background-color: transparent;
    border-bottom: 1px solid #d8d5cf;
    padding-bottom: 4px;
}

/* ---- Logger 通道多选下拉 (CheckCombo): 仿输入框字段外观, 与 QLineEdit/QComboBox 一致 ---- */
QPushButton#checkComboBtn {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #c0bcb6;
    border-radius: 3px;
    padding: 5px 8px;
    text-align: left;
    min-width: 60px;
    font-weight: 400;
}
QPushButton#checkComboBtn:hover {
    border-color: #4a7fb5;
}
QPushButton#checkComboBtn:pressed {
    background-color: #f2f0eb;
    border-color: #4a7fb5;
}
QMenu#checkComboMenu {
    background-color: #ffffff;
    border: 1px solid #c0bcb6;
    border-radius: 4px;
    padding: 3px;
}
QListWidget#checkComboList {
    background-color: #ffffff;
    border: none;
    outline: none;
}
QListWidget#checkComboList::item {
    padding: 4px 10px;
    border-radius: 3px;
    color: #333333;
}
QListWidget#checkComboList::item:hover {
    background-color: #eef1f5;
}

/* ---- Dock Widget (Qt原生) ---- */
QDockWidget {
    color: #333333;
}
QDockWidget::title {
    background-color: #e4e2dd;
    padding: 5px 10px;
    border: 1px solid #c8c4be;
    text-align: left;
    font-weight: 600;
    font-size: 12px;
}

/* ---- ADS Docking System (PySide6-QtAds) ---- */
ads--CDockWidgetTab {
    background-color: #e4e2dd;
    color: #666666;
    border: none;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
}
ads--CDockWidgetTab[selected="true"] {
    background-color: #f2f0eb;
    color: #333333;
    border-bottom: 2px solid #4a7fb5;
}
ads--CDockWidgetTab:hover:!selected {
    background-color: #d8d5cf;
}
ads--CDockAreaWidget {
    background-color: #ffffff;
    border: none;
}
ads--CDockContainerWidget {
    background-color: #ffffff;
}
ads--CDockSplitterHandle {
    background-color: #c0bcb6;
}
ads--CFloatingDockContainer {
    border: 1px solid #c0bcb6;
    background-color: #f2f0eb;
}
ads--CDockAreaTabBar {
    background-color: #e4e2dd;
    border: none;
}
ads--CDockWidgetTab QPushButton {
    background-color: transparent;
    border: none;
    color: #888888;
    padding: 2px 4px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 10px;
}
ads--CDockWidgetTab QPushButton:hover {
    color: #333333;
    background-color: #c0bcb6;
}
"""


# 主题注册表: name -> 显示名 (当前仅一套已实现主题, 为未来扩展预留)
THEMES = {
    "soft_tech": "暖灰工业风",
}


def get_theme(name: str = "soft_tech") -> str:
    """
    获取主题QSS字符串

    Args:
        name: 主题名称 (目前仅支持 soft_tech)

    Returns:
        QSS样式字符串
    """
    _ensure_check_icon()
    _ensure_combo_arrows()
    return (SOFT_TECH
            .replace("@CHECK_ICON@", _CHECK_ICON_PATH)
            .replace("@DOWN_ARROW@", _DOWN_ARROW_PATH)
            .replace("@DOWN_ARROW_GRAY@", _DOWN_ARROW_GRAY_PATH))
