"""DBC数据库模型"""

from dataclasses import dataclass, field
from typing import Optional
from app.models.signal import Signal
from app.models.message import CanMessage


@dataclass
class DbcMessage:
    """DBC报文定义"""
    name: str                           # 报文名 (BO_ name)
    message_id: int                     # 报文ID
    sender: str = ""                    # 发送节点
    dlc: int = 8                        # 数据长度
    signals: list[Signal] = field(default_factory=list)
    comment: str = ""
    cycle_time: int = 0                 # 发送周期(ms)
    is_fd: bool = False                 # CAN FD报文 (BA_ "VFrameFormat")

    def find_signal(self, name: str) -> Optional[Signal]:
        """按名称查找信号"""
        for sig in self.signals:
            if sig.name == name:
                return sig
        return None

    def to_can_message(self, channel: int = 1) -> CanMessage:
        """转换为可发送的CanMessage"""
        return CanMessage(
            message_id=self.message_id,
            data=bytearray(self.dlc),
            channel=channel,
            dlc=self.dlc,
            is_fd=self.is_fd,
            message_name=self.name,
            sender_node=self.sender,
            cycle_time=self.cycle_time,
            signals=list(self.signals),
        )


@dataclass
class DbcNode:
    """DBC节点定义"""
    name: str
    comment: str = ""


@dataclass
class DbcDatabase:
    """DBC数据库模型 - 一个DBC文件的完整解析结果"""

    name: str = ""                      # 数据库名称
    version: str = ""                   # 版本号
    source_path: str = ""               # 来源 .dbc 文件路径 (多DBC导入/持久化用)
    nodes: list[DbcNode] = field(default_factory=list)
    messages: list[DbcMessage] = field(default_factory=list)

    # 索引缓存
    _msg_by_id: dict[int, DbcMessage] = field(default_factory=dict, repr=False)
    _msg_by_name: dict[str, DbcMessage] = field(default_factory=dict, repr=False)

    def build_index(self):
        """构建索引"""
        self._msg_by_id = {m.message_id: m for m in self.messages}
        self._msg_by_name = {m.name: m for m in self.messages}

    def get_message_by_id(self, msg_id: int) -> Optional[DbcMessage]:
        """按ID查找报文"""
        return self._msg_by_id.get(msg_id)

    def get_message_by_name(self, name: str) -> Optional[DbcMessage]:
        """按名称查找报文"""
        return self._msg_by_name.get(name)

    def get_all_signal_names(self) -> list[str]:
        """获取所有信号名"""
        names = []
        for msg in self.messages:
            for sig in msg.signals:
                names.append(sig.name)
        return names

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def signal_count(self) -> int:
        return sum(len(m.signals) for m in self.messages)
