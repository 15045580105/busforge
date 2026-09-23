"""
TSMaster 连接服务 - 移植自 tosuncan/TSMasterServiceImpl 的设备连接核心

只移植"设备连接"相关逻辑, 并做优化:
- 型号通道布局改为数据驱动表(替代Java中逐型号硬编码的映射函数)
- 映射表在服务内维护, 应用通道号 <-> (设备索引, 硬件通道) 双向可查
- 所有配置类调用遵循同星要求: 断连 -> 配置 -> 重连
- 全局单例 + 线程锁, 多通道共享一个DLL应用连接

对应Java类:
- com.desaycv.tosuncan.service.impl.TSMasterServiceImpl (start/connect/autoMapping/
  setCanBaudrate/setCanFDBaudrate/setChannelEnabled)
- com.desaycv.tosuncan.jna.HardwareMapping (常量)
"""

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from app.devices.drivers.ts_jna import TsMasterLib

logger = logging.getLogger(__name__)


# ============================================================
# 同星DLL常量 (对应 HardwareMapping.java)
# ============================================================

class AppChannelType:
    """应用通道类型 (TLIBApplicationChannelType)"""
    CAN = 0
    LIN = 1
    FLEXRAY = 2
    ETHERNET = 3


class BusToolDeviceType:
    """总线工具设备类型 (TLIBBusToolDeviceType)"""
    TS_USB_DEVICE = 3


class TSDeviceSubType:
    """同星设备子型号 (TLIBTSDeviceSubType)"""
    TC1026 = 10
    TC1016 = 11
    TC1013 = 13
    TC1034 = 15


# 型号通道布局表: 型号 -> 各总线类型通道数
# 替代Java中 set_TC1013Mapping/set_TC1016Mapping/... 的硬编码逻辑
MODEL_CHANNEL_LAYOUT: dict[str, dict[str, int]] = {
    "TC1013": {"can": 2, "lin": 0, "flexray": 0},
    "TC1016": {"can": 4, "lin": 2, "flexray": 0},
    "TC1026": {"can": 0, "lin": 6, "flexray": 0},
    "TC1034": {"can": 2, "lin": 0, "flexray": 2},
}

# 型号 -> DLL设备子类型常量
MODEL_SUBTYPE: dict[str, int] = {
    "TC1013": TSDeviceSubType.TC1013,
    "TC1016": TSDeviceSubType.TC1016,
    "TC1026": TSDeviceSubType.TC1026,
    "TC1034": TSDeviceSubType.TC1034,
}


@dataclass
class ChannelMapping:
    """一条应用通道映射记录"""
    app_type: int            # 应用通道类型 (AppChannelType)
    app_index: int           # 应用通道号 (0-based, DLL用)
    device_name: str         # 硬件型号名 (如 TC1013)
    device_index: int        # 设备枚举索引
    serial: str              # 设备序列号
    hw_channel: int          # 硬件通道号 (0-based)


