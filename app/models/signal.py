"""信号数据模型"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class SignalType(Enum):
    """信号类型"""
    UNSIGNED = "unsigned"
    SIGNED = "signed"
    FLOAT = "float"
    DOUBLE = "double"
    RAW = "raw"


class ByteOrder(Enum):
    """字节序"""
    LITTLE_ENDIAN = "little"
    BIG_ENDIAN = "big"


@dataclass
class ValueDescription:
    """信号值描述（枚举值定义）"""
    value: int
    name: str
    description: str = ""


@dataclass
class Signal:
    """CAN信号模型 - 对应DBC中SG_定义"""

    name: str                           # 信号名称
    start_bit: int                      # 起始位
    length: int                         # 信号长度(bit)
    byte_order: ByteOrder = ByteOrder.BIG_ENDIAN
    signal_type: SignalType = SignalType.UNSIGNED
    factor: float = 1.0                 # 缩放因子
    offset: float = 0.0                 # 偏移量
    minimum: float = 0.0                # 最小值
    maximum: float = 0.0                # 最大值
    unit: str = ""                      # 单位
    comment: str = ""                   # 注释
    receiver_nodes: list[str] = field(default_factory=list)

    # 值描述表
    value_descriptions: list[ValueDescription] = field(default_factory=list)

    # 多路复用
    is_multiplexer: bool = False        # 是否为多路复用器信号
    multiplexer_value: Optional[int] = None  # 多路复用值(-1表示非复用信号)

    # 运行时值
    raw_value: int = 0                  # 原始值
    physical_value: float = 0.0         # 物理值

    def decode(self, data: bytes) -> float:
        """从报文数据中解码信号物理值"""
        raw = self.decode_raw(data)
        self.raw_value = raw
        self.physical_value = raw * self.factor + self.offset
        return self.physical_value

    def decode_raw(self, data: bytes) -> int:
        """从报文数据中解码信号原始值"""
        bit_pos = self.start_bit
        bit_len = self.length

        # 将字节数组转为整数
        if self.byte_order == ByteOrder.BIG_ENDIAN:
            value = int.from_bytes(data, byteorder='big')
        else:
            value = int.from_bytes(data, byteorder='little')

        # 提取指定位
        mask = (1 << bit_len) - 1
        # 注意：DBC中start_bit的定义 - bit0是最高位(big-endian位编号)
        if self.byte_order == ByteOrder.BIG_ENDIAN:
            total_bits = len(data) * 8
            shift = max(0, total_bits - bit_pos - bit_len)
        else:
            shift = bit_pos

        raw = (value >> shift) & mask

        # 有符号处理
        if self.signal_type == SignalType.SIGNED and (raw >> (bit_len - 1)) & 1:
            raw -= (1 << bit_len)

        return raw

    def encode(self, physical_value: float, data: bytearray) -> None:
        """将物理值编码写入报文数据"""
        raw = int((physical_value - self.offset) / self.factor)
        self.encode_raw(raw, data)

    def encode_raw(self, raw: int, data: bytearray) -> None:
        """将原始值编码写入报文数据"""
        bit_pos = self.start_bit
        bit_len = self.length
        mask = (1 << bit_len) - 1
        raw &= mask

        if self.byte_order == ByteOrder.BIG_ENDIAN:
            total_bits = len(data) * 8
            shift = max(0, total_bits - bit_pos - bit_len)
        else:
            shift = bit_pos

        # 清除旧值
        clear_mask = ~(mask << shift)
        value = int.from_bytes(data, byteorder='big')
        value = (value & clear_mask) | (raw << shift)
        data[:] = value.to_bytes(len(data), byteorder='big')

    def get_value_description(self, raw_value: int) -> str:
        """获取原始值对应的描述"""
        for vd in self.value_descriptions:
            if vd.value == raw_value:
                return vd.name
        return str(raw_value)

    @property
    def display_value(self) -> str:
        """获取用于显示的物理值字符串"""
        if self.value_descriptions:
            desc = self.get_value_description(self.raw_value)
            if desc != str(self.raw_value):
                return desc
        if self.unit:
            return f"{self.physical_value:.2f} {self.unit}"
        return f"{self.physical_value:.2f}"
