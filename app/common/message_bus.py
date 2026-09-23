"""
内部消息总线 - 面板间控制信令

基于Qt Signal/Slot机制，实现:
- 面板间控制信令: 面板创建/关闭请求
- 设备状态变化通知(已迁移至 DeviceManager.device_state_changed)
- 变量变化通知

注意: 帧数据/DBC/统计不再经由此总线, 统一由 DataHub 按订阅推送。
"""

import logging
from typing import Optional
from PySide6.QtCore import QObject, Signal, QTimer

logger = logging.getLogger(__name__)


class MessageBus(QObject):
    """
    全局消息总线 (仅控制信令)

    单例模式，所有面板通过消息总线通信。
    使用Qt Signal/Slot确保线程安全。
    """

    # 面板请求创建: panel_type, config_dict
    panel_create_requested = Signal(str, dict)

    # 面板关闭请求: panel_id
    panel_close_requested = Signal(str)

    # 变量变化通知(从VariableSystem转发): var_name, old_value, new_value
    variable_changed = Signal(str, object, object)

    _instance: Optional['MessageBus'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> 'MessageBus':
        if cls._instance is None:
            cls._instance = MessageBus()
        return cls._instance

    def __init__(self, parent=None):
        if hasattr(self, '_initialized'):
            return
        super().__init__(parent)
        self._initialized = True
        # 通道 -> 关联的面板ID列表
        self._channel_panels: dict[str, list[str]] = {}
        # 面板ID -> 面板类型
        self._panel_types: dict[str, str] = {}
        # 面板ID -> 关联的通道key
        self._panel_channels: dict[str, str] = {}

    def register_panel(self, panel_id: str, panel_type: str, channel_key: str = ""):
        """注册面板到消息总线"""
        self._panel_types[panel_id] = panel_type
        if channel_key:
            self._panel_channels[panel_id] = channel_key
            if channel_key not in self._channel_panels:
                self._channel_panels[channel_key] = []
            if panel_id not in self._channel_panels[channel_key]:
                self._channel_panels[channel_key].append(panel_id)
        logger.debug(f"面板注册: {panel_id} ({panel_type}) -> channel={channel_key}")

    def unregister_panel(self, panel_id: str):
        """从消息总线注销面板"""
        channel_key = self._panel_channels.pop(panel_id, "")
        if channel_key and channel_key in self._channel_panels:
            panels = self._channel_panels[channel_key]
            if panel_id in panels:
                panels.remove(panel_id)
        self._panel_types.pop(panel_id, None)
        logger.debug(f"面板注销: {panel_id}")

    def get_panels_for_channel(self, channel_key: str) -> list[str]:
        """获取通道关联的所有面板ID"""
        return self._channel_panels.get(channel_key, [])

    def get_panels_by_type(self, panel_type: str) -> list[str]:
        """获取指定类型的所有面板ID"""
        return [pid for pid, pt in self._panel_types.items() if pt == panel_type]

    def get_panel_type(self, panel_id: str) -> str:
        return self._panel_types.get(panel_id, "")
