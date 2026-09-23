"""
DBC文件解析器 - 纯Python实现

解析Vector DBC格式文件，提取报文和信号定义。
不依赖任何外部库，完全自包含。
"""

import re
import logging
from typing import Optional
from pathlib import Path

from app.models.signal import Signal, SignalType, ByteOrder, ValueDescription
from app.models.dbc_model import DbcDatabase, DbcMessage, DbcNode

logger = logging.getLogger(__name__)


class DbcParser:
    """
    DBC文件解析器

    支持解析标准DBC格式文件，提取：
    - 版本信息 (VERSION)
    - 节点定义 (BU_)
    - 报文定义 (BO_) 及信号定义 (SG_)
    - 信号注释 (CM_)
    - 值描述 (VAL_)
    - 发送周期 (BA_ "GenMsgCycleTime")
    """

    def __init__(self):
        self._db = DbcDatabase()

    def parse_file(self, file_path: str) -> DbcDatabase:
        """解析DBC文件"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"DBC文件不存在: {file_path}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        self._db = DbcDatabase(name=path.stem)
        self._db.source_path = str(path)
        self._parse_content(content)
        self._db.build_index()

        logger.info(
            f"DBC解析完成: {path.name} - "
            f"{self._db.message_count}个报文, "
            f"{self._db.signal_count}个信号"
        )
        return self._db

    def parse_string(self, content: str) -> DbcDatabase:
        """解析DBC字符串"""
        self._db = DbcDatabase(name="inline")
        self._parse_content(content)
        self._db.build_index()
        return self._db

    def _parse_content(self, content: str):
        """解析DBC内容"""
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if line.startswith("VERSION"):
                self._parse_version(line)

            elif line.startswith("BU_:"):
                self._parse_nodes(line)

            elif line.startswith("BO_ "):
                i = self._parse_message(lines, i)
                continue

            elif line.startswith("CM_ BO_ "):
                self._parse_message_comment(line)

            elif line.startswith("CM_ SG_ "):
                self._parse_signal_comment(line)

            elif line.startswith("VAL_ "):
                self._parse_value_descriptions(line)

            elif line.startswith("BA_ \"GenMsgCycleTime\""):
                self._parse_cycle_time(line)

            elif line.startswith("BA_ \"VFrameFormat\""):
                self._parse_frame_format(line)

            i += 1

    def _parse_version(self, line: str):
        """解析版本: VERSION "xxx" """
        match = re.search(r'VERSION\s+"([^"]*)"', line)
        if match:
            self._db.version = match.group(1)

    def _parse_nodes(self, line: str):
        """解析节点: BU_: Node1 Node2 ..."""
        nodes_str = line.replace("BU_:", "").strip()
        for name in nodes_str.split():
            self._db.nodes.append(DbcNode(name=name))

    def _parse_message(self, lines: list[str], start: int) -> int:
        """
        解析报文及信号定义
        BO_ <msg_id> <msg_name>: <dlc> <sender>
          SG_ <signal_name> : <start_bit>|<length>@<byte_order><type> (<factor>,<offset>) [<min>|<max>] "<unit>" <receivers>
        """
        line = lines[start].strip()
        match = re.match(
            r'BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)',
            line
        )
        if not match:
            return start

        msg_id = int(match.group(1))
        msg_name = match.group(2)
        dlc = int(match.group(3))
        sender = match.group(4)

        # 处理扩展帧ID (最高位为1)
        is_extended = False
        if msg_id > 0x80000000:
            msg_id -= 0x80000000
            is_extended = True

        dbc_msg = DbcMessage(
            name=msg_name,
            message_id=msg_id,
            dlc=dlc,
            sender=sender,
        )

        # 解析信号行
        i = start + 1
        while i < len(lines):
            sig_line = lines[i].strip()
            if not sig_line.startswith("SG_ "):
                break

            signal = self._parse_signal(sig_line)
            if signal:
                dbc_msg.signals.append(signal)
            i += 1

        self._db.messages.append(dbc_msg)
        return i - 1  # 返回最后处理的行索引

    def _parse_signal(self, line: str) -> Optional[Signal]:
        """
        解析信号定义行
        SG_ <name> [M|m<mux_val>] : <start>|<len>@<order><sign> (<factor>,<offset>) [<min>|<max>] "<unit>" <receivers>
        """
        # 匹配信号定义
        # 字节序/符号位为标准 DBC 的 @<0|1><+|->: 0=Motorola(大端) 1=Intel(小端),
        # +=无符号 -=有符号 (旧版误写为两个 +/-, 导致全部信号行匹配失败)
        pattern = (
            r'SG_\s+(\w+)\s*'
            r'([Mm]\d*)?\s*'           # 多路复用标记(可选)
            r':\s*(\d+)\|(\d+)'        # start_bit|length
            r'@([01])([+-])'           # byte_order(0/1) + sign(+/-)
            r'\s*\(([^,]+),([^)]+)\)'  # (factor,offset)
            r'\s*\[([^|]+)\|([^\]]+)\]'  # [min|max]
            r'\s*"([^"]*)"'            # "unit"
            r'\s*(.*)'                 # receivers
        )
        match = re.match(pattern, line)
        if not match:
            return None

        name = match.group(1)
        mux_mark = match.group(2)  # M / m0 / m1 等
        start_bit = int(match.group(3))
        length = int(match.group(4))
        byte_order_char = match.group(5)  # 0 = big endian(Motorola), 1 = little endian(Intel)
        sign_char = match.group(6)        # + = unsigned, - = signed
        factor = float(match.group(7))
        offset = float(match.group(8))
        minimum = float(match.group(9))
        maximum = float(match.group(10))
        unit = match.group(11)
        receivers_str = match.group(12).strip()

        # 字节序: 0=Motorola(大端) 1=Intel(小端)
        byte_order = ByteOrder.BIG_ENDIAN if byte_order_char == "0" else ByteOrder.LITTLE_ENDIAN

        # 符号类型
        signal_type = SignalType.UNSIGNED if sign_char == "+" else SignalType.SIGNED

        # 多路复用
        is_multiplexer = False
        multiplexer_value = None
        if mux_mark:
            if mux_mark == "M":
                is_multiplexer = True
            elif mux_mark.startswith("m"):
                try:
                    multiplexer_value = int(mux_mark[1:])
                except ValueError:
                    pass

        # 接收节点
        receivers = [r.strip() for r in receivers_str.split(",") if r.strip()]

        return Signal(
            name=name,
            start_bit=start_bit,
            length=length,
            byte_order=byte_order,
            signal_type=signal_type,
            factor=factor,
            offset=offset,
            minimum=minimum,
            maximum=maximum,
            unit=unit,
            receiver_nodes=receivers,
            is_multiplexer=is_multiplexer,
            multiplexer_value=multiplexer_value,
        )

    def _parse_message_comment(self, line: str):
        """解析报文注释: CM_ BO_ <id> "comment";"""
        match = re.match(r'CM_\s+BO_\s+(\d+)\s+"([^"]*)"', line)
        if match:
            msg_id = int(match.group(1))
            comment = match.group(2)
            msg = self._find_msg(msg_id)
            if msg:
                msg.comment = comment

    def _parse_signal_comment(self, line: str):
        """解析信号注释: CM_ SG_ <msg_id> <signal_name> "comment";"""
        match = re.match(r'CM_\s+SG_\s+(\d+)\s+(\w+)\s+"([^"]*)"', line)
        if match:
            msg_id = int(match.group(1))
            sig_name = match.group(2)
            comment = match.group(3)
            msg = self._find_msg(msg_id)
            if msg:
                sig = msg.find_signal(sig_name)
                if sig:
                    sig.comment = comment

    def _parse_value_descriptions(self, line: str):
        """
        解析值描述: VAL_ <msg_id> <signal_name> <value> "<name>" <value> "<name>" ... ;
        """
        match = re.match(r'VAL_\s+(\d+)\s+(\w+)\s+(.*);', line)
        if not match:
            return

        msg_id = int(match.group(1))
        sig_name = match.group(2)
        values_str = match.group(3).strip()

        msg = self._find_msg(msg_id)
        if not msg:
            return
        sig = msg.find_signal(sig_name)
        if not sig:
            return

        # 解析 value "name" 对
        pairs = re.findall(r'(\d+)\s+"([^"]*)"', values_str)
        for val_str, name in pairs:
            sig.value_descriptions.append(
                ValueDescription(value=int(val_str), name=name)
            )

    def _parse_cycle_time(self, line: str):
        """解析发送周期: BA_ "GenMsgCycleTime" BO_ <id> <time_ms>;"""
        match = re.match(r'BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)', line)
        if match:
            msg_id = int(match.group(1))
            cycle_time = int(match.group(2))
            msg = self._find_msg(msg_id)
            if msg:
                msg.cycle_time = cycle_time

    def _parse_frame_format(self, line: str):
        """解析帧格式: BA_ "VFrameFormat" BO_ <id> <val>;
        枚举值 14=StandardCAN_FD, 15=ExtendedCAN_FD (14及以上即FD报文)"""
        match = re.match(r'BA_\s+"VFrameFormat"\s+BO_\s+(\d+)\s+(\d+)', line)
        if match:
            msg = self._find_msg(int(match.group(1)))
            if msg and int(match.group(2)) >= 14:
                msg.is_fd = True

    def _find_msg(self, msg_id: int) -> Optional[DbcMessage]:
        """解析期间按ID线性查找报文
        (build_index 在 _parse_content 完成后才执行, 解析中索引为空,
        解析期调用 get_message_by_id 会静默返回 None)"""
        for m in self._db.messages:
            if m.message_id == msg_id:
                return m
        return None
