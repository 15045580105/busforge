"""
全局变量系统 - Panel和Script共享的变量注册表

所有Panel控件和Script脚本通过此系统注册、读写变量。
支持观察者模式(值变化通知)，实现Panel<->Script双向绑定。
"""

import logging
from typing import Any, Optional, Callable
from enum import Enum, auto

logger = logging.getLogger(__name__)


class VarType(Enum):
    """变量类型"""
    INT = auto()
    FLOAT = auto()
    STR = auto()
    BOOL = auto()
    ENUM = auto()
    ANY = auto()


class AppVariable:
    """应用变量 - 带类型、观察者、元数据"""

    def __init__(self, name: str, value: Any = None, var_type: VarType = VarType.ANY,
                 description: str = "", unit: str = "", min_val=None, max_val=None,
                 enum_values: list | None = None):
        self.name = name
        self.var_type = var_type
        self.description = description
        self.unit = unit
        self.min_val = min_val
        self.max_val = max_val
        self.enum_values = enum_values or []
        self._value = value
        self._observers: list[Callable] = []
        self._read_only = False

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, new_value: Any):
        if self._read_only:
            logger.warning(f"变量 {self.name} 为只读, 不可修改")
            return
        old_value = self._value
        # 类型转换
        new_value = self._coerce_type(new_value)
        # 范围检查
        if self.min_val is not None and new_value < self.min_val:
            new_value = self.min_val
        if self.max_val is not None and new_value > self.max_val:
            new_value = self.max_val
        self._value = new_value
        if old_value != new_value:
            self._notify_observers(old_value, new_value)

    def _coerce_type(self, value: Any) -> Any:
        """类型转换"""
        if self.var_type == VarType.ANY:
            return value
        try:
            if self.var_type == VarType.INT:
                return int(value)
            elif self.var_type == VarType.FLOAT:
                return float(value)
            elif self.var_type == VarType.STR:
                return str(value)
            elif self.var_type == VarType.BOOL:
                return bool(value)
        except (ValueError, TypeError):
            return self._value
        return value

    def on_change(self, callback: Callable):
        """注册值变化回调: callback(name, old_value, new_value)"""
        self._observers.append(callback)

    def remove_observer(self, callback: Callable):
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify_observers(self, old_value: Any, new_value: Any):
        for obs in self._observers:
            try:
                obs(self.name, old_value, new_value)
            except Exception as e:
                logger.error(f"变量 {self.name} 观察者回调异常: {e}")

    def set_read_only(self, ro: bool):
        self._read_only = ro

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'type': self.var_type.name,
            'value': self._value,
            'description': self.description,
            'unit': self.unit,
            'read_only': self._read_only,
        }


class VariableRegistry:
    """
    全局变量注册表

    单例模式，所有Panel和Script共享同一个注册表。
    """

    _instance: Optional['VariableRegistry'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._variables = {}
        return cls._instance

    @classmethod
    def instance(cls) -> 'VariableRegistry':
        if cls._instance is None:
            cls._instance = VariableRegistry()
        return cls._instance

    def create(self, name: str, value: Any = None, var_type: VarType = VarType.ANY,
               description: str = "", **kwargs) -> AppVariable:
        """创建并注册变量"""
        if name in self._variables:
            return self._variables[name]
        var = AppVariable(name, value, var_type, description, **kwargs)
        self._variables[name] = var
        logger.debug(f"变量已注册: {name} = {value} ({var_type.name})")
        return var

    def get(self, name: str) -> Optional[AppVariable]:
        """获取变量"""
        return self._variables.get(name)

    def get_value(self, name: str, default=None) -> Any:
        """获取变量值"""
        var = self._variables.get(name)
        return var.value if var else default

    def set_value(self, name: str, value: Any):
        """设置变量值"""
        var = self._variables.get(name)
        if var:
            var.value = value
        else:
            # 自动创建
            self.create(name, value)

    def remove(self, name: str):
        """移除变量"""
        self._variables.pop(name, None)

    def list_variables(self) -> list[AppVariable]:
        """列出所有变量"""
        return list(self._variables.values())

    def list_names(self) -> list[str]:
        """列出所有变量名"""
        return list(self._variables.keys())

    def clear(self):
        """清空所有变量"""
        self._variables.clear()

    def exists(self, name: str) -> bool:
        return name in self._variables
