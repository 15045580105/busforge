"""
设备管理器 - 按工程分区的设备池 / 软件通道表 / 连接实例的所有者

核心语义:
- 设备与软件通道的"定义"归属工程 (project_id), 每个工程拥有独立的池
- 同一物理设备可在多个工程各自定义不同映射; 通道 key 工程内唯一
- 连接生命周期 = 运行生命周期: 运行工程时统一连接, 停止/切换工程时断开
- connect_channel 仅打开硬件并激活通道, 不收数 (收数由 DataHub 运行态控制)
- 切换工程即断开旧工程全部连接, 因此任一时刻只有活动工程的通道处于连接态,
  连接实例字典可安全地用普通 channel_key 作键 (不存在跨工程同名冲突)
- 定义级读写作用于"活动工程池"; 无活动工程时读返回空、写被拒绝
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal

from app.devices.drivers.base import BaseBusDevice

logger = logging.getLogger(__name__)


class DeviceState(Enum):
    """设备状态"""
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class DeviceInfo:
    """硬件设备元数据"""
    device_id: str                       # 工程内唯一, 如 TSMaster#0
    vendor: str                          # TSMaster / Vector / ZLG / Virtual
    model: str = ""
    serial: str = ""
    index: int = 0
    bus_type: str = "can"                # can / lin
    vendor_params: dict = field(default_factory=dict)
    state: DeviceState = DeviceState.DISCONNECTED

    def to_dict(self) -> dict:
        return {
            'device_id': self.device_id, 'vendor': self.vendor,
            'model': self.model, 'serial': self.serial, 'index': self.index,
            'bus_type': self.bus_type, 'vendor_params': dict(self.vendor_params),
        }


@dataclass
class SoftwareChannel:
    """软件通道 - 工程内唯一的逻辑通道, 映射到 (设备, 硬件通道)"""
    key: str                             # 工程内唯一, 如 CAN1 / LIN1
    device_id: str
    hw_channel: int = 1
    bus_type: str = "can"
    baud_rate: int = 500                 # kbps
    is_fd: bool = False
    data_baud_rate: int = 2000           # kbps
    dbc_path: str = ""
    dbc_paths: list = field(default_factory=list)  # 多DBC导入路径列表 (dbc_path 为首个, 向后兼容)
    enabled: bool = True
    listen_only: bool = False            # 只听模式 (只收不发)
    terminal_resistor: bool = False      # 启用120欧终端电阻

    def to_dict(self) -> dict:
        """序列化为dict (持久化用)"""
        return {
            'key': self.key, 'device_id': self.device_id,
            'hw_channel': self.hw_channel, 'bus_type': self.bus_type,
            'baud_rate': self.baud_rate, 'is_fd': self.is_fd,
            'data_baud_rate': self.data_baud_rate, 'dbc_path': self.dbc_path,
            'dbc_paths': list(self.dbc_paths),
            'enabled': self.enabled, 'listen_only': self.listen_only,
            'terminal_resistor': self.terminal_resistor,
        }


class DeviceManager(QObject):
    """设备管理器 (单例, 按工程分区持有设备池)"""

    # device_id, state值
    device_state_changed = Signal(str, str)
    # channel_key, state值 (disconnected / connected)
    channel_state_changed = Signal(str, str)
    # 设备池/通道表结构变化 (增删/切换工程)
    pool_changed = Signal()
    # 本机发送成功且设备无 TX 自回显 (channel_key, 帧dict[含direction=TX])
    frame_sent = Signal(str, dict)
    # 异步发送失败 (channel_key, 原因) 已节流, 供面板提示
    send_failed = Signal(str, str)

    _instance: Optional['DeviceManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> 'DeviceManager':
        if cls._instance is None:
            cls._instance = DeviceManager()
        return cls._instance

    def __init__(self, parent=None):
        if hasattr(self, '_initialized'):
            return
        super().__init__(parent)
        self._initialized = True

        # project_id -> {'devices': {device_id: DeviceInfo},
        #                'channels': {key: SoftwareChannel}}
        self._pools: dict[str, dict] = {}
        self._active_project: Optional[str] = None
        # project_id -> 工程名 (供设备面板显示"当前是哪个工程")
        self._project_names: dict[str, str] = {}

        # channel_key -> 连接实例 (仅活动工程的通道会被连接)
        self._instances: dict[str, BaseBusDevice] = {}
        self._channel_state: dict[str, str] = {}
        # 被运行中项目占有的设备
        self._acquired: set[str] = set()

        # 保护连接/断开与池结构变更 (读方法不加锁, 依赖GIL原子性, 避免UI阻塞)
        self._lock = threading.RLock()

        # 通道级收发互斥: 串行化 dm-tx 线程的 send() 与主线程的
        # disconnect_channel() 的原生调用, 防止句柄关闭后仍被使用 (原生层闪退)
        self._io_locks: dict[str, threading.Lock] = {}
        self._io_locks_guard = threading.Lock()

        # 异步发送队列 + 单工作线程 (保序):
        # 硬件发送可能阻塞(如ZLG总线无ACK时ZCAN_Transmit阻塞~1.5s/帧),
        # 同步调用会冻死UI线程; 队列有界, 满则丢弃防无限积压
        self._tx_queue: queue.Queue = queue.Queue(maxsize=2000)
        self._tx_fail_ts: dict[str, float] = {}   # 失败信号节流 (每通道2s)
        self._tx_thread = threading.Thread(
            target=self._tx_loop, daemon=True, name="dm-tx")
        self._tx_thread.start()

    # ------------------------------------------------------------------ #
    #  活动工程池解析 (定义级读写的作用域)
    # ------------------------------------------------------------------ #

    @property
    def _devices(self) -> dict[str, DeviceInfo]:
        """活动工程设备表 (无活动工程时返回临时空表, 只读安全)"""
        pool = self._pools.get(self._active_project)
        return pool['devices'] if pool else {}

    @property
    def _channels(self) -> dict[str, SoftwareChannel]:
        """活动工程软件通道表 (无活动工程时返回临时空表, 只读安全)"""
        pool = self._pools.get(self._active_project)
        return pool['channels'] if pool else {}

    @property
    def active_project(self) -> Optional[str]:
        return self._active_project

    @property
    def active_project_name(self) -> str:
        """活动工程名 (无则空串)"""
        if not self._active_project:
            return ""
        return self._project_names.get(self._active_project, "")

    # ------------------------------------------------------------------ #
    #  工程池生命周期
    # ------------------------------------------------------------------ #

    def register_project(self, project_id: str, name: str = ""):
        """为工程建立空设备池 (幂等); 可附带工程名"""
        if not project_id:
            return
        with self._lock:
            if project_id not in self._pools:
                self._pools[project_id] = {'devices': {}, 'channels': {}}
                logger.info(f"工程设备池已注册: {project_id}")
            if name:
                self._project_names[project_id] = name

    def set_project_name(self, project_id: str, name: str):
        """更新工程名 (重命名时调用), 刷新依赖方"""
        with self._lock:
            if project_id in self._pools:
                self._project_names[project_id] = name
                self.pool_changed.emit()

    def unregister_project(self, project_id: str, emit: bool = True):
        """删除工程设备池 (若为活动工程先断开其连接)"""
        with self._lock:
            if project_id not in self._pools:
                return
            if self._active_project == project_id:
                self.disconnect_all_active()
                self._active_project = None
            self._pools.pop(project_id, None)
            self._project_names.pop(project_id, None)
            logger.info(f"工程设备池已移除: {project_id}")
            if emit:
                self.pool_changed.emit()

    def set_active_project(self, project_id: Optional[str], name: str = ""):
        """切换活动工程: 先断开旧工程全部连接, 再切换池指针"""
        with self._lock:
            if project_id and name:
                self._project_names[project_id] = name
            if self._active_project == project_id:
                return
            self.disconnect_all_active()
            self._active_project = (
                project_id if project_id in self._pools else None)
            logger.info(f"活动工程已切换: {self._active_project}")
            self.pool_changed.emit()

    # ------------------------------------------------------------------ #
    #  设备池 (作用域: 活动工程)
    # ------------------------------------------------------------------ #

    def add_device(self, vendor: str, model: str = "", serial: str = "",
                   index: int = 0, bus_type: str = "can",
                   vendor_params: Optional[dict] = None) -> Optional[DeviceInfo]:
        """添加设备到活动工程池, device_id 自动保证工程内唯一"""
        with self._lock:
            if self._active_project is None:
                logger.warning("无活动工程, 拒绝添加设备")
                return None
            devices = self._devices
            base_id = f"{vendor}#{serial}" if serial else f"{vendor}#{index}"
            device_id = base_id
            n = 2
            while device_id in devices:
                device_id = f"{base_id}_{n}"
                n += 1
            info = DeviceInfo(device_id=device_id, vendor=vendor, model=model,
                              serial=serial, index=index, bus_type=bus_type,
                              vendor_params=dict(vendor_params or {}))
            devices[device_id] = info
            logger.info(f"设备已加入工程池: {device_id} "
                        f"(工程 {self._active_project})")
            self.pool_changed.emit()
            return info

    def remove_device(self, device_id: str) -> bool:
        """移除设备: 先断开连接; 绑定到它的通道解绑为未绑定
        (通道归属工程, 不随设备删除)"""
        with self._lock:
            if device_id not in self._devices:
                return False
            self.disconnect_device(device_id)
            for ch in list(self._channels.values()):
                if ch.device_id == device_id:
                    ch.device_id = ""
            self._devices.pop(device_id, None)
            self._acquired.discard(device_id)
            logger.info(f"设备已移出工程池: {device_id} (相关通道已解绑)")
            self.pool_changed.emit()
            return True

    def update_device_params(self, device_id: str, **fields) -> bool:
        """更新设备参数 (连接中禁止)"""
        with self._lock:
            info = self._devices.get(device_id)
            if not info:
                return False
            if info.state == DeviceState.CONNECTED:
                logger.warning(f"设备 {device_id} 连接中, 拒绝修改参数")
                return False
            for k, v in fields.items():
                if hasattr(info, k) and k not in ('device_id', 'state'):
                    setattr(info, k, v)
            self.pool_changed.emit()
            return True

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        return self._devices.get(device_id)

    def list_devices(self) -> list[DeviceInfo]:
        return list(self._devices.values())

    # ------------------------------------------------------------------ #
    #  软件通道表 (key 工程内唯一)
    # ------------------------------------------------------------------ #

    def suggest_channel_key(self, bus_type: str = "can") -> str:
        """建议下一个空闲软件通道名: CAN1 -> CAN2 ..."""
        prefix = "LIN" if bus_type == "lin" else "CAN"
        channels = self._channels
        n = 1
        while f"{prefix}{n}" in channels:
            n += 1
        return f"{prefix}{n}"

    def assign_channel(self, key: str, device_id: str = "", hw_channel: int = 1,
                       bus_type: str = "can", baud_rate: int = 500,
                       is_fd: bool = False, data_baud_rate: int = 2000,
                       dbc_path: str = "") -> tuple[bool, str]:
        """创建软件通道, key 工程内唯一校验; device_id 为空=未绑定设备"""
        with self._lock:
            if self._active_project is None:
                return False, "无活动工程, 无法创建软件通道"
            key = (key or "").strip()
            if not key:
                return False, "软件通道名不能为空"
            channels = self._channels
            if key in channels:
                return False, f"软件通道 '{key}' 已存在, 工程内不可重复"
            device_id = (device_id or "").strip()
            if device_id and device_id not in self._devices:
                return False, f"设备 '{device_id}' 不存在"
            ch = SoftwareChannel(key=key, device_id=device_id,
                                 hw_channel=hw_channel, bus_type=bus_type,
                                 baud_rate=baud_rate, is_fd=is_fd,
                                 data_baud_rate=data_baud_rate, dbc_path=dbc_path)
            channels[key] = ch
            self._channel_state[key] = "disconnected"
            bound = f"{device_id}/HW{hw_channel}" if device_id else "未绑定"
            logger.info(f"软件通道已创建: {key} -> {bound}")
            self.pool_changed.emit()
            return True, ""

    def rename_channel(self, old_key: str, new_key: str) -> tuple[bool, str]:
        """重命名软件通道 (工程内唯一性校验)"""
        with self._lock:
            new_key = (new_key or "").strip()
            if not new_key:
                return False, "软件通道名不能为空"
            channels = self._channels
            if old_key not in channels:
                return False, f"软件通道 '{old_key}' 不存在"
            if new_key != old_key and new_key in channels:
                return False, f"软件通道 '{new_key}' 已存在, 工程内不可重复"
            if self._channel_state.get(old_key) == "connected":
                return False, "通道连接中, 请先断开再重命名"
            ch = channels.pop(old_key)
            ch.key = new_key
            channels[new_key] = ch
            self._channel_state.pop(old_key, None)
            self._channel_state[new_key] = "disconnected"
            self.pool_changed.emit()
            return True, ""

    def update_channel(self, key: str, **fields) -> tuple[bool, str]:
        """更新软件通道参数 (连接中禁止)"""
        with self._lock:
            ch = self._channels.get(key)
            if not ch:
                return False, f"软件通道 '{key}' 不存在"
            if self._channel_state.get(key) == "connected":
                return False, "通道连接中, 请先断开再修改"
            if 'device_id' in fields:
                new_dev = (fields['device_id'] or "").strip()
                if new_dev and new_dev not in self._devices:
                    return False, f"设备 '{new_dev}' 不存在"
                fields['device_id'] = new_dev
            for k, v in fields.items():
                if hasattr(ch, k) and k not in ('key',):
                    setattr(ch, k, v)
            self.pool_changed.emit()
            return True, ""

    def bind_channel(self, key: str, device_id: str,
                     hw_channel: Optional[int] = None) -> tuple[bool, str]:
        """将软件通道绑定到设备的硬件通道 (device_id 为空=解绑)"""
        fields: dict = {'device_id': device_id}
        if hw_channel is not None:
            fields['hw_channel'] = hw_channel
        ok, err = self.update_channel(key, **fields)
        if ok:
            bound = f"{device_id}/HW{fields.get('hw_channel', '')}" \
                if device_id else "未绑定"
            logger.info(f"软件通道绑定更新: {key} -> {bound}")
        return ok, err

    def remove_channel(self, key: str) -> bool:
        with self._lock:
            ch = self._channels.pop(key, None)
            if not ch:
                return False
            inst = self._instances.pop(key, None)
            if inst:
                try:
                    inst.stop()
                    inst.close()
                except Exception:
                    pass
            self._channel_state.pop(key, None)
            self.pool_changed.emit()
            return True

    def get_channel(self, key: str) -> Optional[SoftwareChannel]:
        return self._channels.get(key)

    def list_channels(self) -> list[SoftwareChannel]:
        return list(self._channels.values())

    def channels_of_device(self, device_id: str) -> list[SoftwareChannel]:
        return [c for c in self._channels.values() if c.device_id == device_id]

    def channel_state(self, key: str) -> str:
        return self._channel_state.get(key, "disconnected")

    def channel_bound(self, key: str) -> bool:
        """通道是否已绑定到本工程存在的有效设备"""
        ch = self._channels.get(key)
        return bool(ch and ch.device_id and ch.device_id in self._devices)

    # ------------------------------------------------------------------ #
    #  连接管理 (仅开硬件, 不收数)
    # ------------------------------------------------------------------ #

    def connect_device(self, device_id: str) -> tuple[bool, str]:
        """连接设备: 逐通道连接全部启用通道 (不启动收数)"""
        info = self._devices.get(device_id)
        if not info:
            return False, f"设备 '{device_id}' 不存在"
        if info.state == DeviceState.CONNECTED:
            return True, ""
        channels = [c for c in self.channels_of_device(device_id) if c.enabled]
        if not channels:
            return False, f"设备 '{device_id}' 没有启用的软件通道"
        errors = []
        for ch in channels:
            ok, err = self.connect_channel(ch.key)
            if not ok:
                errors.append(err)
        if errors:
            return False, "; ".join(errors)
        return True, ""

    def connect_channels(self, keys: list[str]) -> tuple[bool, str]:
        """顺序连接一组软件通道 (供异步 worker / 同步运行包装调用)"""
        errors = []
        connected = 0
        for key in keys:
            ch = self._channels.get(key)
            if not ch or not ch.enabled:
                continue
            ok, err = self.connect_channel(key)
            if ok:
                connected += 1
            else:
                errors.append(err)
        if connected == 0 and errors:
            return False, "; ".join(errors)
        return True, "; ".join(errors)

    def connect_channel(self, key: str) -> tuple[bool, str]:
        """连接单个软件通道: 创建实例 -> 打开硬件 -> 激活"""
        with self._lock:
            ch = self._channels.get(key)
            if not ch:
                return False, f"软件通道 '{key}' 不存在"
            if self._channel_state.get(key) == "connected":
                return True, ""
            if not ch.device_id:
                return False, (f"软件通道 '{key}' 未绑定设备, "
                               f"请先在设备管理中为其绑定硬件通道")
            dev = self._devices.get(ch.device_id)
            if not dev:
                return False, (f"软件通道 '{key}' 绑定的设备 '{ch.device_id}' "
                               f"不存在, 请在设备管理中重新绑定")
            try:
                inst = self._create_instance(dev, ch)
                inst.set_baud_rate(ch.baud_rate * 1000)
                if ch.is_fd:
                    inst.set_can_fd(True, ch.data_baud_rate * 1000)
                if not inst.open():
                    raise RuntimeError("open 失败")
                inst.start()
            except Exception as e:
                dev.state = DeviceState.ERROR
                self.device_state_changed.emit(dev.device_id, dev.state.value)
                logger.error(f"通道连接失败: {key}: {e}")
                return False, f"{key}: {e}"
            self._instances[key] = inst
            self._channel_state[key] = "connected"
            dev.state = DeviceState.CONNECTED
            self.channel_state_changed.emit(key, "connected")
            self.device_state_changed.emit(dev.device_id, dev.state.value)
            logger.info(f"通道已连接: {key} -> {dev.device_id}/HW{ch.hw_channel}")
            return True, ""

    def disconnect_device(self, device_id: str) -> bool:
        """断开设备: 逐通道断开"""
        info = self._devices.get(device_id)
        if not info:
            return False
        for ch in self.channels_of_device(device_id):
            self.disconnect_channel(ch.key)
        return True

    def disconnect_all_active(self):
        """断开活动工程的全部连接并清空实例字典"""
        with self._lock:
            for key in list(self._instances.keys()):
                self.disconnect_channel(key)

    def disconnect_channel(self, key: str) -> bool:
        """断开单个软件通道: 停止并销毁实例, 刷新设备状态"""
        with self._lock:
            ch = self._channels.get(key)
            # 与 dm-tx 线程的 send() 互斥: 等在途原生发送完成后
            # 再 stop/close, 避免使用已释放的句柄 (原生层闪退)
            with self._io_lock(key):
                inst = self._instances.pop(key, None)
                if inst:
                    try:
                        inst.stop()
                        inst.close()
                    except Exception:
                        pass
            if self._channel_state.get(key) != "disconnected":
                self._channel_state[key] = "disconnected"
                self.channel_state_changed.emit(key, "disconnected")
            if ch:
                dev = self._devices.get(ch.device_id)
                if dev:
                    remaining = any(
                        self._channel_state.get(c.key) == "connected"
                        for c in self.channels_of_device(dev.device_id))
                    if not remaining and dev.state != DeviceState.DISCONNECTED:
                        dev.state = DeviceState.DISCONNECTED
                        self._acquired.discard(dev.device_id)
                        self.device_state_changed.emit(
                            dev.device_id, dev.state.value)
                        self._release_tsmaster_if_idle()
            logger.info(f"通道已断开: {key}")
            return True

    def _release_tsmaster_if_idle(self):
        """无任何TSMaster通道连接时释放同星应用连接"""
        from app.devices.drivers.ts_master import TsMasterCanDevice
        if any(isinstance(i, TsMasterCanDevice)
               for i in self._instances.values()):
            return
        try:
            from app.devices.drivers.ts_service import TsMasterService
            TsMasterService.instance().disconnect()
        except Exception as e:
            logger.debug(f"释放同星连接跳过: {e}")

    def ensure_connected(self, device_id: str) -> tuple[bool, str]:
        if self.is_connected(device_id):
            return True, ""
        return self.connect_device(device_id)

    def is_connected(self, device_id: str) -> bool:
        info = self._devices.get(device_id)
        return bool(info) and info.state == DeviceState.CONNECTED

    def get_instance(self, channel_key: str) -> Optional[BaseBusDevice]:
        return self._instances.get(channel_key)

    def connected_instances(self) -> dict[str, BaseBusDevice]:
        """当前已连接通道实例 (channel_key -> 实例)"""
        return dict(self._instances)

    def send(self, channel_key: str, msg_id: int, data: bytes,
             is_extended: bool = False, is_fd: bool = False,
             is_remote: bool = False, is_brs: bool = False) -> bool:
        """同步发送帧 - 连接即可发, 不依赖运行态 (is_remote仅经典CAN, is_brs仅FD)

        发送成功且设备不把自发帧回显到接收路径时 (tx_self_echo=False,
        如真实硬件), 发 frame_sent 信号由中台补一条 TX 回显帧,
        保证 Trace 始终能看到本机发送 (CANoe 式)。

        警告: 可能阻塞 (硬件发送超时), UI 高频发送请用 send_async。"""
        # 与 disconnect_channel 互斥: 断开期间句柄正在关闭,
        # 并发 send 会命中已释放的原生句柄导致进程闪退
        with self._io_lock(channel_key):
            inst = self._instances.get(channel_key)
            if not inst:
                return False
            try:
                ok = inst.send(msg_id, data, is_extended, is_fd,
                               is_remote=is_remote, is_brs=is_brs)
            except Exception as e:
                logger.error(f"发送失败({channel_key}): {e}")
                return False
            if ok and not getattr(inst, 'tx_self_echo', False):
                self.frame_sent.emit(channel_key, {
                    'id': msg_id, 'data': bytes(data), 'dlc': len(data),
                    'is_extended': is_extended, 'is_fd': is_fd,
                    'is_remote': is_remote, 'is_brs': is_brs,
                    'channel': getattr(inst, 'channel', 1),
                    'timestamp': time.time(), 'direction': 'TX'})
            return ok

    def _io_lock(self, channel_key: str) -> threading.Lock:
        """取通道级收发锁 (send 与 disconnect_channel 互斥, 保护原生句柄)"""
        with self._io_locks_guard:
            lock = self._io_locks.get(channel_key)
            if lock is None:
                lock = self._io_locks[channel_key] = threading.Lock()
            return lock

    # ------------------------------------------------------------------ #
    #  异步发送 (UI 高频发送专用: 硬件 send 可能阻塞, 如ZLG无ACK时~1.5s/帧)
    # ------------------------------------------------------------------ #

    def send_async(self, channel_key: str, msg_id: int, data: bytes,
                   is_extended: bool = False, is_fd: bool = False,
                   is_remote: bool = False, is_brs: bool = False) -> bool:
        """异步入队发送 (单工作线程保序执行); 返回 False=队列已满丢弃"""
        try:
            self._tx_queue.put_nowait(
                (channel_key, msg_id, bytes(data),
                 is_extended, is_fd, is_remote, is_brs))
            return True
        except queue.Full:
            return False

    def _tx_loop(self):
        """发送工作线程: 逐帧执行; 失败时节流上报 send_failed (UI线程接收)"""
        while True:
            item = self._tx_queue.get()
            try:
                key, msg_id, data, ext, fd, remote, brs = item
                ok = self.send(key, msg_id, data, ext, fd,
                               is_remote=remote, is_brs=brs)
                if not ok:
                    now = time.time()
                    if now - self._tx_fail_ts.get(key, 0) >= 2.0:
                        self._tx_fail_ts[key] = now
                        inst = self._instances.get(key)
                        reason = ("通道未连接" if inst is None
                                  else "硬件无应答 (检查总线连接/对端节点)")
                        self.send_failed.emit(key, reason)
            except Exception as e:
                logger.error(f"异步发送异常: {e}")

    # ------------------------------------------------------------------ #
    #  运行占有 (单运行项目制)
    # ------------------------------------------------------------------ #

    def set_acquired(self, device_ids: list[str], acquired: bool):
        """标记设备被运行中项目占有 (状态灯蓝色)"""
        for did in device_ids:
            if acquired:
                self._acquired.add(did)
            else:
                self._acquired.discard(did)
            info = self._devices.get(did)
            if info:
                self.device_state_changed.emit(did, info.state.value)

    def is_acquired(self, device_id: str) -> bool:
        return device_id in self._acquired

    # ------------------------------------------------------------------ #
    #  持久化 (按工程导出/导入完整定义)
    # ------------------------------------------------------------------ #

    def export_project(self, project_id: str) -> dict:
        """导出指定工程的设备/通道完整定义 (存 .bfproj)"""
        with self._lock:
            pool = self._pools.get(project_id)
            if not pool:
                return {'devices': [], 'channels': []}
            return {
                'devices': [d.to_dict() for d in pool['devices'].values()],
                'channels': [c.to_dict() for c in pool['channels'].values()],
            }

    def import_project(self, project_id: str, data: dict):
        """从工程文件导入设备/通道定义到指定工程池 (不切活动、不碰硬件)"""
        with self._lock:
            self.register_project(project_id)
            pool = self._pools[project_id]
            for d in data.get('devices', []):
                info = DeviceInfo(
                    device_id=d['device_id'], vendor=d.get('vendor', 'Virtual'),
                    model=d.get('model', ''), serial=d.get('serial', ''),
                    index=d.get('index', 0), bus_type=d.get('bus_type', 'can'),
                    vendor_params=dict(d.get('vendor_params', {})))
                pool['devices'][info.device_id] = info
            for c in data.get('channels', []):
                ch = SoftwareChannel(
                    key=c['key'], device_id=c.get('device_id', ''),
                    hw_channel=c.get('hw_channel', 1),
                    bus_type=c.get('bus_type', 'can'),
                    baud_rate=c.get('baud_rate', 500),
                    is_fd=c.get('is_fd', False),
                    data_baud_rate=c.get('data_baud_rate', 2000),
                    dbc_path=c.get('dbc_path', ''),
                    dbc_paths=list(c.get('dbc_paths')
                                  or ([c['dbc_path']] if c.get('dbc_path') else [])),
                    enabled=c.get('enabled', True),
                    listen_only=c.get('listen_only', False),
                    terminal_resistor=c.get('terminal_resistor', False))
                pool['channels'][ch.key] = ch
            logger.info(f"工程定义已导入: {project_id} "
                        f"({len(pool['devices'])}设备/"
                        f"{len(pool['channels'])}通道)")
            self.pool_changed.emit()

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #

    def shutdown(self):
        """应用退出: 断开全部连接"""
        with self._lock:
            for key in list(self._instances.keys()):
                self.disconnect_channel(key)

    # ------------------------------------------------------------------ #
    #  内部: 设备实例工厂
    # ------------------------------------------------------------------ #

    def _create_instance(self, info: DeviceInfo,
                         ch: SoftwareChannel) -> BaseBusDevice:
        vendor = (info.vendor or "").lower()
        try:
            if vendor in ("tsmaster", "ts_master"):
                from app.devices.drivers.ts_master import TsMasterCanDevice
                return TsMasterCanDevice(
                    channel=ch.hw_channel, device_index=info.index,
                    device_model=info.model, serial=info.serial,
                    listen_only=ch.listen_only,
                    terminal_resistor=ch.terminal_resistor)
            if vendor == "vector":
                from app.devices.drivers.vector import VectorCanDevice
                return VectorCanDevice(
                    channel=ch.hw_channel, serial=info.serial)
            if vendor == "zlg":
                from app.devices.drivers.zlg import ZlgCanDevice
                return ZlgCanDevice(
                    channel=ch.hw_channel, device_index=info.index,
                    device_model=info.model,
                    listen_only=ch.listen_only,
                    terminal_resistor=ch.terminal_resistor)
            from app.devices.drivers.virtual import VirtualBusDevice
            return VirtualBusDevice(channel=ch.hw_channel,
                                    bus_name=info.device_id)
        except Exception as e:
            logger.warning(f"创建 {info.vendor} 设备实例失败: {e}, 回退虚拟设备")
            from app.devices.drivers.virtual import VirtualBusDevice
            return VirtualBusDevice(channel=ch.hw_channel,
                                    bus_name=info.device_id)
