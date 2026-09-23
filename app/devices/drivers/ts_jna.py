"""
TSMaster DLL ctypes绑定

对应 tosuncan/jna/TsMaster_jna.java 的Python ctypes实现。
通过ctypes直接调用tsMaster.dll，不依赖任何后端。

DLL路径获取顺序:
1. 环境变量 TSMaster_HOME
2. 注册表 HKEY_CURRENT_USER\\Software\\TOSUN\\TSMaster
3. 默认路径 C:\\Program Files\\TSMaster\\
"""

import os
import sys
import ctypes
import logging
from ctypes import (
    c_int, c_float, c_bool, c_char_p, c_void_p,
    POINTER, byref, WinDLL
)
from typing import Optional

from app.devices.drivers.ts_structures import (
    TLIBCAN, TLIBCANFD, TLIBHWInfo,
    hw_info_to_dict, can_to_dict, canfd_to_dict,
    TCCANFDControllerType, TCCANFDControllerMode
)

logger = logging.getLogger(__name__)

# 回调函数类型
TCANQueueEvent_Win32 = ctypes.CFUNCTYPE(None, c_void_p, POINTER(TLIBCAN))
TCANFDQueueEvent_Win32 = ctypes.CFUNCTYPE(None, c_void_p, POINTER(TLIBCANFD))


def find_tsmaster_dll() -> Optional[str]:
    """查找TSMaster DLL路径"""
    # 1. 环境变量
    home = os.environ.get('TSMaster_HOME')
    if home:
        dll_path = os.path.join(home, 'tsMaster.dll')
        if os.path.exists(dll_path):
            return dll_path

    # 2. 注册表
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\TOSUN\TSMaster"
        )
        install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
        winreg.CloseKey(key)
        dll_path = os.path.join(install_dir, 'tsMaster.dll')
        if os.path.exists(dll_path):
            return dll_path
    except Exception:
        pass

    # 3. 默认路径
    default_paths = [
        r"C:\Program Files\TSMaster\tsMaster.dll",
        r"C:\Program Files (x86)\TSMaster\tsMaster.dll",
        r"D:\TSMaster\tsMaster.dll",
    ]
    for p in default_paths:
        if os.path.exists(p):
            return p

    return None


