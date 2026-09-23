# -*- coding: utf-8 -*-
"""总线报文记录器 (Logger): 订阅中台帧流保存为 ASC/BLF

基于 python-can 的 ASCWriter/BLFWriter, 负责
"启动 -> 逐帧写入(超上限轮转) -> 停止落盘" 链路;
全局配置 (存储根目录/单文件上限/自动记录) 存 AppConfig.logger_*。
"""
import logging
import os
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

import can as pcan

from app.datahub.data_hub import DataHub, KIND_FRAME

logger = logging.getLogger(__name__)

# 单文件大小配置范围 (MB)
MIN_SIZE_MB = 50
MAX_SIZE_MB = 1024


def _app_config():
    """当前 AppConfig (UISettings 绑定的同一实例); 离屏无绑定时 None"""
    from app.common.ui_settings import UISettings
    return getattr(UISettings.instance(), "_config", None)


def logger_root() -> Path:
    """Logger 存储根目录: 配置优先, 空则 保存目录/logger"""
    cfg = _app_config()
    d = (getattr(cfg, "logger_dir", "") or "").strip() if cfg else ""
    if not d:
        from app.common.workspace import WorkspaceManager
        return WorkspaceManager.save_dir() / "logger"
    return Path(d)


def logger_max_bytes() -> int:
    """单文件上限字节数 (配置钳制在 50MB~1GB)"""
    cfg = _app_config()
    mb = getattr(cfg, "logger_max_size_mb", 100) if cfg else 100
    try:
        mb = int(mb)
    except (TypeError, ValueError):
        mb = 100
    mb = max(MIN_SIZE_MB, min(MAX_SIZE_MB, mb))
    return mb * 1024 * 1024


def default_log_path(fmt: str = "asc", project_name: str = "",
                     create: bool = True) -> str:
    """默认保存路径: 根目录/项目名/日期/时分秒.ext (按时间存储);
    create=False 仅计算不建目录 (供界面预览默认路径)"""
    if not project_name:
        from app.devices.device_manager import DeviceManager
        project_name = DeviceManager.instance().active_project_name
    proj = project_name or "default"
    day = time.strftime("%Y-%m-%d")
    d = logger_root() / proj / day
    if create:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Logger目录创建失败: {e}")
    return str(d / f"{time.strftime('%H%M%S')}.{fmt}")


