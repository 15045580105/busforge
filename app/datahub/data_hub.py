"""
数据中台 DataHub - 轮询收帧 / 解析层解码 / 订阅注册 / 合批推送

核心语义:
- 仅"运行中"轮询 DeviceManager 的通道实例 (运行工程才收数)
- 监控界面创建即 register(分类型), 关闭即 unregister, 推送随之启停
- 解码按需: 仅当存在 message/signal 订阅者时调用解析层 CanCodec
- 展示层只消费 DTO, 不做任何解码/过滤计算
"""

import logging
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer

from app.devices.device_manager import DeviceManager
from app.models.dto import FrameDTO, SignalValueDTO, StatsDTO, DeviceStateDTO
from app.models.dbc_model import DbcDatabase
from app.protocol.can_codec import CanCodec

logger = logging.getLogger(__name__)

# 订阅类型常量
KIND_FRAME = "frame"          # 原始帧 (可选带解码名)
KIND_MESSAGE = "message"      # 解码后报文 (含信号)
KIND_SIGNAL = "signal"        # 信号值更新
KIND_STATS = "stats"          # 通道统计
KIND_STATE = "device_state"   # 设备/通道状态


class Subscription:
    """订阅句柄"""

    def __init__(self, subscriber_id: str, kinds: set,
                 channels: Optional[list] = None,
                 filter: Optional[dict] = None):
        self.subscriber_id = subscriber_id
        self.kinds = set(kinds)
        self.channels = list(channels) if channels else None  # None = 全部
        self.filter = dict(filter or {})
        # filter: {'message_ids': set[int], 'signal_names': set[str]}

    def matches_channel(self, channel_key: str) -> bool:
        return self.channels is None or channel_key in self.channels

    def matches_message_id(self, msg_id: int) -> bool:
        ids = self.filter.get('message_ids')
        return ids is None or not ids or msg_id in ids

    def matches_signal(self, name: str) -> bool:
        names = self.filter.get('signal_names')
        return names is None or not names or name in names


