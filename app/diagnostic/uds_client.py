"""
UDS诊断客户端 - 自包含实现

完整实现ISO 14229-1 UDS协议栈，直接通过总线设备收发诊断报文。
不依赖任何后端服务。

支持的服务:
- 0x10 诊断会话控制 (DiagnosticSessionControl)
- 0x11 ECU复位 (ECUReset)
- 0x22 读数据 (ReadDataByIdentifier)
- 0x27 安全访问 (SecurityAccess) - 支持外部DLL算法
- 0x2E 写数据 (WriteDataByIdentifier)
- 0x31 例行控制 (RoutineControl)
- 0x3E 测试器在线 (TesterPresent)
- 0x85 通信控制 (CommunicationControl)
"""

import ctypes
import time
import struct
import logging
from enum import IntEnum
from typing import Optional, Callable
from dataclasses import dataclass, field

from app.devices.drivers.base import BaseBusDevice

logger = logging.getLogger(__name__)


class UdsService(IntEnum):
    """UDS服务ID"""
    DIAGNOSTIC_SESSION_CONTROL = 0x10
    ECU_RESET = 0x11
    CLEAR_DIAGNOSTIC_INFORMATION = 0x14
    READ_DTC_INFORMATION = 0x19
    READ_DATA_BY_IDENTIFIER = 0x22
    SECURITY_ACCESS = 0x27
    COMMUNICATION_CONTROL = 0x28
    WRITE_DATA_BY_IDENTIFIER = 0x2E
    ROUTINE_CONTROL = 0x31
    REQUEST_DOWNLOAD = 0x34
    REQUEST_UPLOAD = 0x35
    TRANSFER_DATA = 0x36
    REQUEST_TRANSFER_EXIT = 0x37
    TESTER_PRESENT = 0x3E
    CONTROL_DTC_SETTING = 0x85


class NrcCode(IntEnum):
    """UDS负响应码 (NRC)"""
    GENERAL_REJECT = 0x10
    SERVICE_NOT_SUPPORTED = 0x11
    SUB_FUNCTION_NOT_SUPPORTED = 0x12
    INCORRECT_MESSAGE_LENGTH_OR_FORMAT = 0x13
    RESPONSE_TOO_LONG = 0x14
    BUSY_REPEAT_REQUEST = 0x21
    CONDITIONS_NOT_CORRECT = 0x22
    REQUEST_SEQUENCE_ERROR = 0x24
    NO_RESPONSE_FROM_SUBNET = 0x25
    FAILURE_PREVENTS_EXECUTION = 0x26
    REQUEST_OUT_OF_RANGE = 0x31
    SECURITY_ACCESS_DENIED = 0x33
    INVALID_KEY = 0x35
    EXCEEDED_NUMBER_OF_ATTEMPTS = 0x36
    REQUIRED_TIME_DELAY_NOT_EXPIRED = 0x37
    UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70
    TRANSFER_DATA_SUSPENDED = 0x71
    GENERAL_PROGRAMMING_FAILURE = 0x72
    WRONG_BLOCK_SEQUENCE_COUNTER = 0x73
    SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7F


@dataclass
class UdsResponse:
    """UDS响应"""
    service_id: int = 0
    sub_function: int = 0
    data: bytes = b""
    is_positive: bool = True
    nrc: int = 0
    raw_response: bytes = b""

    @property
    def nrc_name(self) -> str:
        """获取NRC名称"""
        try:
            return NrcCode(self.nrc).name
        except ValueError:
            return f"Unknown(0x{self.nrc:02X})"


@dataclass
class UdsConfig:
    """UDS配置"""
    request_id: int = 0x7E0           # 请求报文ID
    response_id: int = 0x7E8          # 响应报文ID
    channel: int = 1                  # 通道号
    p2_timeout: float = 1.0           # P2超时(秒)
    p2_star_timeout: float = 5.0      # P2*超时(秒)
    security_dll_path: str = ""       # 27服务DLL路径
    security_dll_function: str = "GenerateKey"  # DLL函数名
    polling_interval: float = 0.01    # 轮询间隔(秒)


