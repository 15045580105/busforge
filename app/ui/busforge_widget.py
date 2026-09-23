"""
BusForgeWidget - 核心业务组件

可嵌入QMainWindow或第三方平台的总线分析工具Widget。
包含ADS停靠管理、双树导航、设备管理、面板管理等全部业务逻辑。

作为插件使用时，外部平台只需:
    widget = BusForgeWidget(config, parent=host_widget)
    host_layout.addWidget(widget)
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QPlainTextEdit
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont

from app.config import AppConfig
from app.devices.device_manager import DeviceManager
from app.datahub.data_hub import DataHub
from app.devices.connect_worker import ConnectWorker
from app.common.message_bus import MessageBus
from app.common.variable_system import VariableRegistry
from app.ui.project_tree import ProjectTree
from app.ui.ads_manager import AdsManager, ADS_AVAILABLE
from app.devices.device_manage_panel import DeviceManagePanel
from app.ui.settings_panel import SettingsPanel

logger = logging.getLogger(__name__)


class BusForgeWidget(QWidget):
    """
    BusForge核心业务Widget

    封装全部总线分析功能，可独立运行或嵌入第三方平台。
    外部平台通过公共API与BusForge交互。
    """

    # 运行/连接状态文本 (供主窗口状态栏显示连接进度)
    run_state_changed = Signal(str)
    # 运行态联动 (True=运行/连接中, False=已停止) 供工具栏按钮置灰
    run_active_changed = Signal(bool)
    # 当前运行工程名 (空串=未运行) 供主窗口状态栏常驻提示
    run_project_changed = Signal(str)

    # 跨工程切换保留的系统面板 (不随工程关闭)
    _SYSTEM_PANELS = {"设备管理", "全局配置", "Log"}

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._message_bus = MessageBus.instance()
        self._var_registry = VariableRegistry.instance()

        # 设备管理委托给 DeviceManager / DataHub (按工程分区)
        self._dm = DeviceManager.instance()
        self._hub = DataHub.instance()
        self._device_panel: Optional[DeviceManagePanel] = None
        self._settings_panel: Optional[SettingsPanel] = None
        # 异步连接工作线程与运行代号 (代号用于作废切换/终止前的回调)
        self._connect_worker: Optional[ConnectWorker] = None
        self._run_gen: int = 0
        self._panel_restore_gen: int = 0

        self._ads_manager: Optional[AdsManager] = None
        self._project_tree: Optional[ProjectTree] = None
        self._log_text: Optional[QPlainTextEdit] = None
        self._log_dock = None

        self._build_ui()
        self._connect_signals()

        logger.info("BusForgeWidget 已初始化")

    # ------------------------------------------------------------------ #
    #  UI 构建
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        """构建内部UI: 左侧固定树 + 右侧ADS工作区"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ADS DockManager
        self._ads_manager = AdsManager(self)
        dock_manager = self._ads_manager.dock_manager

        if not dock_manager:
            # 回退: 简单左右分割
            splitter = QSplitter(Qt.Orientation.Horizontal)
            layout.addWidget(splitter)
            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            self._project_tree = ProjectTree()
            left_layout.addWidget(self._project_tree)
            splitter.addWidget(left)
            right = QPlainTextEdit("ADS not available")
            right.setReadOnly(True)
            splitter.addWidget(right)
            splitter.setSizes([300, 900])
            return

        # ---- 水平分割: 左侧固定树 + 右侧ADS工作区 ----
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._main_splitter)

        # 左侧固定面板 (非dock, 不可关闭/拖拽)
        self._left_panel = QWidget()
        self._left_panel.setObjectName("LeftPanel")
        self._left_panel.setStyleSheet("background-color: #e8ecf1;")
        left_layout = QVBoxLayout(self._left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._project_tree = ProjectTree()
        left_layout.addWidget(self._project_tree)

        self._main_splitter.addWidget(self._left_panel)
        self._main_splitter.setStretchFactor(0, 0)  # 左侧固定宽度

        # 右侧ADS工作区
        self._ads_container = QWidget()
        self._ads_container.setStyleSheet("background-color: #ffffff;")
        ads_layout = QVBoxLayout(self._ads_container)
        ads_layout.setContentsMargins(0, 0, 0, 0)
        ads_layout.addWidget(dock_manager)
        # 强制ADS容器背景为纯白
        dock_manager.setStyleSheet("background-color: #ffffff;")
        self._main_splitter.addWidget(self._ads_container)
        self._main_splitter.setStretchFactor(1, 1)  # 右侧自适应
        self._main_splitter.setSizes([300, 900])

        # ---- 日志面板 (ADS底部, 默认隐藏) ----
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(5000)
        self._log_text.setFont(QFont("Consolas", 11))

        self._log_dock = self._ads_manager.add_panel(
            "Log", self._log_text,
            area=self._get_bottom_area()
        )
        if self._log_dock:
            self._log_dock.closeDockWidget()

    def _connect_signals(self):
        """连接内部信号"""
        if not self._project_tree:
            return

        self._project_tree.device_manage_requested.connect(
            lambda did: self.open_device_panel(device_id=did))
        self._project_tree.channel_manage_requested.connect(
            lambda key: self.open_device_panel(channel_key=key))

        self._project_tree.panel_created.connect(self._on_panel_created)
        self._project_tree.panel_close_requested.connect(self._on_panel_close_requested)
        self._project_tree.panel_activate_requested.connect(
            self._on_panel_activate_requested)
        self._project_tree.project_switched.connect(self._on_project_switched)

    # ------------------------------------------------------------------ #
    #  公共API - 供外部平台调用
    # ------------------------------------------------------------------ #

    def get_message_bus(self) -> MessageBus:
        """获取消息总线实例"""
        return self._message_bus

    def get_variable_registry(self) -> VariableRegistry:
        """获取全局变量注册表"""
        return self._var_registry

    def get_ads_manager(self) -> Optional[AdsManager]:
        """获取ADS停靠管理器"""
        return self._ads_manager

    def tile_panels(self):
        """平铺所有面板同时显示 (CANoe 式多窗口)"""
        if self._ads_manager:
            self._ads_manager.tile_panels()

    def tabify_panels(self):
        """所有面板合并回标签切换"""
        if self._ads_manager:
            self._ads_manager.tabify_all_panels()

    def get_project_tree(self) -> Optional[ProjectTree]:
        """获取统一项目树"""
        return self._project_tree

    def create_panel(self, panel_type: str, title: str,
                     channel_key: str = "") -> object:
        """
        外部平台调用: 创建功能面板

        Args:
            panel_type: 面板类型 (trace/signal/graphy/panel/uds/script/transmit)
            title: 面板标题
            channel_key: 关联通道

        Returns:
            CDockWidget 或 None
        """
        if self._project_tree:
            self._project_tree.create_panel(panel_type, title, channel_key)
        return self._ads_manager.get_panel(title) if self._ads_manager else None

    def open_device_panel(self, device_id: str = "", channel_key: str = ""):
        """打开/聚焦统一设备管理面板 (全局单实例)"""
        if self._device_panel is None:
            self._device_panel = DeviceManagePanel()
            if self._ads_manager:
                self._ads_manager.add_panel("设备管理", self._device_panel)
            else:
                # 无ADS回退: 独立窗口显示
                self._device_panel.setWindowTitle("设备管理")
                self._device_panel.resize(1100, 600)
                self._device_panel.show()
        if self._ads_manager:
            self._ads_manager.activate_panel("设备管理")
        else:
            self._device_panel.raise_()
        if channel_key:
            self._device_panel.show_channel(channel_key)
        elif device_id:
            self._device_panel.show_device(device_id)

    def open_settings_panel(self, page: str = ""):
        """打开/聚焦全局配置面板 (全局单实例, 与设备管理一致停靠);
        page: 可选快捷跳转页 (workspace/theme/logger)"""
        if self._settings_panel is None:
            self._settings_panel = SettingsPanel(
                project_tree=self._project_tree, config=self._config)
            if self._ads_manager:
                self._ads_manager.add_panel("全局配置", self._settings_panel)
            else:
                # 无ADS回退: 独立窗口显示
                self._settings_panel.setWindowTitle("全局配置")
                self._settings_panel.resize(900, 560)
                self._settings_panel.show()
        if self._ads_manager:
            self._ads_manager.activate_panel("全局配置")
        else:
            self._settings_panel.raise_()
        if page:
            self._settings_panel.show_page(page)
        # 打开时刷新工作空间列表
        self._settings_panel.reload_workspace()

    def get_devices(self) -> dict:
        """获取已连接通道实例 (channel_key -> 设备实例)"""
        return self._dm.connected_instances()

    def run_project(self) -> bool:
        """运行工程: 异步连接当前项目引用通道 -> 连接完成后开始收数/推送"""
        if not self._project_tree:
            return False
        if self._connect_worker is not None:
            logger.info("已有连接任务进行中, 忽略重复运行")
            return False
        keys = self._project_tree.collect_project_channels()
        if not keys:
            logger.warning("当前项目没有引用软件通道, 无法运行")
            self.run_state_changed.emit("运行失败: 当前工程无引用通道")
            self.run_active_changed.emit(False)
            return False
        # 异步连接 (工作线程逐通道开硬件, UI不冻结, 上报进度)
        self._run_gen += 1
        gen = self._run_gen
        self.run_state_changed.emit(f"连接中 0/{len(keys)} ...")
        self._connect_worker = ConnectWorker(self._dm, keys)
        self._connect_worker.progress.connect(
            lambda d, t, k, g=gen: self._on_connect_progress(g, d, t, k))
        self._connect_worker.finished_ok.connect(
            lambda ok, err, g=gen, ks=keys:
                self._on_connect_finished(g, ok, err, ks))
        self._connect_worker.start()
        self.run_active_changed.emit(True)
        # 状态栏常驻提示: 哪个工程在运行
        self.run_project_changed.emit(
            self._dm.active_project_name or "未命名工程")
        return True

    def stop_project(self):
        """终止工程: 停收数/推送 + 断开本工程全部连接"""
        self._run_gen += 1
        self._cancel_connect_worker()
        self._hub.stop_polling()
        self._dm.disconnect_all_active()
        if self._project_tree:
            self._project_tree.set_running_badge(None)
        self.run_state_changed.emit("工程已终止")
        self.run_active_changed.emit(False)
        self.run_project_changed.emit("")
        logger.info("工程终止")

    def _cancel_connect_worker(self):
        """取消进行中的异步连接任务"""
        worker = self._connect_worker
        self._connect_worker = None
        if worker is not None:
            worker.cancel()

    def _on_connect_progress(self, gen: int, done: int, total: int, key: str):
        if gen != self._run_gen:
            return
        self.run_state_changed.emit(f"连接中 {done}/{total}: {key}")

    def _on_connect_finished(self, gen: int, ok: bool, err: str, keys: list):
        worker = self._connect_worker
        self._connect_worker = None
        if worker is not None:
            worker.deleteLater()
        if gen != self._run_gen:
            return  # 已切换/终止, 丢弃陈旧回调
        if not ok:
            logger.error(f"工程连接失败: {err}")
            self._dm.disconnect_all_active()
            self.run_state_changed.emit(f"运行失败: {err or '设备连接失败'}")
            self.run_active_changed.emit(False)
            self.run_project_changed.emit("")
            return
        if err:
            logger.warning(f"部分通道连接异常: {err}")
        p_ok, p_err = self._hub.begin_polling(keys)
        if p_ok:
            self._project_tree.set_running_badge(
                self._project_tree.project_manager.active_index)
            self.run_state_changed.emit("工程运行中")
            logger.info(f"工程运行: channels={keys}")
        else:
            logger.error(f"工程运行失败: {p_err}")
            self._dm.disconnect_all_active()
            self.run_state_changed.emit(f"运行失败: {p_err}")
            self.run_active_changed.emit(False)
            self.run_project_changed.emit("")

    def toggle_log(self):
        """切换日志面板显示"""
        if self._log_dock and ADS_AVAILABLE:
            self._log_dock.toggleView(self._log_dock.isClosed())

    def save_layout(self) -> bool:
        """保存布局到配置"""
        data = self._ads_manager.save_layout() if self._ads_manager else b""
        if data:
            import base64
            encoded = base64.b64encode(data).decode()
            self._config.window_geometry = {"ads_layout": encoded}
            self._config.save()
            logger.info("布局已保存")
            return True
        return False

    def restore_layout(self) -> bool:
        """从配置恢复布局"""
        if (self._config.window_geometry
                and "ads_layout" in self._config.window_geometry
                and self._ads_manager):
            import base64
            data = base64.b64decode(
                self._config.window_geometry["ads_layout"])
            if self._ads_manager.restore_layout(data):
                logger.info("布局已恢复")
                return True
        return False

    # ------------------------------------------------------------------ #
    #  内部信号处理
    # ------------------------------------------------------------------ #

    def _on_panel_created(self, panel_id: str, panel_type: str,
                          widget, channel_key: str):
        dock = self._ads_manager.add_panel(panel_id, widget)
        if dock:
            self._message_bus.register_panel(panel_id, panel_type, channel_key)
            logger.info(f"面板已创建: {panel_id} ({panel_type})")

    def _on_panel_close_requested(self, panel_id: str):
        self._ads_manager.remove_panel(panel_id)
        self._message_bus.unregister_panel(panel_id)

    def _on_panel_activate_requested(self, panel_id: str):
        """双击工程树面板实例节点 -> 激活右侧对应标签页"""
        if self._ads_manager:
            self._ads_manager.activate_panel(panel_id)

    def _on_project_switched(self, project_index: int):
        """项目切换: 停运行 + 关功能面板 + 换活动工程池(断开旧工程) + 刷新设备面板"""
        # 作废进行中的连接并停运行
        self._run_gen += 1
        self._cancel_connect_worker()
        if self._hub.running:
            self._hub.stop_polling()
            if self._project_tree:
                self._project_tree.set_running_badge(None)
        # 关闭旧工程的功能面板 (保留设备管理/日志等系统面板)
        if self._ads_manager:
            self._ads_manager.begin_panel_batch()
            try:
                for pid in self._ads_manager.list_panels():
                    if pid in self._SYSTEM_PANELS:
                        continue
                    self._ads_manager.remove_panel(pid)
                    self._message_bus.unregister_panel(pid)
            finally:
                self._ads_manager.end_panel_batch()
        # 切换 DeviceManager 活动工程池 (内部先断开旧工程连接)
        tree = self._project_tree
        if tree:
            mgr = tree.project_manager
            if 0 <= project_index < len(mgr.projects):
                proj = mgr.projects[project_index]
                self._dm.register_project(proj.project_id, proj.name)
                self._dm.set_active_project(proj.project_id, proj.name)
            else:
                self._dm.set_active_project(None)
        # 设备管理面板随工程刷新
        if self._device_panel is not None:
            self._device_panel.reload_all()
        # 恢复活动工程的面板 dock。延迟到当前 QtAds 清理信号处理完毕后执行，
        # 避免旧停靠区的 currentChanged 回调与新面板创建交错。
        if project_index >= 0 and self._project_tree:
            self._panel_restore_gen += 1
            restore_gen = self._panel_restore_gen

            def restore():
                if restore_gen == self._panel_restore_gen:
                    self._project_tree.restore_active_panels()

            QTimer.singleShot(0, restore)
        logger.info(f"已切换到项目 {project_index}")

    # ------------------------------------------------------------------ #
    #  区域常量
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_bottom_area() -> int:
        if ADS_AVAILABLE:
            import PySide6QtAds as qt_ads
            return qt_ads.BottomDockWidgetArea
        return 0

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #

    def shutdown(self):
        """关闭时清理资源"""
        self._run_gen += 1
        self._cancel_connect_worker()
        self._hub.stop_polling()
        # Logger 记录中则停止落盘, 保证文件完整
        from app.recorder.can_logger import CanLogger
        CanLogger.instance().stop()
        self._dm.shutdown()
        self.save_layout()
        logger.info("BusForgeWidget 已关闭")
