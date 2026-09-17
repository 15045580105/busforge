"""
WorkspaceManager - 工作空间 / 工程自动持久化 (路径感知)

保存模型 (自动保存):
- 工程在"创建/更改/删除"时即刻落盘, 无需手动保存。
- 每个工程保存为独立 .bfproj 文件; 删除工程即删除该文件。
- 会话索引 workspace.json 记录打开的工程与活动工程, 供启动恢复。
- 保存目录由 AppConfig.save_dir 配置; 为空时默认 = 运行/安装路径
  (即 main.py / app 包所在的工程根目录)。
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 运行/安装路径: app/core/workspace.py -> 上三级为工程根 (busforge/)
APP_RUN_DIR = Path(__file__).resolve().parents[2]

WORKSPACE_NAME = "workspace.json"
PROJECT_SUFFIX = ".bfproj"


def _sanitize_filename(name: str) -> str:
    """把工程名转为安全文件名"""
    safe = re.sub(r'[\\/:*?"<>|]', "_", (name or "project").strip())
    return safe or "project"


class WorkspaceManager:
    """工作空间 / 工程文件读写 (路径感知, 绑定 AppConfig)"""

    _config = None

    # ------------------------------------------------------------------ #
    #  绑定与路径解析
    # ------------------------------------------------------------------ #

    @classmethod
    def bind(cls, config):
        """绑定 AppConfig 以读取 save_dir"""
        cls._config = config

    @classmethod
    def is_bound(cls) -> bool:
        return cls._config is not None

    @classmethod
    def save_dir(cls) -> Path:
        """当前保存目录; 未配置时回退运行/安装路径"""
        raw = getattr(cls._config, "save_dir", "") if cls._config else ""
        if not raw:
            return APP_RUN_DIR
        p = Path(raw)
        return p if p.is_absolute() else (APP_RUN_DIR / p)

    @classmethod
    def default_save_dir(cls) -> Path:
        """默认保存目录 (运行/安装路径)"""
        return APP_RUN_DIR

    @classmethod
    def workspace_file(cls) -> Path:
        return cls.save_dir() / WORKSPACE_NAME

    @classmethod
    def project_file(cls, name: str) -> Path:
        return cls.save_dir() / (_sanitize_filename(name) + PROJECT_SUFFIX)

    # ------------------------------------------------------------------ #
    #  工程文件 (.bfproj)
    # ------------------------------------------------------------------ #

    @classmethod
    def write_project(cls, path, data: dict) -> bool:
        """写单个工程文件"""
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"工程文件写入失败 {path}: {e}")
            return False

    @classmethod
    def remove_project_file(cls, path) -> bool:
        """删除单个工程文件 (删除工程时同步调用)"""
        try:
            path = Path(path) if path else None
            if path and path.exists():
                path.unlink()
                logger.info(f"工程文件已删除: {path}")
                return True
        except Exception as e:
            logger.warning(f"工程文件删除失败 {path}: {e}")
        return False

    # ------------------------------------------------------------------ #
    #  会话索引 (workspace.json)
    # ------------------------------------------------------------------ #

    @classmethod
    def save(cls, projects: list, active_index: int) -> bool:
        """保存会话索引: 全部工程定义 + 活动工程索引"""
        try:
            sd = cls.save_dir()
            sd.mkdir(parents=True, exist_ok=True)
            data = {
                "version": "1.0",
                "save_dir": str(sd),
                "active_index": active_index,
                "projects": projects,
            }
            with open(cls.workspace_file(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(
                f"工作空间已保存: {len(projects)} 个项目 "
                f"(活动={active_index}) -> {cls.workspace_file()}")
            return True
        except Exception as e:
            logger.error(f"工作空间保存失败: {e}")
            return False

    @classmethod
    def load(cls) -> dict:
        """读取会话索引; 不存在或损坏时返回 None"""
        wf = cls.workspace_file()
        if not wf.exists():
            return None
        try:
            with open(wf, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "projects" not in data:
                return None
            logger.info(
                f"工作空间已读取: {len(data.get('projects', []))} 个项目")
            return data
        except Exception as e:
            logger.error(f"工作空间读取失败: {e}")
            return None

    @classmethod
    def clear(cls):
        """清空会话索引文件"""
        try:
            wf = cls.workspace_file()
            if wf.exists():
                wf.unlink()
                logger.info("工作空间会话已清空")
        except Exception as e:
            logger.warning(f"清空工作空间失败: {e}")

    @classmethod
    def exists(cls) -> bool:
        return cls.workspace_file().exists()