class TsMasterLib:
    """
    TSMaster DLL封装库

    对应 TsMaster_jna.java 中的所有函数绑定。
    """

    def __init__(self, dll_path: Optional[str] = None):
        self._dll_path = dll_path or find_tsmaster_dll()
        self._dll = None
        self._initialized = False
        # 保持回调引用(防止GC)
        self._can_callback = None
        self._canfd_callback = None

    def _load_dll(self):
        """加载DLL"""
        if self._dll:
            return
        if not self._dll_path:
            raise FileNotFoundError(
                "找不到tsMaster.dll，请安装TSMaster或设置TSMaster_HOME环境变量"
            )
        logger.info(f"加载TSMaster DLL: {self._dll_path}")
        self._dll = WinDLL(self._dll_path)
        self._setup_functions()

    def _setup_functions(self):
        """设置函数原型(restype/argtypes)"""
        dll = self._dll

        # initialize_lib_tsmaster
        dll.initialize_lib_tsmaster.restype = None
        dll.initialize_lib_tsmaster.argtypes = [c_char_p]

        # finalize_lib_tsmaster
        dll.finalize_lib_tsmaster.restype = None
        dll.finalize_lib_tsmaster.argtypes = []

        # tsapp_connect
        dll.tsapp_connect.restype = c_int
        dll.tsapp_connect.argtypes = []

        # tsapp_disconnect
        dll.tsapp_disconnect.restype = c_int
        dll.tsapp_disconnect.argtypes = []

        # tsapp_enumerate_hw_devices
        dll.tsapp_enumerate_hw_devices.restype = c_int
        dll.tsapp_enumerate_hw_devices.argtypes = [POINTER(c_int)]

        # tsapp_get_hw_info_by_index
        dll.tsapp_get_hw_info_by_index.restype = c_int
        dll.tsapp_get_hw_info_by_index.argtypes = [c_int, POINTER(TLIBHWInfo)]

        # tsapp_configure_baudrate_can
        dll.tsapp_configure_baudrate_can.restype = c_int
        dll.tsapp_configure_baudrate_can.argtypes = [c_int, c_float, c_int, c_bool]

        # tsapp_configure_baudrate_canfd
        dll.tsapp_configure_baudrate_canfd.restype = c_int
        dll.tsapp_configure_baudrate_canfd.argtypes = [
            c_int, c_float, c_float, c_int, c_int, c_bool
        ]

        # tsapp_transmit_can_async
        dll.tsapp_transmit_can_async.restype = c_int
        dll.tsapp_transmit_can_async.argtypes = [TLIBCAN]

        # tsapp_transmit_can_sync
        dll.tsapp_transmit_can_sync.restype = c_int
        dll.tsapp_transmit_can_sync.argtypes = [TLIBCAN, c_int]

        # tsapp_transmit_canfd_async
        dll.tsapp_transmit_canfd_async.restype = c_int
        dll.tsapp_transmit_canfd_async.argtypes = [TLIBCANFD]

        # FIFO接收相关
        dll.tsfifo_enable_receive_fifo.restype = c_int
        dll.tsfifo_enable_receive_fifo.argtypes = []

        dll.tsfifo_disable_receive_fifo.restype = c_int
        dll.tsfifo_disable_receive_fifo.argtypes = []

        dll.tsfifo_clear_can_receive_buffers.restype = c_int
        dll.tsfifo_clear_can_receive_buffers.argtypes = [c_int]

        dll.tsfifo_read_can_buffer_frame_count.restype = c_int
        dll.tsfifo_read_can_buffer_frame_count.argtypes = [c_int, POINTER(c_int)]

        # tsfifo_receive_can_msgs: (TLIBCAN[], int*, int, int)
        dll.tsfifo_receive_can_msgs.restype = c_int
        dll.tsfifo_receive_can_msgs.argtypes = [
            POINTER(TLIBCAN), POINTER(c_int), c_int, c_int
        ]

        dll.tsfifo_clear_canfd_receive_buffers.restype = c_int
        dll.tsfifo_clear_canfd_receive_buffers.argtypes = [c_int]

        dll.tsfifo_read_canfd_buffer_frame_count.restype = c_int
        dll.tsfifo_read_canfd_buffer_frame_count.argtypes = [c_int, POINTER(c_int)]

        dll.tsfifo_receive_canfd_msgs.restype = c_int
        dll.tsfifo_receive_canfd_msgs.argtypes = [
            POINTER(TLIBCANFD), POINTER(c_int), c_int, c_int
        ]

        # 回调注册
        dll.tsapp_register_event_can.restype = c_int
        dll.tsapp_register_event_can.argtypes = [c_void_p, TCANQueueEvent_Win32]

        dll.tsapp_unregister_event_can.restype = c_int
        dll.tsapp_unregister_event_can.argtypes = [c_void_p, TCANQueueEvent_Win32]

        dll.tsapp_register_event_canfd.restype = c_int
        dll.tsapp_register_event_canfd.argtypes = [c_void_p, TCANFDQueueEvent_Win32]

        dll.tsapp_unregister_event_canfd.restype = c_int
        dll.tsapp_unregister_event_canfd.argtypes = [c_void_p, TCANFDQueueEvent_Win32]

        # 通道数量设置
        dll.tsapp_set_can_channel_count.restype = c_int
        dll.tsapp_set_can_channel_count.argtypes = [c_int]

        dll.tsapp_set_lin_channel_count.restype = c_int
        dll.tsapp_set_lin_channel_count.argtypes = [c_int]

        # 通道映射(纯参数版, 对应Java tsapp_set_mapping_verbose)
        dll.tsapp_set_mapping_verbose.restype = c_int
        dll.tsapp_set_mapping_verbose.argtypes = [
            c_char_p, c_int, c_int, c_char_p, c_int, c_int, c_int, c_int, c_bool
        ]

        # LIN波特率/启停
        dll.tsapp_configure_baudrate_lin.restype = c_int
        dll.tsapp_configure_baudrate_lin.argtypes = [c_int, c_float, c_int]

        dll.tslin_start_lin_channel.restype = c_int
        dll.tslin_start_lin_channel.argtypes = [c_int]

        dll.tslin_stop_lin_channel.restype = c_int
        dll.tslin_stop_lin_channel.argtypes = [c_int]

        # 错误码描述
        dll.tsapp_get_error_description.restype = c_int
        dll.tsapp_get_error_description.argtypes = [c_int, POINTER(c_char_p)]

        # 映射窗口
        dll.tsapp_show_channel_mapping_window.restype = c_int
        dll.tsapp_show_channel_mapping_window.argtypes = []

        dll.tsapp_show_hardware_configuration_window.restype = c_int
        dll.tsapp_show_hardware_configuration_window.argtypes = []

    # ---- 公共API ----

    def initialize(self, app_name: str = "BusForge"):
        """初始化TSMaster库"""
        self._load_dll()
        self._dll.initialize_lib_tsmaster(app_name.encode('utf-8'))
        self._initialized = True
        logger.info("TSMaster库初始化成功")

    def finalize(self):
        """释放TSMaster库"""
        if self._dll and self._initialized:
            self._dll.finalize_lib_tsmaster()
            self._initialized = False
            logger.info("TSMaster库已释放")

    def connect(self) -> int:
        """连接应用"""
        self._load_dll()
        result = self._dll.tsapp_connect()
        logger.debug(f"tsapp_connect -> {result}")
        return result

    def disconnect(self) -> int:
        """断开应用"""
        result = self._dll.tsapp_disconnect()
        logger.debug(f"tsapp_disconnect -> {result}")
        return result

    def enumerate_hw_devices(self) -> int:
        """枚举硬件设备，返回设备数量"""
        self._load_dll()
        count = c_int(0)
        result = self._dll.tsapp_enumerate_hw_devices(byref(count))
        if result != 0:
            logger.error(f"枚举设备失败, 错误码: {result}")
            return 0
        logger.info(f"枚举到 {count.value} 个TSMaster设备")
        return count.value

    def get_hw_info_by_index(self, index: int) -> Optional[dict]:
        """获取指定索引的硬件信息"""
        self._load_dll()
        hw_info = TLIBHWInfo()
        result = self._dll.tsapp_get_hw_info_by_index(index, byref(hw_info))
        if result != 0:
            return None
        return hw_info_to_dict(hw_info)

    def configure_baudrate_can(self, channel: int, baudrate_kbps: float,
                                listen_only: bool = False,
                                term_resistor: bool = False) -> int:
        """配置CAN通道波特率"""
        self._load_dll()
        result = self._dll.tsapp_configure_baudrate_can(
            channel, c_float(baudrate_kbps),
            1 if listen_only else 0,
            term_resistor
        )
        logger.debug(f"configure_baudrate_can(CH{channel}, {baudrate_kbps}kbps) -> {result}")
        return result

    def configure_baudrate_canfd(self, channel: int, arb_kbps: float,
                                  data_kbps: float,
                                  controller_type: int = TCCANFDControllerType.CANFD_LFDTISOCAN,
                                  controller_mode: int = TCCANFDControllerMode.CANFD_LFDMNORMAL,
                                  term_resistor: bool = False) -> int:
        """配置CAN FD通道波特率"""
        self._load_dll()
        result = self._dll.tsapp_configure_baudrate_canfd(
            channel, c_float(arb_kbps), c_float(data_kbps),
            controller_type, controller_mode,
            term_resistor
        )
        logger.debug(f"configure_baudrate_canfd(CH{channel}, {arb_kbps}/{data_kbps}kbps) -> {result}")
        return result

    def transmit_can_async(self, can: TLIBCAN) -> int:
        """异步发送CAN帧"""
        result = self._dll.tsapp_transmit_can_async(can)
        return result

    def transmit_can_sync(self, can: TLIBCAN, timeout_ms: int = 1000) -> int:
        """同步发送CAN帧"""
        result = self._dll.tsapp_transmit_can_sync(can, timeout_ms)
        return result

    def transmit_canfd_async(self, canfd: TLIBCANFD) -> int:
        """异步发送CAN FD帧"""
        result = self._dll.tsapp_transmit_canfd_async(canfd)
        return result

    def enable_receive_fifo(self):
        """启用接收FIFO"""
        self._dll.tsfifo_enable_receive_fifo()

    def disable_receive_fifo(self):
        """禁用接收FIFO"""
        self._dll.tsfifo_disable_receive_fifo()

    def clear_can_receive_buffers(self, channel: int) -> int:
        """清除CAN接收缓存"""
        return self._dll.tsfifo_clear_can_receive_buffers(channel)

    def read_can_buffer_frame_count(self, channel: int) -> int:
        """读取CAN接收缓冲区帧数量"""
        count = c_int(0)
        result = self._dll.tsfifo_read_can_buffer_frame_count(channel, byref(count))
        if result != 0:
            return 0
        return count.value

    def receive_can_msgs(self, channel: int, max_count: int = 100,
                          include_tx: bool = True) -> list[dict]:
        """读取CAN帧(FIFO)"""
        if max_count <= 0:
            return []

        buf = (TLIBCAN * max_count)()
        buf_size = c_int(max_count)
        result = self._dll.tsfifo_receive_can_msgs(
            buf, byref(buf_size), channel, 1 if include_tx else 0
        )
        if result != 0:
            return []

        frames = []
        actual_count = buf_size.value
        for i in range(actual_count):
            frames.append(can_to_dict(buf[i]))
        return frames

    def read_canfd_buffer_frame_count(self, channel: int) -> int:
        """读取CAN FD接收缓冲区帧数量"""
        count = c_int(0)
        result = self._dll.tsfifo_read_canfd_buffer_frame_count(channel, byref(count))
        if result != 0:
            return 0
        return count.value

    def receive_canfd_msgs(self, channel: int, max_count: int = 100,
                            include_tx: bool = True) -> list[dict]:
        """读取CAN FD帧(FIFO)"""
        if max_count <= 0:
            return []

        buf = (TLIBCANFD * max_count)()
        buf_size = c_int(max_count)
        result = self._dll.tsfifo_receive_canfd_msgs(
            buf, byref(buf_size), channel, 1 if include_tx else 0
        )
        if result != 0:
            return []

        frames = []
        for i in range(buf_size.value):
            frames.append(canfd_to_dict(buf[i]))
        return frames

    def set_can_channel_count(self, count: int) -> int:
        """设置CAN通道数量"""
        return self._dll.tsapp_set_can_channel_count(count)

    def set_lin_channel_count(self, count: int) -> int:
        """设置LIN通道数量"""
        return self._dll.tsapp_set_lin_channel_count(count)

    def set_mapping_verbose(self, app_name: str, app_ch_type: int,
                            app_ch_index: int, hw_device_name: str,
                            hw_device_type: int, hw_device_subtype: int,
                            hw_index: int, hw_ch_index: int,
                            enable: bool = True) -> int:
        """设置应用通道到硬件通道的映射"""
        return self._dll.tsapp_set_mapping_verbose(
            app_name.encode('utf-8'), app_ch_type, app_ch_index,
            hw_device_name.encode('utf-8'), hw_device_type,
            hw_device_subtype, hw_index, hw_ch_index, enable)

    def configure_baudrate_lin(self, channel: int, baudrate_kbps: float,
                               protocol: int = 0) -> int:
        """配置LIN通道波特率"""
        return self._dll.tsapp_configure_baudrate_lin(
            channel, c_float(baudrate_kbps), protocol)

    def start_lin_channel(self, channel: int) -> int:
        """启动LIN通道"""
        return self._dll.tslin_start_lin_channel(channel)

    def stop_lin_channel(self, channel: int) -> int:
        """停止LIN通道"""
        return self._dll.tslin_stop_lin_channel(channel)

    def get_error_description(self, code: int) -> str:
        """获取DLL错误码的文本描述"""
        desc = c_char_p()
        if self._dll.tsapp_get_error_description(code, byref(desc)) == 0 and desc.value:
            return desc.value.decode('utf-8', errors='replace')
        return f"错误码{code}"

    def register_can_event(self, callback) -> int:
        """注册CAN接收回调"""
        self._can_callback = TCANQueueEvent_Win32(callback)
        return self._dll.tsapp_register_event_can(None, self._can_callback)

    def unregister_can_event(self) -> int:
        """注销CAN接收回调"""
        if self._can_callback:
            result = self._dll.tsapp_unregister_event_can(None, self._can_callback)
            self._can_callback = None
            return result
        return 0

    def register_canfd_event(self, callback) -> int:
        """注册CAN FD接收回调"""
        self._canfd_callback = TCANFDQueueEvent_Win32(callback)
        return self._dll.tsapp_register_event_canfd(None, self._canfd_callback)

    def show_channel_mapping_window(self) -> int:
        """显示通道映射窗口"""
        return self._dll.tsapp_show_channel_mapping_window()

    def show_hardware_configuration_window(self) -> int:
        """显示硬件配置窗口"""
        return self._dll.tsapp_show_hardware_configuration_window()