class CanLogger(QObject):
    """报文记录器 (全局单例): 启动后订阅全通道帧, 按所选格式逐帧写入文件"""

    state_changed = Signal(bool, str)   # (是否记录中, 文件路径)
    notice = Signal(str)                # 提示 (如 0 帧未保存)

    _instance: "CanLogger | None" = None

    @classmethod
    def instance(cls) -> "CanLogger":
        if cls._instance is None:
            cls._instance = CanLogger()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._writer = None
        self._path = ""
        self._fmt = "asc"
        self._max_bytes = 0
        self._count = 0
        self._filt: dict | None = None
        self._since_size_check = 0
        self._lock = threading.Lock()
        self._sub_id = f"logger_{id(self):x}"

    @property
    def recording(self) -> bool:
        return self._writer is not None

    @property
    def path(self) -> str:
        return self._path

    @property
    def count(self) -> int:
        return self._count

    def start(self, file_path: str, fmt: str,
              filt: dict | None = None) -> tuple[bool, str]:
        """开始记录; filt: {channels:set|None, ids:set|None, tx:bool, rx:bool};
        失败返回 (False, 原因)"""
        with self._lock:
            if self._writer is not None:
                return False, tr_msg("已在记录中, 请先停止")
            try:
                self._writer = self._open_writer(file_path, fmt)
            except Exception as e:
                self._writer = None
                return False, f"{tr_msg('创建文件失败')}: {e}"
            self._path = file_path
            self._fmt = fmt
            self._max_bytes = logger_max_bytes()
            self._count = 0
            self._filt = filt
            self._since_size_check = 0
        hub = DataHub.instance()
        hub.register(self._sub_id, kinds={KIND_FRAME})
        hub.push.connect(self._on_push)
        logger.info(f"Logger启动: {file_path} ({fmt})")
        self.state_changed.emit(True, file_path)
        return True, ""

    @staticmethod
    def _open_writer(file_path: str, fmt: str):
        if fmt == "blf":
            from can.io import BLFWriter
            return BLFWriter(file_path)
        from can.io import ASCWriter
        return ASCWriter(file_path)

    def stop(self) -> str:
        """停止记录并落盘; 返回文件路径"""
        with self._lock:
            writer, self._writer = self._writer, None
            path = self._path
        if writer is None:
            return ""
        hub = DataHub.instance()
        try:
            hub.push.disconnect(self._on_push)
        except RuntimeError:
            pass
        hub.unregister(self._sub_id)
        try:
            writer.stop()
        except Exception as e:
            logger.error(f"Logger落盘失败: {e}")
        if self._count == 0:
            # 0 帧不保存文件: 删除空文件并提示
            try:
                os.remove(path)
                logger.info(f"Logger 0帧, 空文件已删除: {path}")
            except OSError:
                pass
            self.notice.emit(tr_msg("本次记录 0 帧, 未保存文件"))
        logger.info(f"Logger停止: {path} ({self._count}帧)")
        self.state_changed.emit(False, path)
        return path

    def _on_push(self, sid: str, kind: str, payload):
        """中台帧推送 -> 写入当前写器 (推送线程调用, 加锁保序)"""
        if sid != self._sub_id or kind != KIND_FRAME:
            return
        with self._lock:
            writer = self._writer
            if writer is None:
                return
            for f in payload:
                if not self._accept(f):
                    continue
                try:
                    writer.on_message_received(self._to_can(f))
                except Exception as e:
                    logger.error(f"Logger写帧失败: {e}")
                    return
                self._count += 1
            # 每 128 帧检查一次文件大小, 超上限轮转新文件
            self._since_size_check += len(payload)
            if self._since_size_check >= 128:
                self._since_size_check = 0
                self._rotate_if_needed_locked()

    def _rotate_if_needed_locked(self):
        """超单文件上限: 落盘当前文件并开新文件 (调用方持锁)"""
        try:
            size = os.path.getsize(self._path)
        except OSError:
            return
        if size < self._max_bytes:
            return
        old = self._writer
        try:
            old.stop()
        except Exception as e:
            logger.error(f"Logger轮转落盘失败: {e}")
        new_path = self._next_rotate_path()
        try:
            self._writer = self._open_writer(new_path, self._fmt)
            self._path = new_path
            logger.info(f"Logger轮转新文件: {new_path}")
            self.state_changed.emit(True, new_path)
        except Exception as e:
            self._writer = None
            logger.error(f"Logger轮转开新文件失败: {e}")

    def _next_rotate_path(self) -> str:
        """轮转路径: 同目录 时分秒_序号.ext"""
        p = Path(self._path)
        for i in range(1, 1000):
            cand = p.with_name(f"{time.strftime('%H%M%S')}_{i:02d}{p.suffix}")
            if not cand.exists():
                return str(cand)
        return str(p.with_name(f"{time.strftime('%H%M%S%f')}{p.suffix}"))

    def _accept(self, f) -> bool:
        """记录过滤: 通道/报文ID/方向 (None/空集=不限)"""
        fl = self._filt
        if not fl:
            return True
        chs = fl.get("channels")
        if chs and f.channel_key not in chs:
            return False
        ids = fl.get("ids")
        if ids and f.id not in ids:
            return False
        if f.direction == "TX" and not fl.get("tx", True):
            return False
        if f.direction != "TX" and not fl.get("rx", True):
            return False
        return True

    @staticmethod
    def _to_can(f) -> pcan.Message:
        """FrameDTO -> python-can Message (通道名取尾部数字)"""
        m = re.search(r"\d+", f.channel_key or "")
        return pcan.Message(
            timestamp=f.timestamp,
            arbitration_id=f.id,
            is_extended_id=bool(f.is_extended),
            is_fd=bool(f.is_fd),
            is_rx=f.direction != "TX",
            dlc=f.dlc,
            data=bytes(f.data),
            channel=int(m.group()) if m else 1,
        )


class AutoLogger(QObject):
    """跟随项目运行自动开始记录 (全局配置 logger_auto_start)"""

    _instance: "AutoLogger | None" = None

    @classmethod
    def instance(cls) -> "AutoLogger":
        if cls._instance is None:
            cls._instance = AutoLogger()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        DataHub.instance().running_changed.connect(self._on_running)

    def _on_running(self, running: bool):
        cfg = _app_config()
        lg = CanLogger.instance()
        if not getattr(cfg, "logger_auto_start", False):
            return
        if running:
            if lg.recording:
                return
            ok, err = lg.start(default_log_path("asc"), "asc")
            if not ok:
                logger.error(f"Logger自动启动失败: {err}")
        else:
            # 项目停止 -> 自动停止记录 (仅在跟随模式下由 AutoLogger 启动的)
            if lg.recording:
                lg.stop()


def tr_msg(text: str) -> str:
    """延迟导入 tr, 避免 core 层启动期循环依赖"""
    from app.common.i18n import tr
    return tr(text)
