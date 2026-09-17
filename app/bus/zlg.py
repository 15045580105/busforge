"""
ZLG(周立功) CAN设备驱动 - 基于 zlg_lib.py 绑定

移植自 Java ZlgCan.java 的连接流程并优化:
- open:  打开设备(同设备多通道共享句柄) -> 属性配置(波特率/ISO/电阻)
         -> InitCAN -> 滤波配置 -> StartCAN (对应Java openChannel/startCan)
- start: 清接收缓冲, 进入RUNNING
- stop:  ResetCAN
- close: ResetCAN + 释放共享设备句柄(引用计数归零才CloseDevice)
- send/receive: 经通道句柄收发, 支持CAN/CAN FD与只听模式
"""

import logging
import threading
import time
from typing import Optional

from app.bus.base import BaseBusDevice, BusState
from app.bus.zlg_lib import (
    ZlgLib, ZCANChannelInitConfig, ZCANTransmitData, ZCANTransmitFDData,
    model_to_device_type, make_can_id, STATUS_OK,
    SEND_ECHO, SEND_BRS,
)

logger = logging.getLogger(__name__)


class ZlgCanDevice(BaseBusDevice):
    """
    周立功单通道CAN设备驱动

    一个实例对应 (设备, 硬件通道); 同一物理设备的多通道实例共享设备句柄。
    """

    # 共享设备句柄: (device_type, device_index) -> [handle, refcount]
    _shared_devices: dict = {}
    _shared_lock = threading.RLock()

    # ZLG硬件把自发自帧环回到接收队列 (发送时置 SEND_ECHO/SEND_BRS 标志,
    # 接收路径据此标 direction=TX), 即真实上线确认;
    # DeviceManager 无需再补软件 TX 回显, 否则 Trace 每帧出现两条 TX
    tx_self_echo = True

    def __init__(self, channel: int = 1, device_index: int = 0,
                 dll_path: str = "", device_model: str = "",
                 listen_only: bool = False, terminal_resistor: bool = False,
                 is_fd_standard: bool = True):
        """
        构造单通道设备驱动

        Args:
            channel: 硬件通道号 (1-based)
            device_index: 设备索引
            dll_path: zlgcan.dll路径 (可选)
            device_model: 型号名 (如 USBCANFD_200U, 用于设备类型常量)
            listen_only: 只听模式
            terminal_resistor: 启用内部120欧终端电阻
            is_fd_standard: CAN FD ISO标准 (True=ISO)
        """
        super().__init__(channel)
        self._device_index = device_index
        self._device_model = device_model
        self._listen_only = listen_only
        self._terminal_resistor = terminal_resistor
        self._fd_standard = is_fd_standard
        self._lib = ZlgLib(dll_path)
        self._device_handle = None
        self._channel_handle = None
        self._prop = None
        # 硬件时间戳 -> 纪元秒换算锚点 (ZLG时间戳是设备上电以来的微秒计数,
        # 非纪元时间; 以首帧为锚点换算, 保留帧间微秒级相对精度)
        self._ts_hw0: Optional[float] = None
        self._ts_epoch0: float = 0.0

    @property
    def device_name(self) -> str:
        """设备可读名称"""
        return f"ZLG({self._device_model or 'CAN'} CH{self.channel})"

    # ------------------------------------------------------------------ #
    #  共享设备句柄管理
    # ------------------------------------------------------------------ #

    def _acquire_device(self, device_type: int):
        """获取共享设备句柄 (首次打开, 之后引用计数+1)"""
        key = (device_type, self._device_index)
        with self._shared_lock:
            entry = self._shared_devices.get(key)
            if entry and entry[0]:
                entry[1] += 1
                return entry[0]
            handle = self._lib.open_device(device_type, self._device_index)
            if not handle:
                return None
            self._shared_devices[key] = [handle, 1]
            logger.info(f"ZLG设备已打开: type={device_type} "
                        f"index={self._device_index}")
            return handle

    def _release_device(self, device_type: int):
        """释放共享设备句柄 (引用计数归零才真正关闭)"""
        key = (device_type, self._device_index)
        with self._shared_lock:
            entry = self._shared_devices.get(key)
            if not entry:
                return
            entry[1] -= 1
            if entry[1] <= 0:
                self._lib.close_device(entry[0])
                self._shared_devices.pop(key, None)
                logger.info(f"ZLG设备已关闭: type={device_type} "
                            f"index={self._device_index}")

    # ------------------------------------------------------------------ #
    #  生命周期 (对应Java openDevice/openChannel/closeChannel)
    # ------------------------------------------------------------------ #

    def open(self) -> bool:
        """打开设备通道: 开设备->属性配置->InitCAN->滤波->StartCAN"""
        device_type = model_to_device_type(self._device_model)
        if device_type is None:
            logger.error(f"ZLG型号未知: {self._device_model} "
                         f"(请在设备参数中填写如 USBCANFD_200U)")
            self._state = BusState.ERROR
            return False
        try:
            self._device_handle = self._acquire_device(device_type)
            if not self._device_handle:
                self._state = BusState.ERROR
                return False
            self._device_type = device_type
            ch_idx = self.channel - 1

            # 属性配置 (InitCAN之前): ISO标准 + 仲裁域/数据域波特率
            self._prop = self._lib.get_iproperty(self._device_handle)
            if self._prop:
                self._lib.set_property(
                    self._prop, ch_idx, "canfd_standard",
                    0 if self._fd_standard else 1)
                self._lib.set_property(
                    self._prop, ch_idx, "canfd_abit_baud_rate",
                    int(self._baud_rate))
                self._lib.set_property(
                    self._prop, ch_idx, "canfd_dbit_baud_rate",
                    int(self._data_baud_rate))

            # 通道初始化 (与ZLG沟通: 盒子固定canType=1)
            cfg = ZCANChannelInitConfig()
            cfg.canType = 1
            mode = 1 if self._listen_only else 0
            cfg.can.mode = mode
            cfg.canFd.mode = mode
            self._channel_handle = self._lib.init_can(
                self._device_handle, ch_idx, cfg)
            if not self._channel_handle:
                logger.error(f"ZCAN_InitCAN失败: {self.device_name}")
                self._state = BusState.ERROR
                return False

            # 滤波配置 (InitCAN之后): 清滤波->标准帧全收->扩展帧全收->生效
            if self._prop:
                self._lib.set_property(self._prop, ch_idx, "filter_clear", 0)
                self._lib.set_property(self._prop, ch_idx, "filter_mode", 0)
                self._lib.set_property(self._prop, ch_idx, "filter_start", "0")
                self._lib.set_property(
                    self._prop, ch_idx, "filter_end", "0x7FF")
                self._lib.set_property(self._prop, ch_idx, "filter_mode", 1)
                self._lib.set_property(self._prop, ch_idx, "filter_start", "0")
                self._lib.set_property(
                    self._prop, ch_idx, "filter_end", "0x1FFFFFFF")
                self._lib.set_property(self._prop, ch_idx, "filter_ack", 0)
                # 内部终端电阻
                self._lib.set_property(
                    self._prop, ch_idx, "initenal_resistance",
                    1 if self._terminal_resistor else 0)

            if not self._lib.start_can(self._channel_handle):
                logger.error(f"ZCAN_StartCAN失败: {self.device_name}")
                self._state = BusState.ERROR
                return False

            self._state = BusState.CONNECTED
            logger.info(f"ZLG通道已打开: {self.device_name}")
            return True
        except FileNotFoundError as e:
            logger.error(f"ZLG DLL未找到: {e}")
            self._state = BusState.ERROR
            return False
        except Exception as e:
            logger.error(f"打开ZLG设备失败: {e}")
            self._state = BusState.ERROR
            return False

    def close(self) -> bool:
        """关闭通道并释放共享设备句柄"""
        try:
            if self._channel_handle:
                self._lib.reset_can(self._channel_handle)
                self._channel_handle = None
            if self._prop:
                self._lib.release_iproperty(self._prop)
                self._prop = None
            if self._device_handle:
                self._release_device(getattr(self, '_device_type', 41))
                self._device_handle = None
            self._state = BusState.DISCONNECTED
            logger.info(f"ZLG通道已关闭: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"关闭ZLG通道失败: {e}")
            return False

    def start(self) -> bool:
        """启动通道: 清接收缓冲后进入RUNNING"""
        try:
            if self._channel_handle:
                self._lib.clear_buffer(self._channel_handle)
            self._ts_hw0 = None   # 新一轮运行重建时间锚点
            self._state = BusState.RUNNING
            logger.info(f"ZLG通道已启动: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"启动ZLG通道失败: {e}")
            return False

    def stop(self) -> bool:
        """停止通道 (ResetCAN, 回到CONNECTED)"""
        try:
            if self._channel_handle:
                self._lib.reset_can(self._channel_handle)
            self._state = BusState.CONNECTED
            logger.info(f"ZLG通道已停止: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"停止ZLG通道失败: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  收发 (对应Java sendCanMessage / read线程)
    # ------------------------------------------------------------------ #

    def send(self, msg_id: int, data: bytes, is_extended: bool = False,
             is_fd: bool = False, is_remote: bool = False,
             is_brs: bool = False) -> bool:
        """发送CAN/CAN FD帧 (只听模式禁止发送)

        is_remote: 经典CAN远程帧 (FD无远程帧, 自动忽略);
        is_brs: CAN FD加速帧 (BRS 位, 逐帧指定, 与通道波特率配置无关)。
        """
        if not self.is_connected or not self._channel_handle:
            return False
        if self._listen_only:
            return False
        try:
            # 远程帧只有经典CAN有 (FD协议无RTR), 仅经典CAN时置 RTR 位
            can_id = make_can_id(msg_id, is_extended,
                                 is_remote and not is_fd)
            if is_fd:
                # FD帧无论长短都必须走 transmit_fd (EDL位), 不能降级到经典发送
                tx = ZCANTransmitFDData()
                tx.transmitType = 0
                tx.frame.canId = can_id
                tx.frame.len = len(data)
                tx.frame.flags = SEND_BRS if is_brs else SEND_ECHO
                for i in range(min(64, len(data))):
                    tx.frame.data[i] = data[i]
                sent = self._lib.transmit_fd(self._channel_handle, tx)
            else:
                tx = ZCANTransmitData()
                tx.transmitType = 0
                tx.frame.canId = can_id
                tx.frame.canDlc = min(8, len(data))
                tx.frame.__pad = SEND_ECHO
                # 远程帧不带数据场
                if not is_remote:
                    for i in range(min(8, len(data))):
                        tx.frame.data[i] = data[i]
                sent = self._lib.transmit(self._channel_handle, tx)
            if sent > 0:
                self._stats.tx_count += 1
                import time as _t
                self._stats.last_tx_time = _t.time()
                return True
            self._stats.error_count += 1
            return False
        except Exception as e:
            logger.error(f"ZLG发送失败: {e}")
            self._stats.error_count += 1
            return False

    def receive(self, timeout: float = 0.1) -> Optional[dict]:
        """接收一帧CAN/CAN FD数据"""
        frames = self.receive_batch(max_count=1, timeout=timeout)
        return frames[0] if frames else None

    def _hw_ts_to_epoch(self, ts: float, now: float) -> float:
        """ZLG硬件时间戳(设备上电起微秒/1e6=秒)换算为纪元秒;
        部分固件直接给UTC纪元秒则原样透传"""
        if ts <= 0:
            return now
        if ts > 1_000_000_000:   # 已是纪元秒 (约2001年之后), 不换算
            return ts
        if self._ts_hw0 is None:
            self._ts_hw0 = ts
            self._ts_epoch0 = now
            return now
        return self._ts_epoch0 + (ts - self._ts_hw0)

    def receive_batch(self, max_count: int = 100,
                      timeout: float = 0.01) -> list[dict]:
        """批量接收CAN/CAN FD帧"""
        if not self.is_connected or not self._channel_handle:
            return []
        try:
            frames = self._lib.receive(self._channel_handle, max_count)
            if len(frames) < max_count:
                frames.extend(self._lib.receive_fd(
                    self._channel_handle, max_count - len(frames)))
            if frames:
                self._stats.rx_count += len(frames)
                self._stats.last_rx_time = time.time()
                now = time.time()
                for f in frames:
                    f['timestamp'] = self._hw_ts_to_epoch(
                        f.get('timestamp', 0.0), now)
            return frames
        except Exception as e:
            logger.error(f"ZLG批量接收异常: {e}")
            return []
