"""虚拟总线设备 - 用于无硬件环境下的测试和开发"""

import time
import queue
import threading
import logging
from typing import Optional

from app.bus.base import BaseBusDevice, BusState

logger = logging.getLogger(__name__)


class VirtualBusDevice(BaseBusDevice):
    """
    虚拟CAN总线设备

    提供环回测试功能，无需实际硬件即可开发和调试。
    支持注入报文和模拟信号。
    """

    # 全局共享总线(同一虚拟总线上的设备可以互相收发)
    _shared_bus: dict[int, list["VirtualBusDevice"]] = {}
    _lock = threading.Lock()

    # 发送经环回自回显到本设备接收队列 (标记 direction=TX),
    # DeviceManager 无需再补发 TX 回显
    tx_self_echo = True

    def __init__(self, channel: int = 1, bus_name: str = "default"):
        super().__init__(channel)
        self.bus_name = bus_name
        self._rx_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._running = False
        self._loopback_enabled = True

    @property
    def device_name(self) -> str:
        return f"VirtualCAN({self.bus_name}/CH{self.channel})"

    def open(self) -> bool:
        with self._lock:
            if self.bus_name not in self._shared_bus:
                self._shared_bus[self.bus_name] = []
            self._shared_bus[self.bus_name].append(self)
        self._state = BusState.CONNECTED
        logger.info(f"虚拟总线设备已打开: {self.device_name}")
        return True

    def close(self) -> bool:
        self._running = False
        with self._lock:
            if self.bus_name in self._shared_bus:
                devices = self._shared_bus[self.bus_name]
                if self in devices:
                    devices.remove(self)
        self._state = BusState.DISCONNECTED
        logger.info(f"虚拟总线设备已关闭: {self.device_name}")
        return True

    def start(self) -> bool:
        self._running = True
        self._state = BusState.RUNNING
        logger.info(f"虚拟总线已启动: {self.device_name}")
        return True

    def stop(self) -> bool:
        self._running = False
        self._state = BusState.CONNECTED
        logger.info(f"虚拟总线已停止: {self.device_name}")
        return True

    def send(self, msg_id: int, data: bytes, is_extended: bool = False,
             is_fd: bool = False, is_remote: bool = False,
             is_brs: bool = False) -> bool:
        """发送帧 - 广播到同一虚拟总线上的其他设备"""
        if not self._running:
            return False

        frame = {
            "id": msg_id,
            "data": bytes(data),
            "dlc": len(data),
            "is_extended": is_extended,
            "is_fd": is_fd,
            "is_remote": is_remote,
            "is_brs": is_brs,
            "channel": self.channel,
            "timestamp": time.time(),
        }

        self._stats.tx_count += 1
        self._stats.last_tx_time = time.time()

        # 广播到同总线的其他设备
        with self._lock:
            devices = self._shared_bus.get(self.bus_name, [])
            for device in devices:
                if device is not self and device._running:
                    try:
                        device._rx_queue.put_nowait(frame)
                        device._notify_receive(frame)
                    except queue.Full:
                        device._stats.error_count += 1

        # 环回 (标记 TX: 本机发送的帧在 Trace 中显示为 TX 而非 RX)
        if self._loopback_enabled:
            loopback_frame = dict(frame)
            loopback_frame["direction"] = "TX"
            try:
                self._rx_queue.put_nowait(loopback_frame)
                self._notify_receive(loopback_frame)
            except queue.Full:
                pass

        return True

    def receive(self, timeout: float = 0.1) -> Optional[dict]:
        """接收帧"""
        try:
            return self._rx_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def receive_batch(self, max_count: int = 100,
                      timeout: float = 0.01) -> list[dict]:
        """批量接收 (纯内存队列非阻塞排空, timeout 忽略;
        不覆写会落回基类空转自旋实现: 空队列每通道阻塞 ~10ms/轮询,
        轮询在 UI 线程执行 -> 整个界面卡死)"""
        frames = []
        while len(frames) < max_count:
            try:
                frames.append(self._rx_queue.get_nowait())
            except queue.Empty:
                break
        return frames

    def inject_frame(self, frame: dict):
        """外部注入帧(用于测试)"""
        try:
            self._rx_queue.put_nowait(frame)
            self._notify_receive(frame)
        except queue.Full:
            pass

    def set_loopback(self, enabled: bool):
        """设置环回模式"""
        self._loopback_enabled = enabled

    def clear_queue(self):
        """清空接收队列"""
        while not self._rx_queue.empty():
            try:
                self._rx_queue.get_nowait()
            except queue.Empty:
                break
