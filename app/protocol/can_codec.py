"""CAN信号编解码器"""

from typing import Optional
from app.models.signal import Signal, ByteOrder
from app.models.message import CanMessage
from app.models.dbc_model import DbcDatabase


class CanCodec:
    """CAN信号编解码器 - 基于DBC数据库进行信号解析"""

    def __init__(self, dbc: Optional[DbcDatabase] = None):
        self._dbc = dbc

    def set_database(self, dbc: DbcDatabase):
        """设置DBC数据库"""
        self._dbc = dbc

    def decode_message(self, msg: CanMessage) -> CanMessage:
        """
        根据DBC解码报文中的所有信号

        返回附带信号值的CanMessage
        """
        if self._dbc is None:
            return msg

        dbc_msg = self._dbc.get_message_by_id(msg.message_id)
        if dbc_msg is None:
            return msg

        msg.message_name = dbc_msg.name
        msg.sender_node = dbc_msg.sender
        msg.signals = []

        for dbc_sig in dbc_msg.signals:
            # 复制信号定义并解码
            sig = Signal(
                name=dbc_sig.name,
                start_bit=dbc_sig.start_bit,
                length=dbc_sig.length,
                byte_order=dbc_sig.byte_order,
                signal_type=dbc_sig.signal_type,
                factor=dbc_sig.factor,
                offset=dbc_sig.offset,
                minimum=dbc_sig.minimum,
                maximum=dbc_sig.maximum,
                unit=dbc_sig.unit,
                comment=dbc_sig.comment,
                value_descriptions=list(dbc_sig.value_descriptions),
                is_multiplexer=dbc_sig.is_multiplexer,
                multiplexer_value=dbc_sig.multiplexer_value,
            )
            sig.decode(msg.data)
            msg.signals.append(sig)

        return msg

    def decode_frame(self, frame: dict) -> CanMessage:
        """从原始帧dict解码为CanMessage"""
        msg = CanMessage(
            message_id=frame["id"],
            data=bytearray(frame.get("data", b"")),
            dlc=frame.get("dlc", 8),
            is_extended=frame.get("is_extended", False),
            is_fd=frame.get("is_fd", False),
            channel=frame.get("channel", 1),
            timestamp=frame.get("timestamp", 0),
        )
        return self.decode_message(msg)

    def encode_message(self, msg_name: str, signal_values: dict[str, float],
                       channel: int = 1) -> Optional[CanMessage]:
        """
        根据信号值编码报文

        signal_values: {信号名: 物理值}
        """
        if self._dbc is None:
            return None

        dbc_msg = self._dbc.get_message_by_name(msg_name)
        if dbc_msg is None:
            return None

        msg = dbc_msg.to_can_message(channel)

        for sig_name, value in signal_values.items():
            msg.encode_signal(sig_name, value)

        return msg
