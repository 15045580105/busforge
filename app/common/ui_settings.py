"""
UISettings - 全局UI显示状态单例 (语言 / 进制)

统一状态源: 持有当前语言与数值进制格式, 变更时发出信号,
所有组件订阅本单例, 避免多处状态不一致。

- language: "zh_CN" / "en_US"
- number_format: "hex" / "dec"

状态持久化委托给传入的 AppConfig (bind 后变更即写回并落盘)。
格式化助手 fmt_id / fmt_data / fmt_int 供各数据视图统一调用。
"""

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

# 支持的语言
LANG_ZH = "zh_CN"
LANG_EN = "en_US"

# 支持的进制格式
FMT_HEX = "hex"
FMT_DEC = "dec"


class UISettings(QObject):
    """全局UI显示状态 (单例)"""

    # 语言变更: 新语言代码
    language_changed = Signal(str)
    # 进制变更: 新格式 (hex / dec)
    number_format_changed = Signal(str)

    _instance: Optional['UISettings'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> 'UISettings':
        if cls._instance is None:
            cls._instance = UISettings()
        return cls._instance

    def __init__(self, parent=None):
        if hasattr(self, '_initialized'):
            return
        super().__init__(parent)
        self._initialized = True
        self._language = LANG_ZH
        self._number_format = FMT_HEX
        self._config = None

    # ------------------------------------------------------------------ #
    #  绑定配置 (载入初值 + 变更回写)
    # ------------------------------------------------------------------ #

    def bind(self, config):
        """绑定 AppConfig: 载入已持久化的语言/进制初值"""
        self._config = config
        self._language = getattr(config, "language", LANG_ZH) or LANG_ZH
        self._number_format = getattr(config, "number_format", FMT_HEX) or FMT_HEX
        logger.info(
            f"UISettings 已绑定 (语言={self._language}, "
            f"进制={self._number_format})")

    def _persist(self):
        """把当前状态写回配置并落盘"""
        if self._config is None:
            return
        try:
            self._config.language = self._language
            self._config.number_format = self._number_format
            self._config.save()
        except Exception as e:
            logger.warning(f"UISettings 持久化失败: {e}")

    # ------------------------------------------------------------------ #
    #  语言
    # ------------------------------------------------------------------ #

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, lang: str):
        if lang == self._language:
            return
        self._language = lang
        self._persist()
        logger.info(f"语言已切换: {lang}")
        self.language_changed.emit(lang)

    def toggle_language(self):
        """中 <-> 英 切换"""
        self.set_language(LANG_EN if self._language == LANG_ZH else LANG_ZH)

    # ------------------------------------------------------------------ #
    #  进制
    # ------------------------------------------------------------------ #

    @property
    def number_format(self) -> str:
        return self._number_format

    def is_hex(self) -> bool:
        return self._number_format == FMT_HEX

    def set_number_format(self, fmt: str):
        if fmt == self._number_format:
            return
        self._number_format = fmt
        self._persist()
        logger.info(f"进制已切换: {fmt}")
        self.number_format_changed.emit(fmt)

    def toggle_number_format(self):
        """十六进制 <-> 十进制 切换"""
        self.set_number_format(FMT_DEC if self.is_hex() else FMT_HEX)

    # ------------------------------------------------------------------ #
    #  格式化助手 (供各数据视图统一调用)
    # ------------------------------------------------------------------ #

    def fmt_id(self, value: int) -> str:
        """格式化报文ID"""
        try:
            v = int(value)
        except (ValueError, TypeError):
            return str(value)
        return f"0x{v:X}" if self.is_hex() else str(v)

    def fmt_int(self, value: int) -> str:
        """格式化整数值 (原始值等)"""
        try:
            v = int(value)
        except (ValueError, TypeError):
            return str(value)
        return f"0x{v:X}" if self.is_hex() else str(v)

    def fmt_data(self, data: bytes) -> str:
        """格式化数据字节序列"""
        if not data:
            return ""
        if self.is_hex():
            return " ".join(f"{b:02X}" for b in data)
        return " ".join(str(b) for b in data)
