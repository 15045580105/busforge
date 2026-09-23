"""
BusForge 主窗口 - 薄壳QMainWindow

仅负责窗口框架(标题/大小/菜单/状态栏/工具栏)，
所有业务逻辑委托给 BusForgeWidget。
"""

import logging

from PySide6.QtWidgets import (
    QMainWindow, QStatusBar, QVBoxLayout, QWidget, QMessageBox, QLabel
)
from PySide6.QtCore import Qt, QTimer

from app.config import AppConfig
from app.common.ui_settings import UISettings
from app.common.workspace import WorkspaceManager
from app.common.i18n import tr
from app.ui.busforge_widget import BusForgeWidget
from app.ui.toolbar_widget import ToolbarWidget

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """BusForge主窗口 - 薄壳"""

    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config
        self._ui = UISettings.instance()

        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        # 核心业务Widget
        self._widget = BusForgeWidget(config, parent=self)

        # 工具栏
        self._toolbar = ToolbarWidget()

        # 中央区域: 工具栏 + 业务Widget
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._toolbar)
        central_layout.addWidget(self._widget)
        self.setCentralWidget(central)

        self._setup_statusbar()
        self._connect_toolbar()
        self.retranslateUi()

        # 语言切换 -> 重译窗口标题/状态栏
        self._ui.language_changed.connect(lambda _l: self.retranslateUi())

        # 启动后恢复上次工作空间会话 (延到事件循环, 确保布局就绪)
        QTimer.singleShot(0, self._restore_session)

        logger.info("主窗口已初始化")

    # ---- 国际化 ----

    def retranslateUi(self):
        """按当前语言重设窗口标题与状态栏"""
        self.setWindowTitle(
            f"BusForge v0.1.0 - {tr('总线分析与诊断工具')}")
        self.statusBar().showMessage(f"BusForge v0.1.0 | {tr('就绪')}")
        self._set_run_project(self._run_project_name)

    # ---- 状态栏 ----

    def _setup_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(f"BusForge v0.1.0 | {tr('就绪')}")
        # 常驻提示: 当前运行的是哪个工程 (右侧, 不被临时消息覆盖)
        self._run_project_name = ""
        self._run_project_label = QLabel()
        sb.addPermanentWidget(self._run_project_label)
        self._set_run_project("")

    def _set_run_project(self, name: str):
        """状态栏常驻运行工程徽章: 绿底白字=运行中, 浅灰胶囊=未运行"""
        self._run_project_name = name
        if name:
            self._run_project_label.setText(f"▶ {tr('运行中')}: {name}")
            self._run_project_label.setStyleSheet(
                "background-color: #2e7d32; color: #ffffff;"
                "font-weight: 700; border-radius: 4px;"
                "padding: 3px 12px; margin: 2px 8px 2px 2px;")
        else:
            self._run_project_label.setText(f"○ {tr('未运行')}")
            self._run_project_label.setStyleSheet(
                "background-color: #e3e7ea; color: #6c7280;"
                "border-radius: 4px;"
                "padding: 3px 12px; margin: 2px 8px 2px 2px;")

    # ---- 工具栏信号 ----

    def _connect_toolbar(self):
        self._toolbar.run.connect(self._on_run)
        self._toolbar.stop.connect(self._on_stop)
        self._toolbar.offline_run.connect(self._on_offline_run)
        self._toolbar.settings.connect(self._on_settings)
        self._toolbar.about_requested.connect(self._show_about)
        self._toolbar.new_project.connect(self._on_new_project)
        self._toolbar.save_project.connect(self._on_save_project)
        self._toolbar.save_all.connect(self._on_save_all)
        self._toolbar.device_manage.connect(
            lambda: self._widget.open_device_panel())
        # 进制 / 语言 切换 -> 全局 UISettings 单例
        from app.common.ui_settings import UISettings
        ui = UISettings.instance()
        self._toolbar.toggle_number_format.connect(ui.toggle_number_format)
        self._toolbar.toggle_language.connect(ui.toggle_language)
        # 窗口管理: 平铺同显 / 合并标签组 (CANoe 式多窗口)
        self._toolbar.tile_windows.connect(self._widget.tile_panels)
        self._toolbar.tabify_windows.connect(self._widget.tabify_panels)
        # 运行/连接状态 -> 状态栏 (含异步连接进度)
        self._widget.run_state_changed.connect(
            lambda text: self.statusBar().showMessage(text, 5000))
        # 运行态 -> 工具栏按钮置灰联动 (启动时停止态: 终止置灰)
        self._widget.run_active_changed.connect(self._toolbar.set_running)
        self._toolbar.set_running(False)
        # 运行工程名 -> 状态栏常驻提示
        self._widget.run_project_changed.connect(self._set_run_project)

    def _on_run(self):
        self._widget.run_project()

    def _on_stop(self):
        self._widget.stop_project()

    def _on_offline_run(self):
        logger.info("脱机运行")

    def _on_settings(self):
        """打开全局配置面板 (与设备管理一致停靠)"""
        self._widget.open_settings_panel()

    def _on_new_project(self):
        tree = self._widget.get_project_tree()
        if tree:
            tree.create_project()

    def _on_save_project(self):
        tree = self._widget.get_project_tree()
        if tree:
            tree.save_project()

    def _on_save_all(self):
        """保存所有项目 (按 pid 序列化, 不切换活动工程)"""
        tree = self._widget.get_project_tree()
        if tree:
            saved = tree.save_all_projects()
            self.statusBar().showMessage(
                tr("已保存 {n} 个项目").format(n=saved), 5000)
            logger.info(f"已保存所有 {saved} 个项目")

    # ---- 关于 ----

    def _show_about(self):
        QMessageBox.about(
            self, tr("关于 BusForge"),
            tr("BusForge v0.1.0\n\n独立总线分析与诊断工具\n"
               "支持 CAN / LIN / Ethernet\n基于 TSMaster DLL"))

    # ---- 工作空间会话 ----

    def _restore_session(self):
        """启动时恢复上次会话 (全部工程/设备/通道/面板)"""
        if not getattr(self._config, "auto_restore_session", True):
            return
        data = WorkspaceManager.load()
        if not data:
            return
        tree = self._widget.get_project_tree()
        if not tree:
            return
        projects = data.get("projects", [])
        active_index = data.get("active_index", 0)
        if not projects:
            return
        try:
            tree.restore_session(projects, active_index)
            self.statusBar().showMessage(
                tr("已恢复上次会话: {n} 个工程").format(n=len(projects)), 5000)
        except Exception as e:
            logger.error(f"会话恢复失败: {e}")

    # ---- 关闭 ----

    def closeEvent(self, event):
        self._widget.shutdown()
        # 保存工作空间会话 (全部打开的工程完整定义), 供下次启动恢复
        if getattr(self._config, "auto_restore_session", True):
            tree = self._widget.get_project_tree()
            if tree:
                try:
                    WorkspaceManager.save(
                        tree.serialize_all_projects(),
                        tree.project_manager.active_index)
                except Exception as e:
                    logger.error(f"保存工作空间失败: {e}")
        # 保存主题/布局/语言/进制等 app 级配置
        self._config.save()
        super().closeEvent(event)
