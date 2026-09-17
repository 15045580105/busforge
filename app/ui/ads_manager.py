"""
ADS停靠管理器 - 封装PySide6-QtAds的DockManager

提供简洁的API来创建/管理停靠面板。
支持布局保存/恢复。
"""

import logging
from typing import Optional

from PySide6.QtWidgets import QWidget, QMenu
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.core.i18n import tr

logger = logging.getLogger(__name__)

try:
    import PySide6QtAds as qt_ads
    ADS_AVAILABLE = True
except ImportError:
    try:
        import qt_ads
        ADS_AVAILABLE = True
    except ImportError:
        qt_ads = None
        ADS_AVAILABLE = False
        logger.warning("PySide6-QtAds未安装, 将使用QDockWidget回退方案")


# ADS 停靠区样式: 朴素浅灰条, 不做花哨效果
_ADS_QSS = """
#BusForgeDockManager {
    background-color: #eceae5;
}
#dockAreaTitleBar {
    background: #e4e1dc;
    border: none;
    border-bottom: 1px solid #b8b4ae;
    padding: 3px 6px 0 6px;
}
"""

# 标签文字色: 活动=白字(蓝底), 非活动=深灰字(浅灰底)
_TAB_FG = {True: "#ffffff", False: "#555555"}

_TAB_QSS_CACHE: dict = {}


def _tab_qss(active: bool) -> str:
    """单标签样式表: 活动=蓝底白字, 非活动=浅灰底深灰字;
    对称内边距+间距, 不挤压; 整表换肤保证切换必重解析"""
    if active in _TAB_QSS_CACHE:
        return _TAB_QSS_CACHE[active]
    if active:
        bg, bd = "#2f7bc2", "#2568a8"
    else:
        bg, bd = "#d8d5cf", "#b8b4ae"
    qss = f"""
QWidget {{
    background: {bg};
    border: 1px solid {bd};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin: 0 3px 0 0;
    min-height: 18px;
    max-height: 18px;
}}
#dockWidgetTabLabel {{
    background: transparent;
    border: none;
    margin: 0px;
    color: {_TAB_FG[active]};
}}
#tabCloseButton {{
    background: transparent;
    border: none;
    margin: 0px;
    padding: 1px;
    min-width: 0px;
    min-height: 0px;
    max-width: 16px;
    max-height: 16px;
    border-radius: 3px;
}}
#tabCloseButton:hover {{
    background: #e05a5a;
}}
"""
    if not active:
        qss += """
QWidget:hover {
    background: #e6e3dd;
}
"""
    _TAB_QSS_CACHE[active] = qss
    return qss