class UdsClient:
    """
    UDS诊断客户端

    直接通过总线设备收发诊断报文，实现完整的UDS协议栈。
    支持通过外部DLL进行安全访问(seed-key)算法计算。
    """

    # 负响应SID
    NEGATIVE_RESPONSE_SID = 0x7F

    def __init__(self, bus_device: BaseBusDevice, config: Optional[UdsConfig] = None):
        self.bus = bus_device
        self.config = config or UdsConfig()
        self._security_dll: Optional[ctypes.CDLL] = None
        self._session_type: int = 1     # 当前会话类型
        self._security_level: int = 0   # 当前安全等级
        self._log_callback: Optional[Callable] = None

    def set_log_callback(self, callback: Callable[[str], None]):
        """设置日志回调"""
        self._log_callback = callback

    def _log(self, message: str):
        """记录日志"""
        logger.info(message)
        if self._log_callback:
            self._log_callback(message)

    # ---- 底层收发 ----

    def _send_uds(self, data: bytes):
        """发送UDS请求帧"""
        self._log(f"TX >> [{self.config.request_id:03X}] {' '.join(f'{b:02X}' for b in data)}")
        self.bus.send(
            msg_id=self.config.request_id,
            data=data,
            is_extended=False,
        )

    def _receive_uds(self, timeout: Optional[float] = None) -> Optional[UdsResponse]:
        """接收UDS响应帧"""
        timeout = timeout or self.config.p2_timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            frame = self.bus.receive(timeout=self.config.polling_interval)
            if frame is None:
                continue

            if frame["id"] != self.config.response_id:
                continue

            raw = frame["data"]
            if len(raw) < 1:
                continue

            return self._parse_response(raw)

        self._log("RX << 超时 - 未收到响应")
        return None

    def _parse_response(self, raw: bytes) -> UdsResponse:
        """解析UDS响应"""
        sid = raw[0]
        resp = UdsResponse(raw_response=raw)

        if sid == self.NEGATIVE_RESPONSE_SID:
            # 负响应: 7F <rejected_sid> <nrc>
            resp.is_positive = False
            if len(raw) >= 3:
                resp.service_id = raw[1]
                resp.nrc = raw[2]
            self._log(
                f"RX << NRC [{resp.service_id:02X}] "
                f"NRC=0x{resp.nrc:02X} ({resp.nrc_name})"
            )
        else:
            # 正响应: SID+0x40 <sub_function> <data...>
            resp.is_positive = True
            resp.service_id = sid
            if len(raw) >= 2:
                resp.sub_function = raw[1] & 0x7F  # 去除suppressPosBit
                resp.data = raw[2:] if len(raw) > 2 else b""
            self._log(
                f"RX << OK [{sid:02X}] "
                f"{' '.join(f'{b:02X}' for b in raw)}"
            )

        return resp

    # ---- 高层服务 ----

    def diagnostic_session_control(self, session_type: int) -> UdsResponse:
        """
        0x10 诊断会话控制

        session_type:
            0x01 = 默认会话
            0x02 = 编程会话
            0x03 = 扩展会话
        """
        self._log(f"0x10 诊断会话控制 -> session=0x{session_type:02X}")
        self._send_uds(bytes([UdsService.DIAGNOSTIC_SESSION_CONTROL, session_type]))
        resp = self._receive_uds()
        if resp and resp.is_positive:
            self._session_type = session_type
            self._log(f"  -> 已切换到会话 0x{session_type:02X}")
        return resp or UdsResponse(is_positive=False, nrc=0x10)

    def ecu_reset(self, reset_type: int = 0x01) -> UdsResponse:
        """
        0x11 ECU复位

        reset_type:
            0x01 = 硬复位
            0x02 = 钥匙关闭/打开复位
            0x03 = 软复位
        """
        self._log(f"0x11 ECU复位 -> type=0x{reset_type:02X}")
        self._send_uds(bytes([UdsService.ECU_RESET, reset_type]))
        return self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)

    def read_data_by_identifier(self, did: int) -> UdsResponse:
        """0x22 读数据 by DID"""
        did_bytes = struct.pack(">H", did)
        self._log(f"0x22 读数据 -> DID=0x{did:04X}")
        self._send_uds(bytes([UdsService.READ_DATA_BY_IDENTIFIER]) + did_bytes)
        return self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)

    def write_data_by_identifier(self, did: int, data: bytes) -> UdsResponse:
        """0x2E 写数据 by DID"""
        did_bytes = struct.pack(">H", did)
        self._log(f"0x2E 写数据 -> DID=0x{did:04X} data={' '.join(f'{b:02X}' for b in data)}")
        self._send_uds(bytes([UdsService.WRITE_DATA_BY_IDENTIFIER]) + did_bytes + data)
        return self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)

    def security_access(self, level: int, seed: Optional[bytes] = None) -> UdsResponse:
        """
        0x27 安全访问

        level: 安全等级 (0x01=请求seed, 0x02=发送key, ...)
        seed: 当level为偶数时，传入计算后的key
        """
        if level % 2 == 1:
            # 请求seed (奇数级)
            self._log(f"0x27 安全访问 -> 请求seed level=0x{level:02X}")
            self._send_uds(bytes([UdsService.SECURITY_ACCESS, level]))
            return self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)
        else:
            # 发送key (偶数级)
            key_data = seed or b""
            self._log(f"0x27 安全访问 -> 发送key level=0x{level:02X} key={' '.join(f'{b:02X}' for b in key_data)}")
            self._send_uds(bytes([UdsService.SECURITY_ACCESS, level]) + key_data)
            resp = self._receive_uds()
            if resp and resp.is_positive:
                self._security_level = level
                self._log("  -> 安全访问成功")
            return resp or UdsResponse(is_positive=False, nrc=0x10)

    def execute_security_access(self, level: int = 1) -> bool:
        """
        完整执行安全访问流程:
        1. 请求seed (奇数)
        2. 通过DLL计算key
        3. 发送key (偶数)

        返回是否成功
        """
        # Step 1: 请求seed
        resp = self.security_access(level)
        if not resp.is_positive:
            self._log(f"  -> 请求seed失败: NRC=0x{resp.nrc:02X}")
            return False

        seed = resp.data
        if seed == b"\x00\x00\x00\x00":
            self._log("  -> seed为全零，已解锁")
            self._security_level = level + 1
            return True

        # Step 2: 计算key
        key = self._compute_key(seed, level)
        if key is None:
            self._log("  -> 计算key失败")
            return False

        # Step 3: 发送key
        resp = self.security_access(level + 1, key)
        return resp.is_positive

    def _compute_key(self, seed: bytes, level: int) -> Optional[bytes]:
        """通过DLL计算key"""
        dll_path = self.config.security_dll_path
        if not dll_path:
            self._log("  -> 未配置安全算法DLL路径")
            return None

        try:
            if self._security_dll is None:
                self._security_dll = ctypes.CDLL(dll_path)

            func_name = self.config.security_dll_function
            if not hasattr(self._security_dll, func_name):
                self._log(f"  -> DLL中未找到函数: {func_name}")
                return None

            func = getattr(self._security_dll, func_name)

            # 尝试标准签名: int GenerateKey(unsigned char* seed, int seedLen, unsigned char* key)
            seed_array = (ctypes.c_ubyte * len(seed))(*seed)
            key_buffer = (ctypes.c_ubyte * 16)()

            result = func(
                ctypes.cast(seed_array, ctypes.POINTER(ctypes.c_ubyte)),
                ctypes.c_int(len(seed)),
                ctypes.cast(key_buffer, ctypes.POINTER(ctypes.c_ubyte)),
            )

            if result == 0:
                key = bytes(key_buffer[:4])  # 通常key为4字节
                self._log(f"  -> DLL计算key成功: {' '.join(f'{b:02X}' for b in key)}")
                return key
            else:
                self._log(f"  -> DLL返回错误码: {result}")
                return None

        except Exception as e:
            self._log(f"  -> DLL调用异常: {e}")
            return None

    def routine_control(self, routine_id: int, option: int = 0x01,
                        data: bytes = b"") -> UdsResponse:
        """
        0x31 例行控制

        option:
            0x01 = 启动例行程序
            0x02 = 停止例行程序
            0x03 = 查询例行程序结果
        """
        rid_bytes = struct.pack(">H", routine_id)
        self._log(
            f"0x31 例行控制 -> option=0x{option:02X} "
            f"routine=0x{routine_id:04X}"
        )
        self._send_uds(
            bytes([UdsService.ROUTINE_CONTROL, option]) + rid_bytes + data
        )
        return self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)

    def tester_present(self) -> UdsResponse:
        """0x3E 测试者在线(保活)"""
        self._send_uds(bytes([UdsService.TESTER_PRESENT, 0x00]))
        return self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)

    def communication_control(self, control_type: int,
                              communication_type: int = 0x01) -> UdsResponse:
        """0x85 通信控制"""
        self._log(
            f"0x85 通信控制 -> type=0x{control_type:02X} "
            f"comm=0x{communication_type:02X}"
        )
        self._send_uds(
            bytes([UdsService.COMMUNICATION_CONTROL, control_type, communication_type])
        )
        return self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)

    # ---- 序列执行 ----

    def execute_sequence(self, steps: list[dict]) -> list[UdsResponse]:
        """
        执行UDS步骤序列

        steps格式:
        [
            {"service": "10 03"},                    # 直接发送hex字符串
            {"service": "27", "level": 1},           # 安全访问请求seed
            {"service": "31", "option": 1, "routine": "3048", "data": "01"},
            ...
        ]
        """
        results = []
        for step in steps:
            service_hex = step.get("service", "").split()
            if not service_hex:
                continue

            sid = int(service_hex[0], 16)

            if sid == 0x10:
                session = int(service_hex[1], 16) if len(service_hex) > 1 else 1
                resp = self.diagnostic_session_control(session)

            elif sid == 0x27:
                level = int(service_hex[1], 16) if len(service_hex) > 1 else 1
                if level % 2 == 1:
                    # 完整执行安全访问
                    success = self.execute_security_access(level)
                    resp = UdsResponse(is_positive=success)
                else:
                    resp = self.security_access(level)

            elif sid == 0x31:
                option = int(service_hex[1], 16) if len(service_hex) > 1 else 1
                routine_str = step.get("routine", service_hex[2] if len(service_hex) > 2 else "0000")
                routine_id = int(routine_str, 16)
                data_str = step.get("data", "")
                data = bytes.fromhex(data_str) if data_str else b""
                resp = self.routine_control(routine_id, option, data)

            elif sid == 0x3E:
                resp = self.tester_present()

            else:
                # 通用发送
                raw = bytes(int(h, 16) for h in service_hex)
                self._send_uds(raw)
                resp = self._receive_uds() or UdsResponse(is_positive=False, nrc=0x10)

            results.append(resp)

            # 如果步骤失败且非27服务，中止序列
            if not resp.is_positive and sid != 0x27:
                self._log(f"  -> 步骤失败，中止序列")
                break

        return results
