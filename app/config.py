"""应用配置管理"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path


APP_DATA_DIR = Path.home() / "BusForge"
CONFIG_FILE = APP_DATA_DIR / "config.json"


@dataclass
class DeviceConfig:
    """设备配置"""
    device_type: str = "virtual"       # vector / zlg / ts_master / virtual
    channel: int = 1
    baud_rate: int = 500000
    can_fd: bool = False
    data_baud_rate: int = 2000000
    dll_path: str = ""
    serial_number: str = ""


@dataclass
class UdsConfig:
    """UDS诊断配置"""
    request_id: int = 0x7E0
    response_id: int = 0x7E8
    channel: int = 1
    p2_timeout: float = 1.0           # P2客户端超时(秒)
    p2_star_timeout: float = 5.0      # P2*增强超时(秒)
    s3_timeout: float = 5.0           # S3服务器超时(秒)
    security_dll_path: str = ""        # 27服务安全算法DLL路径
    polling_interval: float = 0.01     # 轮询间隔(秒)


@dataclass
class AppConfig:
    """全局应用配置"""
    theme: str = "dark"
    language: str = "zh_CN"
    number_format: str = "hex"           # hex / dec - 数据视图进制显示
    auto_restore_session: bool = True    # 启动时自动恢复上次工作空间会话
    save_dir: str = ""                   # 工程自动保存目录; 空=运行/安装路径
    devices: list[DeviceConfig] = field(default_factory=lambda: [DeviceConfig()])
    uds: UdsConfig = field(default_factory=UdsConfig)
    log_dir: str = str(APP_DATA_DIR / "logs")
    logger_dir: str = ""                 # Logger 存储根目录; 空=保存目录/logger
    logger_max_size_mb: int = 100        # Logger 单文件上限 (MB, 50~1024)
    logger_auto_start: bool = False      # 跟随项目运行自动开始记录
    dbc_paths: list[str] = field(default_factory=list)
    window_geometry: Optional[dict] = None

    def save(self):
        """持久化配置到文件"""
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls) -> "AppConfig":
        """从文件加载配置"""
        if not CONFIG_FILE.exists():
            return cls()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = cls()
            if "theme" in data:
                config.theme = data["theme"]
            if "language" in data:
                config.language = data["language"]
            if "number_format" in data:
                config.number_format = data["number_format"]
            if "auto_restore_session" in data:
                config.auto_restore_session = data["auto_restore_session"]
            if "save_dir" in data:
                config.save_dir = data["save_dir"]
            if "devices" in data:
                config.devices = [DeviceConfig(**d) for d in data["devices"]]
            if "uds" in data:
                config.uds = UdsConfig(**data["uds"])
            if "log_dir" in data:
                config.log_dir = data["log_dir"]
            if "logger_dir" in data:
                config.logger_dir = data["logger_dir"]
            if "logger_max_size_mb" in data:
                config.logger_max_size_mb = data["logger_max_size_mb"]
            if "logger_auto_start" in data:
                config.logger_auto_start = data["logger_auto_start"]
            if "dbc_paths" in data:
                config.dbc_paths = data["dbc_paths"]
            if "window_geometry" in data:
                config.window_geometry = data["window_geometry"]
            return config
        except Exception:
            return cls()