class DataHub(QObject):
    """数据中台 (单例)"""

    # subscriber_id, kind, payload(list[DTO])
    push = Signal(str, str, object)
    # 运行态变化
    running_changed = Signal(bool)
    # channel_key, DbcDatabase - 供信号树等只读元数据展示
    dbc_changed = Signal(str, object)

    _instance: Optional['DataHub'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> 'DataHub':
        if cls._instance is None:
            cls._instance = DataHub()
        return cls._instance

    def __init__(self, parent=None):
        if hasattr(self, '_initialized'):
            return
        super().__init__(parent)
        self._initialized = True

        self._dm = DeviceManager.instance()
        self._subs: dict[str, Subscription] = {}
        # channel_key -> CanCodec (解析层实例由中台持有)
        self._codecs: dict[str, CanCodec] = {}
        # channel_key -> 合并后的 DbcDatabase (供面板只读展示)
        self._dbc: dict[str, object] = {}
        # channel_key -> list[DbcDatabase] (一个通道可导入多个 DBC)
        self._dbc_list: dict[str, list] = {}
        # channel_key -> {signal_name: SignalValueDTO} 最新值缓存
        self._signal_cache: dict[str, dict[str, SignalValueDTO]] = {}
        # channel_key -> {msg_id: FrameDTO} 最后报文缓存
        self._last_msg: dict[str, dict[int, FrameDTO]] = {}
        # channel_key -> StatsDTO
        self._stats_cache: dict[str, StatsDTO] = {}

        self._running = False
        self._project_channels: list[str] = []
        self._running_devices: list[str] = []
        # 暂停轮询的通道 (如UDS诊断独占接收时)
        self._paused_channels: set[str] = set()

        # (sid, kind) -> 待推送payload列表
        self._pending: dict[tuple, list] = {}

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(10)
        self._poll_timer.timeout.connect(self._poll)

        self._push_timer = QTimer(self)
        self._push_timer.setInterval(30)
        self._push_timer.timeout.connect(self._flush_push)
        self._push_timer.start()

        # 设备状态转发
        self._dm.device_state_changed.connect(self._on_device_state)
        self._dm.channel_state_changed.connect(self._on_channel_state)
        # 本机发送回显 (硬件无 TX 自回显时由 DeviceManager 上报)
        self._dm.frame_sent.connect(self._on_frame_sent)

    # ------------------------------------------------------------------ #
    #  订阅注册 (分类型)
    # ------------------------------------------------------------------ #

    def register(self, subscriber_id: str, kinds, channels=None,
                 filter=None) -> Subscription:
        """创建监控界面即注册并开始推送"""
        sub = Subscription(subscriber_id, set(kinds), channels, filter)
        self._subs[subscriber_id] = sub
        logger.info(f"中台订阅注册: {subscriber_id} kinds={sub.kinds} "
                    f"channels={sub.channels}")
        return sub

    def unregister(self, subscriber_id: str):
        """监控界面关闭即注销, 停止推送"""
        if self._subs.pop(subscriber_id, None):
            for key in [k for k in self._pending if k[0] == subscriber_id]:
                self._pending.pop(key, None)
            logger.info(f"中台订阅注销: {subscriber_id}")

    def update_subscription(self, subscriber_id: str, kinds=None,
                            channels=None, filter=None):
        """重新订阅 (如面板内切换通道/勾选信号)"""
        sub = self._subs.get(subscriber_id)
        if not sub:
            return
        if kinds is not None:
            sub.kinds = set(kinds)
        if channels is not None:
            sub.channels = list(channels) if channels else None
        if filter is not None:
            sub.filter = dict(filter)

    def get_subscription(self, subscriber_id: str) -> Optional[Subscription]:
        return self._subs.get(subscriber_id)

    # ------------------------------------------------------------------ #
    #  解析层 (DBC) 管理
    # ------------------------------------------------------------------ #

    def set_channel_dbc(self, channel_key: str, dbc) -> bool:
        """通道绑定DBC数据库 (整体替换为单个; 解析层归位: UI不再持有codec)"""
        if dbc is None:
            self._dbc_list.pop(channel_key, None)
            self._rebuild_merged_dbc(channel_key)
            self.dbc_changed.emit(channel_key, None)
            return False
        self._dbc_list[channel_key] = [dbc]
        merged = self._rebuild_merged_dbc(channel_key)
        logger.info(f"通道 {channel_key} 绑定DBC: {dbc.name} "
                    f"({dbc.message_count}报文/{dbc.signal_count}信号)")
        self.dbc_changed.emit(channel_key, merged)
        return True

    def add_channel_dbc(self, channel_key: str, dbc) -> bool:
        """通道追加一个DBC (同名替换), 重算合并库"""
        if dbc is None:
            return False
        lst = self._dbc_list.setdefault(channel_key, [])
        lst[:] = [d for d in lst if d.name != dbc.name]
        lst.append(dbc)
        merged = self._rebuild_merged_dbc(channel_key)
        logger.info(f"通道 {channel_key} 追加DBC: {dbc.name} "
                    f"({dbc.message_count}报文/{dbc.signal_count}信号, "
                    f"共{len(lst)}个)")
        self.dbc_changed.emit(channel_key, merged)
        return True

    def remove_channel_dbc(self, channel_key: str, dbc_name: str) -> bool:
        """通道移除指定名称的DBC, 重算合并库"""
        lst = self._dbc_list.get(channel_key, [])
        kept = [d for d in lst if d.name != dbc_name]
        if len(kept) == len(lst):
            return False
        self._dbc_list[channel_key] = kept
        merged = self._rebuild_merged_dbc(channel_key)
        logger.info(f"通道 {channel_key} 移除DBC: {dbc_name} (剩{len(kept)}个)")
        self.dbc_changed.emit(channel_key, merged)
        return True

    def list_channel_dbc(self, channel_key: str) -> list:
        """通道已导入的DBC列表 (供工程树展示/删除)"""
        return list(self._dbc_list.get(channel_key, []))

    def all_channel_dbc(self) -> dict:
        """全部通道的原始DBC列表 (仅含已绑定DBC的通道)

        返回 {channel_key: [DbcDatabase, ...]}, 供跨通道报文选择使用
        (如仿真发送"从数据库添加帧"按 通道→数据库→报文 层级枚举)。
        """
        return {k: list(v) for k, v in self._dbc_list.items() if v}

    def _rebuild_merged_dbc(self, channel_key: str):
        """将通道多个DBC合并为单一库供解码/展示; 空则清除codec"""
        lst = self._dbc_list.get(channel_key, [])
        if not lst:
            self._codecs.pop(channel_key, None)
            self._dbc.pop(channel_key, None)
            return None
        merged = DbcDatabase(name=" + ".join(d.name for d in lst))
        for d in lst:
            merged.nodes.extend(d.nodes)
            merged.messages.extend(d.messages)
        merged.build_index()
        self._dbc[channel_key] = merged
        self._codecs[channel_key] = CanCodec(merged)
        self._signal_cache.setdefault(channel_key, {})
        return merged

    def get_dbc(self, channel_key: str):
        return self._dbc.get(channel_key)

    def get_codec(self, channel_key: str):
        """获取通道解析层codec (发送侧编码用)"""
        return self._codecs.get(channel_key)

    def load_channel_dbc_file(self, channel_key: str, path: str) -> bool:
        """从文件加载DBC并追加到通道, 同时回写软件通道 dbc_paths"""
        try:
            from app.protocol.dbc_parser import DbcParser
            dbc = DbcParser().parse_file(path)
        except Exception as e:
            logger.error(f"DBC加载失败({path}): {e}")
            return False
        ok = self.add_channel_dbc(channel_key, dbc)
        if ok:
            self._sync_dbc_paths(channel_key)
        return ok

    def unload_channel_dbc(self, channel_key: str, dbc_name: str) -> bool:
        """从通道移除指定DBC并回写软件通道 dbc_paths"""
        ok = self.remove_channel_dbc(channel_key, dbc_name)
        if ok:
            self._sync_dbc_paths(channel_key)
        return ok

    def _sync_dbc_paths(self, channel_key: str):
        """将通道当前DBC来源路径回写到软件通道配置 (持久化)"""
        paths = [d.source_path for d in self._dbc_list.get(channel_key, [])
                 if d.source_path]
        self._dm.update_channel(
            channel_key, dbc_paths=paths,
            dbc_path=paths[0] if paths else "")

    # ------------------------------------------------------------------ #
    #  运行控制
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        return self._running

    @property
    def project_channels(self) -> list[str]:
        return list(self._project_channels)

    def begin_polling(self, channel_keys: list[str]) -> tuple[bool, str]:
        """开始轮询收数与推送 (假定通道已连接; 连接由运行流程异步完成)"""
        if self._running:
            self.stop_polling()
        errors = []
        device_ids = []
        valid_channels = []
        for key in channel_keys:
            ch = self._dm.get_channel(key)
            if not ch:
                errors.append(f"通道 {key} 不存在")
                continue
            valid_channels.append(key)
            if ch.device_id not in device_ids:
                device_ids.append(ch.device_id)
        if not valid_channels:
            return False, "; ".join(errors) if errors else "无有效通道"
        self._project_channels = valid_channels
        self._running_devices = device_ids
        self._dm.set_acquired(device_ids, True)
        # 丢弃启动前积压帧 (发送面板可在运行前自动连接发帧):
        # Trace 以启动为零点计时, 旧时间戳残留会拉偏相对时间轴
        for key in valid_channels:
            inst = self._dm.get_instance(key)
            if inst is not None:
                try:
                    inst.receive_batch(4096)
                except Exception:
                    pass
        self._running = True
        self._poll_timer.start()
        logger.info(f"工程运行: channels={valid_channels} devices={device_ids}")
        self.running_changed.emit(True)
        return True, "; ".join(errors)

    def stop_polling(self):
        """终止轮询: 停收数与推送 (连接是否断开由调用方决定)"""
        if not self._running:
            return
        self._running = False
        self._poll_timer.stop()
        self._pending.clear()
        self._dm.set_acquired(self._running_devices, False)
        logger.info(f"工程终止轮询: channels={self._project_channels}")
        self._project_channels = []
        self._running_devices = []
        self.running_changed.emit(False)

    def start_project(self, channel_keys: list[str]) -> tuple[bool, str]:
        """同步包装: 连接全部通道 -> 开始轮询 (供脚本/同步调用方)"""
        c_ok, c_err = self._dm.connect_channels(channel_keys)
        p_ok, p_err = self.begin_polling(channel_keys)
        combined = "; ".join(x for x in (c_err, p_err) if x)
        return (c_ok and p_ok), combined

    def stop_project(self):
        """同步包装: 停轮询 -> 断开活动工程全部连接"""
        self.stop_polling()
        self._dm.disconnect_all_active()

    def set_channel_paused(self, channel_key: str, paused: bool):
        """暂停/恢复指定通道轮询 (UDS同步收发时避免抢帧)"""
        if paused:
            self._paused_channels.add(channel_key)
        else:
            self._paused_channels.discard(channel_key)
        logger.info(f"通道轮询{'暂停' if paused else '恢复'}: {channel_key}")

    # ------------------------------------------------------------------ #
    #  缓存查询 (展示层只读)
    # ------------------------------------------------------------------ #

    def get_signal_cache(self, channel_key: str) -> dict[str, SignalValueDTO]:
        return dict(self._signal_cache.get(channel_key, {}))

    def get_last_messages(self, channel_key: str) -> dict[int, FrameDTO]:
        return dict(self._last_msg.get(channel_key, {}))

    def get_stats(self, channel_key: str) -> Optional[StatsDTO]:
        return self._stats_cache.get(channel_key)

    # ------------------------------------------------------------------ #
    #  收数与解码
    # ------------------------------------------------------------------ #

    def _poll(self):
        if not self._running:
            return
        for key in self._project_channels:
            if key in self._paused_channels:
                continue
            inst = self._dm.get_instance(key)
            if not inst:
                continue
            try:
                frames = inst.receive_batch(64)
            except Exception:
                frames = []
            if frames:
                self._ingest(key, frames)
            # 统计缓存
            st = inst.stats
            self._stats_cache[key] = StatsDTO(
                channel_key=key, tx_count=st.tx_count, rx_count=st.rx_count,
                error_count=st.error_count, bus_load=st.bus_load)

    def _on_frame_sent(self, channel_key: str, frame: dict):
        """本机发送回显: 走与接收同一 ingest 管线 (解码/分发/缓存),
        帧 dict 已带 direction=TX; 未运行或非工程通道不入 Trace (与 RX 一致)"""
        if not self._running or channel_key not in self._project_channels:
            return
        self._ingest(channel_key, [frame])

    def _need_decode(self, channel_key: str) -> bool:
        for sub in self._subs.values():
            if (KIND_MESSAGE in sub.kinds or KIND_SIGNAL in sub.kinds) \
                    and sub.matches_channel(channel_key):
                return True
        return False

    def _ingest(self, channel_key: str, frames: list[dict]):
        codec = self._codecs.get(channel_key)
        need_decode = codec is not None and self._need_decode(channel_key)
        updated_signals: list[SignalValueDTO] = []
        last_msgs = self._last_msg.setdefault(channel_key, {})
        sig_cache = self._signal_cache.setdefault(channel_key, {})

        dtos: list[FrameDTO] = []
        for f in frames:
            dto = FrameDTO(
                channel_key=channel_key,
                id=f.get('id', 0),
                data=bytes(f.get('data', b"")),
                dlc=f.get('dlc', 8),
                is_extended=f.get('is_extended', False),
                is_fd=f.get('is_fd', False),
                direction=f.get('direction', 'RX'),
                timestamp=f.get('timestamp', 0.0),
            )
            if need_decode:
                try:
                    msg = codec.decode_frame({
                        'id': dto.id, 'data': dto.data, 'dlc': dto.dlc,
                        'is_extended': dto.is_extended, 'is_fd': dto.is_fd,
                        'channel': 1, 'timestamp': dto.timestamp,
                    })
                    dto.name = msg.message_name
                    for sig in msg.signals:
                        sv = SignalValueDTO(
                            name=sig.name, message_name=msg.message_name,
                            channel_key=channel_key,
                            phys=sig.physical_value, raw=sig.raw_value,
                            unit=sig.unit,
                            value_desc=sig.get_value_description(sig.raw_value)
                            if sig.value_descriptions else "",
                            timestamp=dto.timestamp)
                        dto.signals.append(sv)
                        sig_cache[sig.name] = sv
                        updated_signals.append(sv)
                except Exception as e:
                    logger.debug(f"解码失败({channel_key}/0x{dto.id:X}): {e}")
            last_msgs[dto.id] = dto
            dtos.append(dto)

        # 按订阅分发到待推送队列
        for sub in self._subs.values():
            if not sub.matches_channel(channel_key):
                continue
            if KIND_FRAME in sub.kinds:
                self._pending.setdefault(
                    (sub.subscriber_id, KIND_FRAME), []).extend(dtos)
            if KIND_MESSAGE in sub.kinds:
                matched = [d for d in dtos
                           if d.name or sub.matches_message_id(d.id)]
                if matched:
                    self._pending.setdefault(
                        (sub.subscriber_id, KIND_MESSAGE), []).extend(matched)
            if KIND_SIGNAL in sub.kinds and updated_signals:
                matched = [s for s in updated_signals
                           if sub.matches_signal(s.name)]
                if matched:
                    self._pending.setdefault(
                        (sub.subscriber_id, KIND_SIGNAL), []).extend(matched)

    # ------------------------------------------------------------------ #
    #  合批推送
    # ------------------------------------------------------------------ #

    def _flush_push(self):
        # 统计类订阅: 按推送周期合批
        if self._running:
            stats_subs = [s for s in self._subs.values()
                          if KIND_STATS in s.kinds]
            if stats_subs:
                for sub in stats_subs:
                    payload = [st for key, st in self._stats_cache.items()
                               if sub.matches_channel(key)]
                    if payload:
                        self._pending.setdefault(
                            (sub.subscriber_id, KIND_STATS), []).extend(payload)

        if not self._pending:
            return
        pending, self._pending = self._pending, {}
        for (sid, kind), payload in pending.items():
            if sid in self._subs and payload:
                # 报文流按时间戳排序: 多通道/发送回显乱序合批,
                # 不排序会导致 Trace 相对时间出现负值/跳变
                if kind == KIND_FRAME and len(payload) > 1:
                    payload.sort(key=lambda d: d.timestamp)
                self.push.emit(sid, kind, payload)

    # ------------------------------------------------------------------ #
    #  状态转发
    # ------------------------------------------------------------------ #

    def _on_device_state(self, device_id: str, state: str):
        dto = DeviceStateDTO(
            device_id=device_id, state=state,
            acquired=self._dm.is_acquired(device_id))
        for sub in self._subs.values():
            if KIND_STATE in sub.kinds:
                self._pending.setdefault(
                    (sub.subscriber_id, KIND_STATE), []).append(dto)

    def _on_channel_state(self, channel_key: str, state: str):
        ch = self._dm.get_channel(channel_key)
        dto = DeviceStateDTO(
            device_id=ch.device_id if ch else "",
            state=self._dm.get_device(ch.device_id).state.value
            if ch and self._dm.get_device(ch.device_id) else "",
            acquired=self._dm.is_acquired(ch.device_id) if ch else False,
            channel_key=channel_key, channel_state=state)
        for sub in self._subs.values():
            if KIND_STATE in sub.kinds:
                self._pending.setdefault(
                    (sub.subscriber_id, KIND_STATE), []).append(dto)