class TsMasterService:
    """
    同星设备连接服务 (全局单例)

    职责(仅设备连接):
    - 库初始化/释放
    - 设备枚举与识别
    - 通道计数与映射 (autoMapping 移植)
    - 应用连接/断开 (connect/disconnect)
    - 按映射通道配置波特率 (CAN/CAN FD, 含只听/终端电阻)
    - 通道使能控制
    """

    _instance: Optional['TsMasterService'] = None
    _lock = threading.RLock()

    def __new__(cls):
        """单例构造"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    @classmethod
    def instance(cls) -> 'TsMasterService':
        """获取全局唯一服务实例"""
        return cls()

    def __init__(self):
        """初始化服务内部状态 (单例, 仅首次生效)"""
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._lib = TsMasterLib()
        self._app_name = "BusForge"
        self._lib_started = False          # initialize_lib_tsmaster 是否已调用
        self._connected = False            # tsapp_connect 是否成功
        self._mappings: list[ChannelMapping] = []   # 映射表
        self._started_devices: set[tuple] = set()   # 已start的设备 (index, name, serial)

    # ------------------------------------------------------------------ #
    #  库生命周期
    # ------------------------------------------------------------------ #

    def initialize(self) -> bool:
        """初始化TSMaster库 (全局仅一次)"""
        with self._lock:
            if self._lib_started:
                return True
            try:
                self._lib.initialize(self._app_name)
                self._lib_started = True
                return True
            except Exception as e:
                logger.error(f"TSMaster库初始化失败: {e}")
                return False

    def finalize(self):
        """释放TSMaster库 (应用退出时调用)"""
        with self._lock:
            if self._connected:
                self.disconnect()
            if self._lib_started:
                self._lib.finalize()
                self._lib_started = False

    # ------------------------------------------------------------------ #
    #  设备枚举
    # ------------------------------------------------------------------ #

    def enumerate_devices(self) -> list[dict]:
        """枚举当前物理连接的同星硬件设备"""
        with self._lock:
            if not self.initialize():
                return []
            count = self._lib.enumerate_hw_devices()
            devices = []
            for i in range(count):
                info = self._lib.get_hw_info_by_index(i)
                if info:
                    info['enum_index'] = i
                    devices.append(info)
            return devices

    def get_device_count(self) -> int:
        """获取枚举到的设备数量"""
        return len(self.enumerate_devices())

    # ------------------------------------------------------------------ #
    #  连接核心 (start/autoMapping/connect 移植)
    # ------------------------------------------------------------------ #

    def start(self, device_name: str, device_index: int,
              serial: str = "") -> tuple[bool, str]:
        """
        启动指定设备 (对应Java start + autoMapping)

        流程: 已连接则先断连 -> 初始化库 -> 重建映射 -> 恢复连接
        """
        with self._lock:
            was_connected = self._connected
            try:
                if was_connected:
                    self.disconnect()
                if not self.initialize():
                    return False, "TSMaster库初始化失败"
                ok, err = self._auto_mapping(device_name, device_index, serial)
                if not ok:
                    return False, err
                self._started_devices.add(
                    (device_index, device_name, serial))
                if was_connected:
                    self.connect()
                return True, ""
            except Exception as e:
                logger.error(f"start异常: {e}")
                if was_connected and not self._connected:
                    self.connect()
                return False, str(e)

    def _auto_mapping(self, device_name: str, device_index: int,
                      serial: str) -> tuple[bool, str]:
        """
        自动通道映射 (对应Java autoMapping, 数据驱动优化版)

        1. 枚举设备, 校验目标型号存在
        2. 统计已启用设备的总通道数, 下发通道计数
        3. 按型号布局表逐通道建立 应用通道<->硬件通道 映射
        """
        devices = self.enumerate_devices()
        if device_name and not any(
                d['device_name'] == device_name for d in devices):
            return False, f"设备不存在: {device_name}"

        # 统计总通道数 (所有已启用设备 + 本次目标设备)
        enabled = list(self._started_devices)
        key = (device_index, device_name, serial)
        if key not in enabled:
            enabled.append(key)

        total = {"can": 0, "lin": 0, "flexray": 0}
        for (_, name, _) in enabled:
            layout = MODEL_CHANNEL_LAYOUT.get(name)
            if not layout:
                continue
            for bus in total:
                total[bus] += layout.get(bus, 0)

        if len(devices) > 1 or total["can"] > 0:
            rc = self._lib.set_can_channel_count(max(1, total["can"]))
            if rc != 0:
                return False, self._err("tsapp_set_can_channel_count", rc)
            rc = self._lib.set_lin_channel_count(total["lin"])
            if rc != 0:
                return False, self._err("tsapp_set_lin_channel_count", rc)

        # 建立映射: 同型号多台设备按出现顺序分配 hw_index
        self._mappings = [m for m in self._mappings
                          if (m.device_index, m.device_name, m.serial)
                          not in enabled]
        app_can = 0
        app_lin = 0
        occurrence: dict[str, int] = {}
        for (dev_idx, name, ser) in enabled:
            layout = MODEL_CHANNEL_LAYOUT.get(name)
            if not layout:
                continue
            hw_idx = occurrence.get(name, 0)
            occurrence[name] = hw_idx + 1
            subtype = MODEL_SUBTYPE.get(name, 0)
            for ch in range(layout.get("can", 0)):
                rc = self._lib.set_mapping_verbose(
                    self._app_name, AppChannelType.CAN, app_can,
                    name, BusToolDeviceType.TS_USB_DEVICE, subtype,
                    hw_idx, ch, True)
                if rc != 0:
                    return False, self._err("tsapp_set_mapping_verbose", rc)
                self._mappings.append(ChannelMapping(
                    AppChannelType.CAN, app_can, name, dev_idx, ser, ch))
                app_can += 1
            for ch in range(layout.get("lin", 0)):
                rc = self._lib.set_mapping_verbose(
                    self._app_name, AppChannelType.LIN, app_lin,
                    name, BusToolDeviceType.TS_USB_DEVICE, subtype,
                    hw_idx, ch, True)
                if rc != 0:
                    return False, self._err("tsapp_set_mapping_verbose", rc)
                self._mappings.append(ChannelMapping(
                    AppChannelType.LIN, app_lin, name, dev_idx, ser, ch))
                app_lin += 1
        return True, ""

    def connect(self) -> tuple[bool, str]:
        """连接应用 (tsapp_connect), 已连接直接返回成功"""
        with self._lock:
            if self._connected:
                return True, ""
            rc = self._lib.connect()
            if rc != 0:
                return False, self._err("tsapp_connect", rc)
            self._lib.enable_receive_fifo()
            self._connected = True
            logger.info("TSMaster应用已连接")
            return True, ""

    def disconnect(self) -> bool:
        """断开应用连接 (tsapp_disconnect)"""
        with self._lock:
            if not self._connected:
                return True
            self._lib.disconnect()
            self._connected = False
            logger.info("TSMaster应用已断开")
            return True

    @property
    def connected(self) -> bool:
        """当前应用连接状态"""
        return self._connected

    @property
    def lib(self) -> TsMasterLib:
        """底层DLL封装库实例 (供设备驱动收发使用)"""
        return self._lib

    # ------------------------------------------------------------------ #
    #  映射查询
    # ------------------------------------------------------------------ #

    def get_app_channel(self, device_index: int, hw_channel: int,
                        app_type: int = AppChannelType.CAN) -> Optional[int]:
        """
        查询 应用通道号 (对应Java getTsDeviceChannelMapping)

        未建立映射时回退为硬件通道号(单设备场景)
        """
        for m in self._mappings:
            if (m.app_type == app_type and m.device_index == device_index
                    and m.hw_channel == hw_channel):
                return m.app_index
        return hw_channel if app_type == AppChannelType.CAN else None

    def get_mappings(self) -> list[ChannelMapping]:
        """获取当前映射表副本"""
        return list(self._mappings)

    @staticmethod
    def get_channel_count_by_model(model: str, bus: str = "can") -> int:
        """查询型号的通道数量 (对应Java getChannelCountByDeviceName)"""
        return MODEL_CHANNEL_LAYOUT.get(model, {}).get(bus, 0)

    # ------------------------------------------------------------------ #
    #  通道配置 (断连-配置-重连)
    # ------------------------------------------------------------------ #

    def set_can_baudrate(self, device_index: int, hw_channel: int,
                         baudrate_kbps: float, listen_only: bool = False,
                         term_resistor: bool = False) -> tuple[bool, str]:
        """配置CAN通道波特率 (对应Java setCanBaudrate)"""
        with self._lock:
            app_ch = self.get_app_channel(device_index, hw_channel)
            if app_ch is None:
                return False, "通道映射不存在"
            was_connected = self._connected
            try:
                if was_connected:
                    self.disconnect()
                rc = self._lib.configure_baudrate_can(
                    app_ch, baudrate_kbps, listen_only, term_resistor)
                if rc != 0:
                    return False, self._err(
                        "tsapp_configure_baudrate_can", rc)
                return True, ""
            finally:
                if was_connected:
                    self.connect()

    def set_canfd_baudrate(self, device_index: int, hw_channel: int,
                           arb_kbps: float, data_kbps: float,
                           controller_type: int = 0, controller_mode: int = 0,
                           term_resistor: bool = False) -> tuple[bool, str]:
        """配置CAN FD通道波特率 (对应Java setCanFDBaudrate)"""
        with self._lock:
            app_ch = self.get_app_channel(device_index, hw_channel)
            if app_ch is None:
                return False, "通道映射不存在"
            was_connected = self._connected
            try:
                if was_connected:
                    self.disconnect()
                rc = self._lib.configure_baudrate_canfd(
                    app_ch, arb_kbps, data_kbps,
                    controller_type, controller_mode, term_resistor)
                if rc != 0:
                    return False, self._err(
                        "tsapp_configure_baudrate_canfd", rc)
                return True, ""
            finally:
                if was_connected:
                    self.connect()

    def set_channel_enabled(self, device_index: int, hw_channel: int,
                            enable: bool,
                            app_type: int = AppChannelType.CAN) -> tuple[bool, str]:
        """通道使能控制 (对应Java setChannelEnabled)"""
        with self._lock:
            mapping = None
            for m in self._mappings:
                if (m.app_type == app_type and m.device_index == device_index
                        and m.hw_channel == hw_channel):
                    mapping = m
                    break
            if not mapping:
                return False, "通道映射不存在"
            was_connected = self._connected
            try:
                if was_connected:
                    self.disconnect()
                rc = self._lib.set_mapping_verbose(
                    self._app_name, mapping.app_type, mapping.app_index,
                    mapping.device_name, BusToolDeviceType.TS_USB_DEVICE,
                    MODEL_SUBTYPE.get(mapping.device_name, 0),
                    mapping.device_index, mapping.hw_channel, enable)
                if rc != 0:
                    return False, self._err("tsapp_set_mapping_verbose", rc)
                return True, ""
            finally:
                if was_connected:
                    self.connect()

    def clear_buffer(self, device_index: int, hw_channel: int) -> bool:
        """清除指定通道的接收缓存"""
        app_ch = self.get_app_channel(device_index, hw_channel)
        if app_ch is None:
            return False
        self._lib.clear_can_receive_buffers(app_ch)
        return True

    # ------------------------------------------------------------------ #
    #  LIN 通道
    # ------------------------------------------------------------------ #

    def start_lin_channel(self, device_index: int, hw_channel: int,
                          baud_kbps: float = 19.2) -> tuple[bool, str]:
        """配置并启动LIN通道 (对应Java startLinChannel 精简版)"""
        with self._lock:
            app_ch = self.get_app_channel(
                device_index, hw_channel, AppChannelType.LIN)
            if app_ch is None:
                return False, "LIN通道映射不存在"
            rc = self._lib.configure_baudrate_lin(app_ch, baud_kbps, 0)
            if rc != 0:
                return False, self._err("tsapp_configure_baudrate_lin", rc)
            rc = self._lib.start_lin_channel(app_ch)
            if rc != 0:
                return False, self._err("tslin_start_lin_channel", rc)
            return True, ""

    def stop_lin_channel(self, device_index: int, hw_channel: int) -> bool:
        """停止LIN通道"""
        app_ch = self.get_app_channel(
            device_index, hw_channel, AppChannelType.LIN)
        if app_ch is None:
            return False
        return self._lib.stop_lin_channel(app_ch) == 0

    # ------------------------------------------------------------------ #
    #  内部工具
    # ------------------------------------------------------------------ #

    def _err(self, func_name: str, code: int) -> str:
        """格式化DLL错误信息"""
        try:
            desc = self._lib.get_error_description(code)
        except Exception:
            desc = str(code)
        msg = f"{func_name} 失败: {desc}"
        logger.error(msg)
        return msg
