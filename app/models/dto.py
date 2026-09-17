"""
数据中台推送数据结构 (DTO)

展示层(Trace/Signal/Graphy等)只消费这些结构, 不做任何解码/过滤计算。
"""

from dataclasses import dataclass, field


@dataclass
class SignalValueDTO:
    """信号值 - 已由解析层解码完毕"""
    name: str                            # 信号名
    message_name: str = ""               # 所属报文名
    channel_key: str = ""                # 软件通道key
    phys: float = 0.0                    # 物理值
    raw: int = 0                         # 原始值
    unit: str = ""                       # 单位
    value_desc: str = ""                 # 枚举值描述
    timestamp: float = 0.0               # 更新时间戳


@dataclass
class FrameDTO:
    """总线帧 - 可选携带解码结果"""
    channel_key: str                     # 软件通道key
    id: int = 0
    data: bytes = b""
    dlc: int = 8
    is_extended: bool = False
    is_fd: bool = False
    direction: str = "RX"                # RX / TX
    timestamp: float = 0.0
    name: str = ""                       # 报文名(解码后, 未解码为空)
    signals: list = field(default_factory=list)  # list[SignalValueDTO]

    @property
    def data_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.data)

    @property
    def data_length(self) -> int:
        if self.is_fd:
            fd_map = {9: 12, 10: 16, 11: 20, 12: 24, 13: 32, 14: 48, 15: 64}
            return fd_map.get(self.dlc, self.dlc)
        return min(self.dlc, 8)

    @property
    def id_hex(self) -> str:
        return f"0x{self.id:X}"


@dataclass
class StatsDTO:
    """通道统计 - 来自设备层BusStats"""
    channel_key: str
    tx_count: int = 0
    rx_count: int = 0
    error_count: int = 0
    bus_load: float = 0.0


@dataclass
class DeviceStateDTO:
    """设备/通道状态变化"""
    device_id: str
    state: str = "disconnected"          # disconnected / connected / error
    acquired: bool = False               # 是否被运行中项目占有
    channel_key: str = ""                # 通道级事件时填充
    channel_state: str = ""              # 通道级状态
