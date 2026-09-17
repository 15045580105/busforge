"""总线设备抽象基类 - 所有硬件设备通过ctypes直接调用DLL"""

import time
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass
from collections.abc import Iterator

logger = logging.getLogger(__name__)


class BusState(Enum):
    """总线状态"""
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class BusStats:
    """总线统计"""
    tx_count: int = 0
    rx_count: int = 0
    error_count: int = 0
    bus_load: float = 0.0             # 总线负载(%)
    last_rx_time: float = 0.0
    last_tx_time: float = 0.0


class BaseBusDevice(ABC):
    """
    总线设备抽象基类

    所有硬件设备(Vector/ZLG/TSMaster等)通过ctypes直接调用各自DLL，
    不依赖任何后端服务。
    """

    # 本机发送是否自回显到接收路径 (虚拟总线环回=True);
    # False 时由 DeviceManager.send 成功后向中台补发 TX 回显帧
    tx_self_echo = False

    def __init__(self, channel: int = 1):
        self.channel = channel
        self._state = BusState.DISCONNECTED
        self._stats = BusStats()
        self._rx_callbacks: list[Callable] = []
        self._baud_rate: int = 500000
        self._is_fd: bool = False
        self._data_baud_rate: int = 2000000

    @property
    def state(self) -> BusState:
        return self._state

    @property
    def stats(self) -> BusStats:
        return self._stats

    @property
    def is_connected(self) -> bool:
        return self._state in (BusState.CONNECTED, BusState.RUNNING)

    @property
    def device_name(self) -> str:
        """设备名称(子类覆盖)"""
        return self.__class__.__name__

    # ---- 生命周期 ----

    @abstractmethod
    def open(self) -> bool:
        """打开设备连接"""
        ...

    @abstractmethod
    def close(self) -> bool:
        """关闭设备连接"""
        ...

    @abstractmethod
    def start(self) -> bool:
        """启动总线通信"""
        ...

    @abstractmethod
    def stop(self) -> bool:
        """停止总线通信"""
        ...

    # ---- 收发 ----

    @abstractmethod
    def send(self, msg_id: int, data: bytes, is_extended: bool = False,
             is_fd: bool = False, is_remote: bool = False,
             is_brs: bool = False) -> bool:
        """发送CAN帧 (is_remote 仅经典CAN有效, is_brs 仅CAN FD有效)"""
        ...

    @abstractmethod
    def receive(self, timeout: float = 0.1) -> Optional[dict]:
        """
        接收一帧CAN数据

        返回: dict包含 {id, data, is_extended, is_fd, channel, timestamp} 或 None
        """
        ...

    def receive_batch(self, max_count: int = 100, timeout: float = 0.01) -> list[dict]:
        """批量接收(默认实现为循环单次接收)"""
        frames = []
        deadline = time.time() + timeout
        while len(frames) < max_count and time.time() < deadline:
            frame = self.receive(timeout=0.001)
            if frame:
                frames.append(frame)
            elif frames:
                break
        return frames

    # ---- 配置 ----

    def set_baud_rate(self, baud_rate: int):
        """设置波特率"""
        self._baud_rate = baud_rate

    def set_can_fd(self, enabled: bool, data_baud_rate: int = 2000000):
        """设置CAN FD"""
        self._is_fd = enabled
        self._data_baud_rate = data_baud_rate

    # ---- 回调 ----

    def on_receive(self, callback: Callable):
        """注册接收回调"""
        self._rx_callbacks.append(callback)

    def remove_callback(self, callback: Callable):
        """移除接收回调"""
        if callback in self._rx_callbacks:
            self._rx_callbacks.remove(callback)

    def _notify_receive(self, frame: dict):
        """通知接收回调"""
        self._stats.rx_count += 1
        self._stats.last_rx_time = time.time()
        for cb in self._rx_callbacks:
            try:
                cb(frame)
            except Exception as e:
                logger.error(f"接收回调异常: {e}")

    # ---- 上下文管理 ----

    def __enter__(self):
        self.open()
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
        self.close()
