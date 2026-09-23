"""
TSMaster CAN设备驱动 - 基于同星连接服务(TsMasterService)

移植自Java TSCan的设备连接逻辑并优化:
- 设备级启动/映射/连接统一由 TsMasterService 管理(全局单例)
- 本驱动只负责单个硬件通道的收发与状态
- 通道号经映射表换算为DLL应用通道号(多设备共享连接时不错位)
- 波特率配置遵循同星要求: 断连->配置->重连 (在服务内完成)
"""

import time
import logging
from typing import Optional

from app.devices.drivers.base import BaseBusDevice, BusState
from app.devices.drivers.ts_service import TsMasterService
from app.devices.drivers.ts_structures import (
    TLIBCAN, TLIBCANFD, TCCANProperty, TCCANFDProperty,
    data_len_to_dlc
)

logger = logging.getLogger(__name__)


class TsMasterCanDevice(BaseBusDevice):
    """
    同星TSMaster单通道CAN设备驱动

    一个实例对应 (设备, 硬件通道):
    - open:  确保服务已start该设备并connect, 按通道参数配置波特率
    - start: 清除接收缓存, 进入RUNNING
    - send/receive: 经映射后的应用通道号收发
    """

    def __init__(self, channel: int = 1, device_index: int = 0,
                 dll_path: str = "", device_model: str = "",
                 serial: str = "", listen_only: bool = False,
                 terminal_resistor: bool = False):
        """
        构造单通道设备驱动

        Args:
            channel: 硬件通道号 (1-based)
            device_index: 设备枚举索引
            dll_path: DLL路径 (预留, 服务内统一查找)
            device_model: 设备型号名 (如 TC1013, 用于映射)
            serial: 设备序列号 (多同型号设备时区分)
            listen_only: 只听模式 (只收不发)
            terminal_resistor: 启用120欧终端电阻
        """
        super().__init__(channel)
        self._device_index = device_index
        self._device_model = device_model
        self._serial = serial
        self._listen_only = listen_only
        self._terminal_resistor = terminal_resistor
        self._svc = TsMasterService.instance()
        self._tx_buf = TLIBCAN()  # 预分配发送缓冲区
        self._app_channel: Optional[int] = None  # 映射后的DLL应用通道号

    @property
    def device_name(self) -> str:
        """设备可读名称"""
        return f"TSMaster({self._device_model or 'CH'}{self.channel})"

    @property
    def app_channel(self) -> int:
        """映射后的DLL应用通道号 (0-based)"""
        if self._app_channel is None:
            self._app_channel = self._svc.get_app_channel(
                self._device_index, self.channel - 1)
        return self._app_channel

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #

    def open(self) -> bool:
        """
        打开设备通道

        流程(对应Java TSCan.openDevice+openChannel):
        1. 服务start该设备(初始化库+自动映射, 已start则跳过)
        2. 服务connect(已连接则跳过)
        3. 按通道参数配置波特率(CAN FD时配置仲裁域+数据域)
        """
        try:
            if self._device_model:
                ok, err = self._svc.start(
                    self._device_model, self._device_index, self._serial)
                if not ok:
                    logger.error(f"设备start失败: {err}")
                    self._state = BusState.ERROR
                    return False
            ok, err = self._svc.connect()
            if not ok:
                logger.error(f"应用连接失败: {err}")
                self._state = BusState.ERROR
                return False

            # 波特率配置 (服务内部执行 断连-配置-重连)
            baud_kbps = self._baud_rate / 1000.0
            if self._is_fd:
                ok, err = self._svc.set_canfd_baudrate(
                    self._device_index, self.channel - 1,
                    baud_kbps, self._data_baud_rate / 1000.0,
                    term_resistor=self._terminal_resistor)
            else:
                ok, err = self._svc.set_can_baudrate(
                    self._device_index, self.channel - 1, baud_kbps,
                    listen_only=self._listen_only,
                    term_resistor=self._terminal_resistor)
            if not ok:
                logger.warning(f"波特率配置失败(继续使用默认): {err}")

            self._app_channel = self._svc.get_app_channel(
                self._device_index, self.channel - 1)
            self._state = BusState.CONNECTED
            logger.info(f"TSMaster通道已打开: {self.device_name} "
                        f"app_ch={self._app_channel} @ {baud_kbps}kbps")
            return True
        except FileNotFoundError as e:
            logger.error(f"TSMaster DLL未找到: {e}")
            self._state = BusState.ERROR
            return False
        except Exception as e:
            logger.error(f"打开TSMaster设备失败: {e}")
            self._state = BusState.ERROR
            return False

    def close(self) -> bool:
        """关闭通道 (应用连接由DeviceManager统一释放)"""
        try:
            if self._state == BusState.RUNNING:
                self.stop()
            self._state = BusState.DISCONNECTED
            logger.info(f"TSMaster通道已关闭: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"关闭TSMaster通道失败: {e}")
            return False

    def start(self) -> bool:
        """启动通道: 清除接收缓存后进入RUNNING"""
        try:
            self._svc.lib.clear_can_receive_buffers(self.app_channel)
            self._state = BusState.RUNNING
            logger.info(f"TSMaster通道已启动: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"启动TSMaster通道失败: {e}")
            return False

    def stop(self) -> bool:
        """停止通道 (回到CONNECTED)"""
        try:
            self._state = BusState.CONNECTED
            logger.info(f"TSMaster通道已停止: {self.device_name}")
            return True
        except Exception as e:
            logger.error(f"停止TSMaster通道失败: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  收发
    # ------------------------------------------------------------------ #

    def send(self, msg_id: int, data: bytes, is_extended: bool = False,
             is_fd: bool = False, is_remote: bool = False,
             is_brs: bool = False) -> bool:
        """发送CAN/CAN FD帧 (经映射通道号)

        is_remote: 经典CAN远程帧 (FD无远程帧, 自动忽略); is_brs: FD加速帧。
        """
        if not self.is_connected or self._listen_only:
            return False
        try:
            lib = self._svc.lib
            if is_fd:
                # FD帧无论长短都走 CANFD 通道 (EDL位), BRS 逐帧指定
                canfd = TLIBCANFD()
                canfd.FIdxChn = self.app_channel
                canfd.FIdentifier = msg_id
                canfd.FDLC = data_len_to_dlc(len(data))
                for i in range(min(64, len(data))):
                    canfd.FData[i] = data[i]
                canfd.FProperties = (
                    TCCANProperty.TX_DATA_EXT_UNLOGGED if is_extended
                    else TCCANProperty.TX_DATA_STD_UNLOGGED)
                canfd.FFDProperties = (
                    TCCANFDProperty.FDCAN_BRS_NO_ERROR if is_brs
                    else TCCANFDProperty.FDCAN_NO_BRS_NO_ERROR)
                result = lib.transmit_canfd_async(canfd)
            else:
                can = self._tx_buf
                can.FIdxChn = self.app_channel
                can.FIdentifier = msg_id
                can.FDLC = len(data)
                if is_remote:
                    # 远程帧: REMOTE 属性, 不带数据场
                    can.FProperties = (
                        TCCANProperty.TX_REMOTE_EXT_UNLOGGED if is_extended
                        else TCCANProperty.TX_REMOTE_STD_UNLOGGED)
                else:
                    can.FProperties = (
                        TCCANProperty.TX_DATA_EXT_UNLOGGED if is_extended
                        else TCCANProperty.TX_DATA_STD_UNLOGGED)
                    for i in range(min(8, len(data))):
                        can.FData[i] = data[i]
                result = lib.transmit_can_async(can)

            if result == 0:
                self._stats.tx_count += 1
                self._stats.last_tx_time = time.time()
                return True
            logger.warning(f"发送失败, 错误码: {result}")
            self._stats.error_count += 1
            return False
        except Exception as e:
            logger.error(f"TSMaster发送失败: {e}")
            self._stats.error_count += 1
            return False

    def receive(self, timeout: float = 0.1) -> Optional[dict]:
        """接收一帧CAN/CAN FD数据"""
        if not self.is_connected:
            return None
        try:
            lib = self._svc.lib
            frames = lib.receive_can_msgs(self.app_channel, max_count=1,
                                          include_tx=True)
            if frames:
                return frames[0]
            fd_frames = lib.receive_canfd_msgs(self.app_channel, max_count=1,
                                               include_tx=True)
            if fd_frames:
                return fd_frames[0]
            return None
        except Exception as e:
            logger.error(f"TSMaster接收异常: {e}")
            return None

    def receive_batch(self, max_count: int = 100,
                      timeout: float = 0.01) -> list[dict]:
        """批量接收CAN/CAN FD帧"""
        if not self.is_connected:
            return []
        try:
            lib = self._svc.lib
            frames = lib.receive_can_msgs(self.app_channel,
                                          max_count=max_count, include_tx=True)
            remaining = max_count - len(frames)
            if remaining > 0:
                fd_frames = lib.receive_canfd_msgs(
                    self.app_channel, max_count=remaining, include_tx=True)
                frames.extend(fd_frames)
            if frames:
                self._stats.rx_count += len(frames)
                self._stats.last_rx_time = time.time()
            return frames
        except Exception as e:
            logger.error(f"TSMaster批量接收异常: {e}")
            return []
