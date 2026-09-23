"""
Vector CAN设备驱动 - 基于 python-can 的 XL Driver Library 绑定

移植说明:
- Java侧 VectorCanFDX 依赖 CANoe 软件的 FDX TCP 连接, 不适合独立工具;
- 此处优化为经 python-can 的 vector 接口直连 Vector 硬件 (vxlapi64.dll),
  无需 CANoe, 连接语义与本项目其他设备驱动保持一致。

需要安装 Vector 硬件驱动与 XL Driver Library。
"""

import time
import logging
from typing import Optional

from app.devices.drivers.base import BaseBusDevice, BusState

logger = logging.getLogger(__name__)


class VectorCanDevice(BaseBusDevice):
    """
    Vector单通道CAN设备驱动

    一个实例对应一个硬件通道; open 时经 python-can 建立 XL 驱动连接,
    波特率/CAN FD 参数在 open 前通过 set_baud_rate/set_can_fd 下发。
    """

    def __init__(self, channel: int = 1, dll_path: str = "",
                 serial: str = "", app_name: str = "BusForge"):
        """
        构造单通道设备驱动

        Args:
            channel: 硬件通道号 (1-based, python-can 内部转0-based)
            dll_path: 预留 (python-can 自行定位 vxlapi64.dll)
            serial: 设备序列号 (多设备时区分, 可选)
            app_name: XL 驱动应用名
        """
        super().__init__(channel)
        self._dll_path = dll_path
        self._serial = serial
        self._app_name = app_name
        self._bus = None

    @property
    def device_name(self) -> str:
        """设备可读名称"""
        return f"VectorCAN(CH{self.channel})"

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #

    def open(self) -> bool:
        """打开Vector通道 (建立XL驱动连接并配置波特率)"""
        try:
            import can
            kwargs = {
                'interface': 'vector',
                'app_name': self._app_name,
                'channel': self.channel - 1,
                'bitrate': int(self._baud_rate),
                'fd': bool(self._is_fd),
            }
            if self._is_fd:
                kwargs['data_bitrate'] = int(self._data_baud_rate)
            if self._serial:
                kwargs['serial'] = self._serial
            self._bus = can.Bus(**kwargs)
            self._state = BusState.CONNECTED
            logger.info(f"Vector通道已打开: {self.device_name} "
                        f"@ {self._baud_rate / 1000:.0f}kbps "
                        f"fd={self._is_fd}")
            return True
        except ImportError as e:
            logger.error(f"python-can未安装: {e}")
            self._state = BusState.ERROR
            return False
        except Exception as e:
            logger.error(f"打开Vector设备失败: {e}")
            self._state = BusState.ERROR
            return False

    def close(self) -> bool:
        """关闭Vector通道 (释放XL驱动连接)"""
        try:
            if self._bus is not None:
                self._bus.shutdown()
                self._bus = None
            self._state = BusState.DISCONNECTED
            logger.info(f"Vector通道已关闭: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"关闭Vector通道失败: {e}")
            return False

    def start(self) -> bool:
        """启动通道 (XL连接建立后即接收, 此处进入RUNNING)"""
        try:
            self._state = BusState.RUNNING
            logger.info(f"Vector通道已启动: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"启动Vector通道失败: {e}")
            return False

    def stop(self) -> bool:
        """停止通道 (回到CONNECTED)"""
        try:
            self._state = BusState.CONNECTED
            logger.info(f"Vector通道已停止: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"停止Vector通道失败: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  收发
    # ------------------------------------------------------------------ #

    def send(self, msg_id: int, data: bytes, is_extended: bool = False,
             is_fd: bool = False, is_remote: bool = False,
             is_brs: bool = False) -> bool:
        """发送CAN/CAN FD帧 (is_remote 仅经典CAN, is_brs 仅FD)"""
        if not self.is_connected or self._bus is None:
            return False
        try:
            import can
            msg = can.Message(
                arbitration_id=msg_id,
                data=b"" if is_remote else bytes(data),
                is_extended_id=is_extended,
                is_fd=is_fd,
                is_remote_frame=is_remote and not is_fd,
                bitrate_switch=is_brs and is_fd,
            )
            self._bus.send(msg)
            self._stats.tx_count += 1
            self._stats.last_tx_time = time.time()
            return True
        except Exception as e:
            logger.error(f"Vector发送失败: {e}")
            self._stats.error_count += 1
            return False

    def receive(self, timeout: float = 0.1) -> Optional[dict]:
        """接收一帧CAN/CAN FD数据"""
        if not self.is_connected or self._bus is None:
            return None
        try:
            msg = self._bus.recv(timeout)
            return self._msg_to_dict(msg) if msg else None
        except Exception as e:
            logger.error(f"Vector接收异常: {e}")
            return None

    def receive_batch(self, max_count: int = 100,
                      timeout: float = 0.01) -> list[dict]:
        """批量接收CAN/CAN FD帧 (非阻塞排空)"""
        if not self.is_connected or self._bus is None:
            return []
        frames = []
        deadline = time.time() + timeout
        while len(frames) < max_count:
            try:
                msg = self._bus.recv(max(0.0, deadline - time.time()))
            except Exception as e:
                logger.error(f"Vector批量接收异常: {e}")
                break
            if msg is None:
                break
            frames.append(self._msg_to_dict(msg))
        if frames:
            self._stats.rx_count += len(frames)
            self._stats.last_rx_time = time.time()
        return frames

    @staticmethod
    def _msg_to_dict(msg) -> dict:
        """python-can Message 转统一帧dict"""
        return {
            'id': msg.arbitration_id,
            'data': bytes(msg.data),
            'dlc': msg.dlc,
            'is_extended': msg.is_extended_id,
            'is_fd': msg.is_fd,
            'direction': 'TX' if msg.is_rx is False else 'RX',
            'timestamp': msg.timestamp,
        }