class AdsManager:
    """
    ADS停靠管理器

    封装CDockManager，提供:
    - add_panel(title, widget) -> dock_widget
    - remove_panel(dock_widget)
    - save_layout() / restore_layout()
    """

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._dock_manager = None
        self._panels: dict[str, object] = {}  # panel_id -> CDockWidget
        self._hooked_areas: set[int] = set()  # 已连接切换信号的停靠区 id
        self._init_dock_manager()

    def _init_dock_manager(self):
        """初始化DockManager"""
        if ADS_AVAILABLE:
            # 配置ADS
            qt_ads.CDockManager.setConfigFlag(
                qt_ads.CDockManager.FloatingContainerHasWidgetTitle, True)
            qt_ads.CDockManager.setConfigFlag(
                qt_ads.CDockManager.FloatingContainerHasWidgetIcon, True)
            qt_ads.CDockManager.setConfigFlag(
                qt_ads.CDockManager.FocusHighlighting, True)
            qt_ads.CDockManager.setConfigFlag(
                qt_ads.CDockManager.DockAreaHasUndockButton, True)

            self._dock_manager = qt_ads.CDockManager(self._parent)
            self._dock_manager.setObjectName("BusForgeDockManager")
            # 浅色背景 + 醒目标签栏样式
            self._dock_manager.setStyleSheet(_ADS_QSS)
            # 焦点面板变化 -> 刷新标签活动态 (QSS [bfActive] 高亮当前页)
            try:
                self._dock_manager.focusedDockWidgetChanged.connect(
                    lambda *args: self._refresh_tab_states())
            except Exception as e:
                logger.debug(f"连接焦点信号失败: {e}")
            # 拖动拆分/浮动时显示动态预览, 便于看出可拖到何处同时显示
            for flag_name in ("DragPreviewIsDynamic",
                              "DragPreviewShowsContentPixmap"):
                flag = getattr(qt_ads.CDockManager, flag_name, None)
                if flag is not None:
                    try:
                        qt_ads.CDockManager.setConfigFlag(flag, True)
                    except Exception:
                        pass
            logger.info("ADS DockManager已初始化")
        else:
            logger.warning("ADS不可用, 使用回退方案")

    @property
    def dock_manager(self):
        return self._dock_manager

    def add_panel(self, title: str, widget: QWidget,
                  area: int = 0) -> object:
        """
        添加一个停靠面板

        Args:
            title: 面板标题
            widget: 面板内容widget
            area: 停靠区域(0=自动选择)

        Returns:
            CDockWidget对象
        """
        if not ADS_AVAILABLE:
            return None

        dock_widget = qt_ads.CDockWidget(title)
        dock_widget.setWidget(widget)

        if area == 0:
            # 默认以标签形式加入中心区: 多个面板同区标签切换,
            # 新标签置为当前(后打开的先显示); 拖动标签到边缘可拆分同显
            area_obj = self._dock_manager.addDockWidgetTab(
                qt_ads.CenterDockWidgetArea, dock_widget)
        else:
            area_obj = self._dock_manager.addDockWidget(
                area, dock_widget)

        self._panels[title] = dock_widget
        # 新打开的面板置顶显示 (后打开的先显示)
        try:
            dock_widget.toggleView(True)
            dock_widget.raise_()
        except Exception as e:
            logger.debug(f"面板置顶失败({title}): {e}")
        self._style_tab(dock_widget)
        self._setup_tab_menu(dock_widget)
        self._refresh_tab_states()
        logger.debug(f"面板已添加: {title}")
        return dock_widget

    def add_panel_to_area(self, title: str, widget: QWidget,
                          target_area: object = None) -> object:
        """添加面板到指定区域(可tab化)"""
        if not ADS_AVAILABLE:
            return None

        dock_widget = qt_ads.CDockWidget(title)
        dock_widget.setWidget(widget)

        if target_area:
            self._dock_manager.addDockWidgetToArea(
                qt_ads.CenterDockWidgetArea, dock_widget, target_area)
        else:
            self._dock_manager.addDockWidget(
                qt_ads.CenterDockWidgetArea, dock_widget)

        self._panels[title] = dock_widget
        self._style_tab(dock_widget)
        self._setup_tab_menu(dock_widget)
        self._refresh_tab_states()
        return dock_widget

    def remove_panel(self, title: str):
        """移除面板"""
        dock = self._panels.pop(title, None)
        if dock and ADS_AVAILABLE:
            dock.deleteLater()
            self._refresh_tab_states()
            logger.debug(f"面板已移除: {title}")

    def activate_panel(self, title: str):
        """激活面板(切换到前台)"""
        dock = self._panels.get(title)
        if dock and ADS_AVAILABLE:
            dock.toggleView(True)
            dock.raise_()
            self._refresh_tab_states()

    def get_panel(self, title: str) -> object:
        """获取面板"""
        return self._panels.get(title)

    def list_panels(self) -> list[str]:
        """列出所有面板标题"""
        return list(self._panels.keys())

    def save_layout(self) -> bytes:
        """保存当前布局为字节数据"""
        if not ADS_AVAILABLE:
            return b""
        return bytes(self._dock_manager.saveState())

    def restore_layout(self, data: bytes) -> bool:
        """恢复布局"""
        if not ADS_AVAILABLE or not data:
            return False
        ok = self._dock_manager.restoreState(data)
        self._restyle_all_tabs()
        return ok

    def create_perspective(self, name: str):
        """创建命名布局"""
        if ADS_AVAILABLE:
            self._dock_manager.addPerspective(name)
            logger.info(f"布局已保存: {name}")

    def switch_perspective(self, name: str):
        """切换到命名布局"""
        if ADS_AVAILABLE:
            self._dock_manager.openPerspective(name)
            self._restyle_all_tabs()
            logger.info(f"布局已切换: {name}")

    def get_perspective_names(self) -> list[str]:
        """获取所有命名布局"""
        if not ADS_AVAILABLE:
            return []
        return list(self._dock_manager.perspectives().keys())

    # ---------- 标签样式钩子 ----------

    def _style_tab(self, dock_widget, active: bool = False):
        """标签换肤: 活动=蓝底白字, 非活动=浅灰底深灰字;
        布局边距/字体用代码设置并刷新 sizeHint, 避免文字被省略"""
        try:
            tab = dock_widget.tabWidget()
            if tab is None:
                return
            tab.setProperty("bfActive", active)
            tab.setStyleSheet(_tab_qss(active))
            lay = tab.layout()
            if lay is not None:
                lay.setContentsMargins(12, 2, 12, 2)
                lay.setSpacing(4)
            lab = tab.findChild(QWidget, "dockWidgetTabLabel")
            if lab is not None:
                fg = _TAB_FG[active]
                lab.setStyleSheet(f"background: transparent; color: {fg};")
                font = QFont()
                font.setPixelSize(12)
                lab.setFont(font)
                lab.updateGeometry()
            tab.updateGeometry()
            tab.update()
        except Exception as e:
            logger.debug(f"标签样式钩子失败: {e}")

    def _setup_tab_menu(self, dock_widget):
        """标签右键菜单: 拆分同显 / 合并回标签组"""
        try:
            tab = dock_widget.tabWidget()
            if tab is None:
                return
            tab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tab.customContextMenuRequested.connect(
                lambda pos, d=dock_widget: self._show_tab_menu(d, pos))
        except Exception as e:
            logger.debug(f"标签菜单钩子失败: {e}")

    def _show_tab_menu(self, dock_widget, pos):
        """弹出标签操作菜单 (多界面同显入口)"""
        title = next((t for t, d in self._panels.items()
                      if d is dock_widget), None)
        if title is None:
            return
        tab = dock_widget.tabWidget()
        menu = QMenu(self._parent)
        act_right = menu.addAction(tr("右侧拆分显示"))
        act_down = menu.addAction(tr("下方拆分显示"))
        act_tab = menu.addAction(tr("合并到标签组"))
        chosen = menu.exec(tab.mapToGlobal(pos))
        if chosen is act_right:
            self.split_panel(title, vertical=False)
        elif chosen is act_down:
            self.split_panel(title, vertical=True)
        elif chosen is act_tab:
            self.tabify_panel(title)

    def split_panel(self, title: str, vertical: bool = False) -> bool:
        """把面板拆分到原区域右侧/下方, 实现多界面同时显示"""
        dock = self._panels.get(title)
        if not dock or not ADS_AVAILABLE:
            return False
        area = dock.dockAreaWidget()
        target = (qt_ads.BottomDockWidgetArea if vertical
                  else qt_ads.RightDockWidgetArea)
        try:
            self._dock_manager.addDockWidget(target, dock, area)
        except TypeError:
            self._dock_manager.addDockWidget(target, dock)
        self._refresh_tab_states()
        logger.debug(f"面板已拆分同显: {title}"
                     f"({'下' if vertical else '右'})")
        return True

    def tabify_panel(self, title: str) -> bool:
        """把面板合并回标签组 (中心区标签切换)"""
        dock = self._panels.get(title)
        if not dock or not ADS_AVAILABLE:
            return False
        ref_area = next((d.dockAreaWidget() for d in self._panels.values()
                         if d is not dock), None)
        try:
            if ref_area is not None:
                self._dock_manager.addDockWidgetTabToArea(dock, ref_area)
            else:
                self._dock_manager.addDockWidgetTab(
                    qt_ads.CenterDockWidgetArea, dock)
        except Exception as e:
            logger.debug(f"合并标签组失败({title}): {e}")
            return False
        self._refresh_tab_states()
        logger.debug(f"面板已合并回标签组: {title}")
        return True

    def tile_panels(self) -> bool:
        """平铺所有面板 (CANoe 式多窗口同显): 首个保持原区,
        其余依次向右/向下拆分"""
        if not ADS_AVAILABLE:
            return False
        docks = [d for d in self._panels.values() if d is not None]
        if len(docks) < 2:
            return False
        prev = docks[0].dockAreaWidget()
        for i, d in enumerate(docks[1:], start=1):
            target = (qt_ads.BottomDockWidgetArea if i % 2 == 0
                      else qt_ads.RightDockWidgetArea)
            try:
                self._dock_manager.addDockWidget(target, d, prev)
            except TypeError:
                self._dock_manager.addDockWidget(target, d)
            prev = d.dockAreaWidget()
        self._refresh_tab_states()
        logger.info(f"窗口已平铺: {len(docks)} 个面板")
        return True

    def tabify_all_panels(self) -> bool:
        """所有面板合并回中心标签组"""
        if not ADS_AVAILABLE:
            return False
        docks = [d for d in self._panels.values() if d is not None]
        if not docks:
            return False
        base = docks[0].dockAreaWidget()
        for d in docks[1:]:
            if d.dockAreaWidget() is not base:
                self._dock_manager.addDockWidgetTabToArea(d, base)
        self._refresh_tab_states()
        logger.info("所有面板已合并回标签组")
        return True

    def _restyle_all_tabs(self):
        """恢复布局/切换视角后按当前活动态重套全部标签样式"""
        for dock in list(self._panels.values()):
            try:
                self._style_tab(dock, bool(dock.isCurrentTab()))
            except Exception:
                continue

    def _hook_area(self, area):
        """连接停靠区当前标签切换信号 (防重复连接)"""
        if area is None:
            return
        key = id(area)
        if key in self._hooked_areas:
            return
        self._hooked_areas.add(key)
        try:
            area.currentChanged.connect(
                lambda *args: self._refresh_tab_states())
        except Exception as e:
            logger.debug(f"连接停靠区信号失败: {e}")

    def _refresh_tab_states(self):
        """按当前活动态换肤各标签: 活动页白底青顶, 一眼可辨"""
        if not ADS_AVAILABLE or self._dock_manager is None:
            return
        for dock in list(self._panels.values()):
            try:
                self._hook_area(dock.dockAreaWidget())
                tab = dock.tabWidget()
                if tab is None:
                    continue
                active = bool(dock.isCurrentTab())
                if tab.property("bfActive") != active:
                    self._style_tab(dock, active)
            except Exception:
                continue
