"""
脚本运行时API - 提供给用户脚本的内置函数和变量

用户脚本通过此运行时与总线交互，类似CAPL中的变量和函数。
"""

import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ScriptVariable:
    """脚本变量 - 类似CAPL中的message/signal/variable"""

    def __init__(self, name: str, value=None):
        self.name = name
        self._value = value
        self._observers: list[Callable] = []

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_value):
        old_value = self._value
        self._value = new_value
        if old_value != new_value:
            for obs in self._observers:
                try:
                    obs(self.name, old_value, new_value)
                except Exception as e:
                    logger.error(f"变量观察器异常: {e}")

    def on_change(self, callback: Callable):
        """注册值变化观察器"""
        self._observers.append(callback)


class ScriptRuntime:
    """
    脚本运行时 - 提供给用户脚本的API环境

    用户脚本中可用的内置函数:
    - send(id, data)           发送CAN帧
    - receive(timeout)         接收CAN帧
    - read_signal(msg, signal) 读取信号值
    - write_signal(msg, signal, value) 写入信号值
    - sleep(ms)                延时
    - log(msg)                 日志输出
    - get_time()               获取当前时间
    - set_timer(ms, callback)  设置定时器

    用户脚本中可用的内置变量:
    - this.msg                 当前触发报文
    - this.channel             当前通道
    - this.signal              当前信号
    """

    def __init__(self, bus_device=None, codec=None, uds_client=None):
        self.bus = bus_device
        self.codec = codec
        self.uds = uds_client

        # 脚本变量存储
        self._variables: dict[str, ScriptVariable] = {}
        self._timers: dict[str, dict] = {}
        self._log_output: list[str] = []
        self._running = True

    # ---- 报文收发 ----

    def send(self, msg_id: int, data: list[int] | bytes,
             is_extended: bool = False) -> bool:
        """发送CAN帧"""
        if self.bus is None:
            self.log("错误: 总线设备未连接")
            return False
        return self.bus.send(msg_id, bytes(data), is_extended=is_extended)

    def send_message(self, msg_name: str, signal_values: dict[str, float],
                     channel: int = 1) -> bool:
        """按DBC报文名发送(自动编码信号值)"""
        if self.codec is None:
            self.log("错误: 未加载DBC数据库")
            return False
        msg = self.codec.encode_message(msg_name, signal_values, channel)
        if msg is None:
            self.log(f"错误: 未找到报文 {msg_name}")
            return False
        return self.bus.send(msg.message_id, bytes(msg.data))

    def receive(self, timeout: float = 0.1) -> Optional[dict]:
        """接收CAN帧"""
        if self.bus is None:
            return None
        return self.bus.receive(timeout=timeout)

    # ---- 信号操作 ----

    def read_signal(self, msg_id: int, signal_name: str) -> Optional[float]:
        """读取信号值(从最近接收的报文中)"""
        if self.codec is None:
            return None
        # 从总线接收队列获取最新帧并解码
        frame = self.bus.receive(timeout=0.01) if self.bus else None
        if frame and frame["id"] == msg_id:
            msg = self.codec.decode_frame(frame)
            for sig in msg.signals:
                if sig.name == signal_name:
                    return sig.physical_value
        return None

    def write_signal(self, msg_name: str, signal_name: str, value: float) -> bool:
        """写入信号值并发送报文"""
        return self.send_message(msg_name, {signal_name: value})

    # ---- UDS诊断 ----

    def uds_send(self, data: list[int] | bytes):
        """发送UDS请求"""
        if self.uds:
            self.uds._send_uds(bytes(data))

    def uds_session(self, session_type: int):
        """切换UDS会话"""
        if self.uds:
            self.uds.diagnostic_session_control(session_type)

    def uds_security(self, level: int) -> bool:
        """执行UDS安全访问"""
        if self.uds:
            return self.uds.execute_security_access(level)
        return False

    def uds_routine(self, routine_id: int, option: int = 1) -> bool:
        """执行UDS例行控制"""
        if self.uds:
            resp = self.uds.routine_control(routine_id, option)
            return resp.is_positive
        return False

    # ---- 变量系统 ----

    def create_variable(self, name: str, initial_value=None) -> ScriptVariable:
        """创建脚本变量"""
        var = ScriptVariable(name, initial_value)
        self._variables[name] = var
        return var

    def get_variable(self, name: str) -> Optional[ScriptVariable]:
        """获取脚本变量"""
        return self._variables.get(name)

    def set_variable(self, name: str, value):
        """设置脚本变量值"""
        var = self._variables.get(name)
        if var:
            var.value = value
        else:
            self._variables[name] = ScriptVariable(name, value)

    # ---- 定时器 ----

    def set_timer(self, name: str, interval_ms: int, callback: Callable):
        """设置周期定时器"""
        self._timers[name] = {
            "interval": interval_ms / 1000.0,
            "callback": callback,
            "last_fire": time.time(),
            "active": True,
        }

    def cancel_timer(self, name: str):
        """取消定时器"""
        if name in self._timers:
            self._timers[name]["active"] = False

    def check_timers(self):
        """检查并触发到期定时器(由主循环调用)"""
        now = time.time()
        for name, timer in self._timers.items():
            if not timer["active"]:
                continue
            if now - timer["last_fire"] >= timer["interval"]:
                try:
                    timer["callback"]()
                except Exception as e:
                    self.log(f"定时器 {name} 异常: {e}")
                timer["last_fire"] = now

    # ---- 工具函数 ----

    def sleep(self, ms: int):
        """延时(毫秒)"""
        time.sleep(ms / 1000.0)

    def get_time(self) -> float:
        """获取当前时间戳(秒)"""
        return time.time()

    def log(self, message: str):
        """日志输出"""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        log_line = f"[{timestamp}] {message}"
        self._log_output.append(log_line)
        logger.info(f"[Script] {message}")

    def get_log(self) -> list[str]:
        """获取日志"""
        return list(self._log_output)

    def clear_log(self):
        """清空日志"""
        self._log_output.clear()

    def stop(self):
        """停止运行时"""
        self._running = False
        for timer in self._timers.values():
            timer["active"] = False

    @property
    def is_running(self) -> bool:
        return self._running

    def get_builtins_dict(self) -> dict:
        """获取内置函数字典(注入到脚本执行环境)"""
        return {
            "send": self.send,
            "send_message": self.send_message,
            "receive": self.receive,
            "read_signal": self.read_signal,
            "write_signal": self.write_signal,
            "uds_send": self.uds_send,
            "uds_session": self.uds_session,
            "uds_security": self.uds_security,
            "uds_routine": self.uds_routine,
            "create_variable": self.create_variable,
            "get_variable": self.get_variable,
            "set_variable": self.set_variable,
            "set_timer": self.set_timer,
            "cancel_timer": self.cancel_timer,
            "sleep": self.sleep,
            "get_time": self.get_time,
            "log": self.log,
        }
