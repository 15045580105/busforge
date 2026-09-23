"""CAN报文数据模型"""

from dataclasses import dataclass, field
from typing import Optional
import time

from app.models.signal import Signal


@dataclass
class CanMessage:
    """CAN报文模型"""

    message_id: int                     # 报文ID
    data: bytearray = field(default_factory=lambda: bytearray(8))
    is_extended: bool = False           # 是否扩展帧(29bit ID)
    is_fd: bool = False                 # 是否CAN FD帧
    is_remote: bool = False             # 是否远程帧
    channel: int = 1                    # 通道号
    dlc: int = 8                        # 数据长度
    timestamp: float = 0.0              # 时间戳(秒)
    direction: str = "RX"               # 方向: RX / TX

    # 关联的DBC报文信息
    message_name: str = ""              # 报文名称(来自DBC)
    sender_node: str = ""               # 发送节点
    cycle_time: int = 0                 # 发送周期(ms)
    signals: list[Signal] = field(default_factory=list)

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def id_hex(self) -> str:
        """ID的十六进制表示"""
        return f"0x{self.message_id:03X}"

    @property
    def data_hex(self) -> str:
        """数据的十六进制表示"""
        return " ".join(f"{b:02X}" for b in self.data)

    @property
    def data_length(self) -> int:
        """实际数据长度"""
        if self.is_fd:
            fd_dlc_map = {9: 12, 10: 16, 11: 20, 12: 24, 13: 32, 14: 48, 15: 64}
            return fd_dlc_map.get(self.dlc, self.dlc)
        return min(self.dlc, 8)

    def decode_signals(self) -> dict[str, float]:
        """解码所有信号，返回 {信号名: 物理值}"""
        result = {}
        for sig in self.signals:
            try:
                value = sig.decode(self.data)
                result[sig.name] = value
            except Exception:
                pass
        return result

    def encode_signal(self, signal_name: str, physical_value: float) -> bool:
        """编码指定信号的值到报文数据"""
        for sig in self.signals:
            if sig.name == signal_name:
                sig.encode(physical_value, self.data)
                return True
        return False

    def copy(self) -> "CanMessage":
        """创建报文副本"""
        return CanMessage(
            message_id=self.message_id,
            data=bytearray(self.data),
            is_extended=self.is_extended,
            is_fd=self.is_fd,
            is_remote=self.is_remote,
            channel=self.channel,
            dlc=self.dlc,
            timestamp=self.timestamp,
            direction=self.direction,
            message_name=self.message_name,
            sender_node=self.sender_node,
            cycle_time=self.cycle_time,
            signals=list(self.signals),
        )
