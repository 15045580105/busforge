"""
脚本执行引擎 - 类CAPL脚本系统

用户可以编写类似CAPL的脚本来自动化总线操作。
脚本通过ScriptRuntime提供的API与总线交互。

脚本格式示例:
    # BusForge Script
    # 功能: 周期发送UDS 0x3E保活报文

    def on_start():
        log("脚本启动")
        set_timer("keepalive", 2000, send_tester_present)

    def send_tester_present():
        uds_send([0x3E, 0x00])
        log("发送 3E 00 保活")

    def on_message(msg_id, data):
        log(f"收到: ID={msg_id:03X} DATA={' '.join(f'{b:02X}' for b in data)}")

    def on_stop():
        log("脚本停止")
"""

import logging
import traceback
from typing import Optional, Callable
from pathlib import Path

from app.script.runtime import ScriptRuntime

logger = logging.getLogger(__name__)


class ScriptEngine:
    """
    脚本执行引擎

    功能:
    - 加载并执行.py格式的脚本文件
    - 支持事件驱动(on_message, on_start, on_stop)
    - 支持定时器
    - 脚本隔离执行，不影响主程序
    """

    def __init__(self, runtime: ScriptRuntime):
        self.runtime = runtime
        self._script_globals: dict = {}
        self._is_running = False
        self._current_script: str = ""
        self._event_handlers: dict[str, Callable] = {}

    @property
    def is_running(self) -> bool:
        return self._is_running

    def load_script(self, file_path: str) -> bool:
        """加载脚本文件"""
        path = Path(file_path)
        if not path.exists():
            logger.error(f"脚本文件不存在: {file_path}")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            self._current_script = file_path
            return self._compile(source)
        except Exception as e:
            logger.error(f"加载脚本失败: {e}")
            return False

    def load_script_string(self, source: str) -> bool:
        """从字符串加载脚本"""
        self._current_script = "<inline>"
        return self._compile(source)

    def _compile(self, source: str) -> bool:
        """编译脚本"""
        try:
            # 构建执行环境
            self._script_globals = {
                "__builtins__": __builtins__,
                **self.runtime.get_builtins_dict(),
            }

            # 编译并执行脚本(定义函数和变量)
            code = compile(source, self._current_script, "exec")
            exec(code, self._script_globals)

            # 注册事件处理器
            self._event_handlers = {}
            for event_name in ["on_start", "on_stop", "on_message", "on_timer"]:
                if event_name in self._script_globals:
                    self._event_handlers[event_name] = self._script_globals[event_name]

            logger.info(f"脚本编译成功: {self._current_script}")
            return True

        except SyntaxError as e:
            logger.error(f"脚本语法错误: 行{e.lineno} - {e.msg}")
            return False
        except Exception as e:
            logger.error(f"脚本编译失败: {e}")
            return False

    def start(self) -> bool:
        """启动脚本执行"""
        if self._is_running:
            logger.warning("脚本已在运行中")
            return False

        self._is_running = True
        logger.info("脚本引擎启动")

        # 调用 on_start
        if "on_start" in self._event_handlers:
            try:
                self._event_handlers["on_start"]()
            except Exception as e:
                logger.error(f"on_start 异常: {e}")
                self.runtime.log(f"on_start 异常: {e}")

        return True

    def stop(self):
        """停止脚本执行"""
        if not self._is_running:
            return

        # 调用 on_stop
        if "on_stop" in self._event_handlers:
            try:
                self._event_handlers["on_stop"]()
            except Exception as e:
                logger.error(f"on_stop 异常: {e}")

        self.runtime.stop()
        self._is_running = False
        logger.info("脚本引擎停止")

    def notify_message(self, msg_id: int, data: bytes, channel: int = 1):
        """通知脚本收到报文(由主循环调用)"""
        if not self._is_running:
            return
        if "on_message" in self._event_handlers:
            try:
                self._event_handlers["on_message"](msg_id, data, channel)
            except Exception as e:
                logger.error(f"on_message 异常: {e}")
                self.runtime.log(f"on_message 异常: {e}")

    def check_timers(self):
        """检查定时器(由主循环周期调用)"""
        if self._is_running:
            self.runtime.check_timers()

    def execute_function(self, func_name: str, *args) -> Optional[object]:
        """执行脚本中的指定函数"""
        if func_name not in self._script_globals:
            logger.error(f"脚本中未定义函数: {func_name}")
            return None

        try:
            func = self._script_globals[func_name]
            return func(*args)
        except Exception as e:
            logger.error(f"执行函数 {func_name} 异常: {e}")
            self.runtime.log(f"执行 {func_name} 异常: {e}")
            return None
