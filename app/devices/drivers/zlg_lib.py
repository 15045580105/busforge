"""
ZLG(周立功) ZCAN DLL ctypes绑定

移植自 Java ZlgCanLib.java / ZlgApi.java / ZlgCanPropertyManager.java / ZlgCanConstants.java。
通过ctypes直接调用 zlgcan.dll (StdCall)，不依赖任何后端。

DLL路径获取顺序:
1. 构造参数 dll_path
2. 环境变量 ZLG_HOME
3. 系统PATH中的 zlgcan.dll
"""

import os
import ctypes
import logging
from ctypes import (
    c_int, c_uint, c_byte, c_ubyte, c_short, c_uint64, c_char_p, c_void_p,
    POINTER, byref, WinDLL, Structure, CFUNCTYPE
)
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# 状态常量 (对应 ZlgCanConstants.java)
# ============================================================
STATUS_ERR = 0
STATUS_OK = 1
STATUS_ONLINE = 2

# 通道数据类型 (ZCAN_CHANNEL_TYPE)
CHANNEL_TYPE_CAN = 0
CHANNEL_TYPE_CANFD = 1

# 发送回显标志: __pad/flags 等于这两个值表示TX回显帧
SEND_ECHO = 0x20
SEND_BRS = 0x21

# CAN ID 标志位
CAN_ID_MASK = 0x1FFFFFFF
CAN_EFF_FLAG = 0x80000000

# 型号 -> DLL设备类型常量 (ZlgCanConstants 子集, 覆盖常用型号)
ZLG_DEVICE_TYPES = {
    "USBCAN1": 3, "USBCAN2": 4, "USBCAN_I_MINI": 3,
    "USBCAN_2E_U": 21, "USBCAN_4E_U": 31, "USBCAN_8E_U": 34,
    "PCIE_CANFD_100U": 38, "PCIE_CANFD_200U": 39, "PCIE_CANFD_400U": 40,
    "USBCANFD_200U": 41, "USBCANFD_100U": 42, "USBCANFD_MINI": 43,
    "CANFDCOM_100IE": 44, "CANFDNET_200U_TCP": 48, "CANFDNET_200U_UDP": 49,
    "CANFDNET_400U_TCP": 52, "CANFDNET_400U_UDP": 53,
    "USBCANFD_800U": 59, "PCIE_CANFD_200U_MINI": 62,
}


def model_to_device_type(model: str) -> Optional[int]:
    """型号名转DLL设备类型常量, 未知型号返回None"""
    if not model:
        return None
    key = model.strip().upper()
    if key.startswith("ZCAN_"):
        key = key[len("ZCAN_"):]
    return ZLG_DEVICE_TYPES.get(key)


# ============================================================
# 结构体 (字段顺序/对齐与Java JNA一致)
# ============================================================

class ZCANCan(Structure):
    """CAN设备初始化参数"""
    _fields_ = [
        ("accCode", c_uint),    # 验收码, 推荐0
        ("accMask", c_uint),    # 屏蔽码, 推荐0xFFFFFFFF
        ("reserved", c_uint),   # 保留
        ("filter", c_byte),     # 滤波方式
        ("timing0", c_byte),    # 忽略
        ("timing1", c_byte),    # 忽略
        ("mode", c_byte),       # 0-正常模式 1-只听模式
    ]


class ZCANCanFd(Structure):
    """CANFD设备初始化参数"""
    _fields_ = [
        ("accMode", c_uint),    # 验收码
        ("accMask", c_uint),    # 屏蔽码
        ("abitTiming", c_uint), # 忽略
        ("dbitTiming", c_uint), # 忽略
        ("brp", c_uint),        # 波特率预分频, 设0
        ("filter", c_byte),     # 滤波方式
        ("mode", c_byte),       # 0-正常模式 1-只听模式
        ("pad", c_short),       # 对齐
        ("reserved", c_uint),   # 保留
    ]


class ZCANChannelInitConfig(Structure):
    """通道初始化配置 (ZCAN_InitCAN入参)"""
    _fields_ = [
        ("canType", c_uint),    # 0-CAN 1-CANFD (与ZLG沟通: 盒子固定用1)
        ("can", ZCANCan),
        ("canFd", ZCANCanFd),
    ]


class ZCANCanFrame(Structure):
    """CAN帧"""
    _fields_ = [
        ("canId", c_uint),      # 高3位: 扩展/远程/错误标志
        ("canDlc", c_byte),     # 数据长度
        ("__pad", c_byte),      # TX时为回显标志
        ("__res0", c_byte),
        ("__res1", c_byte),
        ("data", c_ubyte * 8),
    ]


class ZCANCanFdFrame(Structure):
    """CAN FD帧"""
    _fields_ = [
        ("canId", c_uint),
        ("len", c_byte),        # 数据长度
        ("flags", c_byte),      # bit0=BRS bit5=TX回显
        ("__res0", c_byte),
        ("__res1", c_byte),
        ("data", c_ubyte * 64),
    ]


class ZCANTransmitData(Structure):
    """CAN发送对象"""
    _fields_ = [
        ("frame", ZCANCanFrame),
        ("transmitType", c_uint),  # 0-正常发送
    ]


class ZCANTransmitFDData(Structure):
    """CAN FD发送对象"""
    _fields_ = [
        ("frame", ZCANCanFdFrame),
        ("transmitType", c_uint),
    ]


class ZCANReceiveData(Structure):
    """CAN接收对象"""
    _fields_ = [
        ("frame", ZCANCanFrame),
        ("timestamp", c_uint64),  # 微秒
    ]


class ZCANReceiveFDData(Structure):
    """CAN FD接收对象"""
    _fields_ = [
        ("frame", ZCANCanFdFrame),
        ("timestamp", c_uint64),
    ]


class ZCANDeviceInfo(Structure):
    """设备信息 (ZCAN_GetDeviceInf出参)"""
    _fields_ = [
        ("hwVersion", c_short),
        ("fwVersion", c_short),
        ("drVersion", c_short),
        ("inVersion", c_short),
        ("irqNum", c_short),
        ("canNum", c_byte),
        ("strSerialNum", c_ubyte * 20),
        ("strHwType", c_ubyte * 40),
        ("reserved", c_short * 4),
    ]


# IProperty 属性接口函数指针
SET_VALUE_FUNC = CFUNCTYPE(c_int, c_char_p, c_char_p)
GET_VALUE_FUNC = CFUNCTYPE(c_char_p, c_char_p)


class ZCANIProperty(Structure):
    """设备属性配置接口 (GetIProperty返回值)"""
    _fields_ = [
        ("SetValue", SET_VALUE_FUNC),
        ("GetValue", GET_VALUE_FUNC),
        ("GetProperties", c_void_p),
    ]


def find_zlg_dll(dll_path: str = "") -> Optional[str]:
    """查找zlgcan.dll路径 (找不到时返回默认名交由加载器按PATH解析)"""
    if dll_path and os.path.exists(dll_path):
        return dll_path
    home = os.environ.get('ZLG_HOME')
    if home:
        p = os.path.join(home, 'zlgcan.dll')
        if os.path.exists(p):
            return p
    for p in [r"C:\Program Files\ZLG\zlgcan.dll",
              r"C:\Program Files (x86)\ZLG\zlgcan.dll",
              r"D:\ZLG\zlgcan.dll",
              r"D:\FlyTest\bin\lib\zlgcan\zlgcan.dll"]:
        if os.path.exists(p):
            return p
    return "zlgcan.dll"


class ZlgLib:
    """
    zlgcan.dll 封装 (对应Java ZlgCanLib + ZlgApi + ZlgCanPropertyManager)

    所有方法带中文注释; 返回None/False表示失败。
    """

    def __init__(self, dll_path: str = ""):
        """构造并延迟加载DLL"""
        self._dll_path = find_zlg_dll(dll_path)
        self._dll = None

    def _load(self) -> bool:
        """加载DLL并设置函数原型"""
        if self._dll:
            return True
        if not self._dll_path:
            raise FileNotFoundError(
                "找不到zlgcan.dll，请安装ZCAN驱动或设置ZLG_HOME环境变量")
        try:
            dll = WinDLL(self._dll_path)
        except OSError as e:
            raise FileNotFoundError(
                f"找不到zlgcan.dll({self._dll_path})，请安装ZCAN驱动"
                f"或设置ZLG_HOME环境变量: {e}")

        dll.ZCAN_OpenDevice.restype = c_void_p
        dll.ZCAN_OpenDevice.argtypes = [c_uint, c_uint, c_uint]
        dll.ZCAN_CloseDevice.restype = c_int
        dll.ZCAN_CloseDevice.argtypes = [c_void_p]
        dll.ZCAN_GetDeviceInf.restype = c_int
        dll.ZCAN_GetDeviceInf.argtypes = [c_void_p, POINTER(ZCANDeviceInfo)]
        dll.ZCAN_IsDeviceOnLine.restype = c_int
        dll.ZCAN_IsDeviceOnLine.argtypes = [c_void_p]
        dll.ZCAN_InitCAN.restype = c_void_p
        dll.ZCAN_InitCAN.argtypes = [
            c_void_p, c_uint, POINTER(ZCANChannelInitConfig)]
        dll.ZCAN_StartCAN.restype = c_int
        dll.ZCAN_StartCAN.argtypes = [c_void_p]
        dll.ZCAN_ResetCAN.restype = c_int
        dll.ZCAN_ResetCAN.argtypes = [c_void_p]
        dll.ZCAN_ClearBuffer.restype = c_int
        dll.ZCAN_ClearBuffer.argtypes = [c_void_p]
        dll.ZCAN_GetReceiveNum.restype = c_int
        dll.ZCAN_GetReceiveNum.argtypes = [c_void_p, c_byte]
        dll.ZCAN_Receive.restype = c_int
        dll.ZCAN_Receive.argtypes = [c_void_p, c_void_p, c_uint, c_int]
        dll.ZCAN_ReceiveFD.restype = c_int
        dll.ZCAN_ReceiveFD.argtypes = [c_void_p, c_void_p, c_uint, c_int]
        dll.ZCAN_Transmit.restype = c_int
        dll.ZCAN_Transmit.argtypes = [c_void_p, POINTER(ZCANTransmitData), c_uint]
        dll.ZCAN_TransmitFD.restype = c_int
        dll.ZCAN_TransmitFD.argtypes = [
            c_void_p, POINTER(ZCANTransmitFDData), c_uint]
        dll.GetIProperty.restype = POINTER(ZCANIProperty)
        dll.GetIProperty.argtypes = [c_void_p]
        dll.ReleaseIProperty.restype = c_int
        dll.ReleaseIProperty.argtypes = [POINTER(ZCANIProperty)]

        self._dll = dll
        logger.info(f"加载ZLG DLL: {self._dll_path}")
        return True

    # ---- 设备级 ----

    def open_device(self, device_type: int, device_index: int):
        """打开设备, 返回设备句柄(None=失败)"""
        self._load()
        handle = self._dll.ZCAN_OpenDevice(device_type, device_index, 0)
        return handle or None

    def close_device(self, device_handle) -> bool:
        """关闭设备"""
        return self._dll.ZCAN_CloseDevice(device_handle) == STATUS_OK

    def get_device_info(self, device_handle) -> Optional[dict]:
        """读取设备信息(序列号/通道数等)"""
        info = ZCANDeviceInfo()
        if self._dll.ZCAN_GetDeviceInf(device_handle, byref(info)) != STATUS_OK:
            return None
        serial = bytes(info.strSerialNum).split(b'\x00')[0].decode(
            'utf-8', errors='replace')
        return {'hw_version': info.hwVersion, 'can_num': info.canNum,
                'serial': serial}

    def is_device_online(self, device_handle) -> bool:
        """设备是否在线"""
        return self._dll.ZCAN_IsDeviceOnLine(device_handle) == STATUS_ONLINE

    def get_iproperty(self, device_handle):
        """获取属性配置接口指针"""
        self._load()
        prop = self._dll.GetIProperty(device_handle)
        return prop if prop else None

    def release_iproperty(self, prop) -> bool:
        """释放属性接口"""
        return self._dll.ReleaseIProperty(prop) == STATUS_OK

    # ---- 属性设置 (对应 ZlgCanPropertyManager) ----

    @staticmethod
    def set_property(prop, channel: int, name: str, value) -> bool:
        """按 通道/属性名 设置设备属性值"""
        path = f"{channel}/{name}".encode('utf-8')
        val = str(value).encode('utf-8')
        return prop.contents.SetValue(path, val) == STATUS_OK

    # ---- 通道级 ----

    def init_can(self, device_handle, channel: int,
                 cfg: ZCANChannelInitConfig):
        """初始化CAN通道, 返回通道句柄(None=失败)"""
        handle = self._dll.ZCAN_InitCAN(
            device_handle, channel, byref(cfg))
        return handle or None

    def start_can(self, channel_handle) -> bool:
        """启动CAN通道"""
        return self._dll.ZCAN_StartCAN(channel_handle) == STATUS_OK

    def reset_can(self, channel_handle) -> bool:
        """复位CAN通道"""
        return self._dll.ZCAN_ResetCAN(channel_handle) == STATUS_OK

    def clear_buffer(self, channel_handle) -> bool:
        """清空接收缓冲"""
        return self._dll.ZCAN_ClearBuffer(channel_handle) == STATUS_OK

    def transmit(self, channel_handle, tx: ZCANTransmitData) -> int:
        """发送1帧CAN, 返回实际发送数"""
        return self._dll.ZCAN_Transmit(channel_handle, byref(tx), 1)

    def transmit_fd(self, channel_handle, tx: ZCANTransmitFDData) -> int:
        """发送1帧CAN FD, 返回实际发送数"""
        return self._dll.ZCAN_TransmitFD(channel_handle, byref(tx), 1)

    def receive(self, channel_handle, max_count: int = 100) -> list[dict]:
        """接收CAN帧列表 (先查数量再读)"""
        num = self._dll.ZCAN_GetReceiveNum(channel_handle, CHANNEL_TYPE_CAN)
        if num <= 0:
            return []
        num = min(num, max_count)
        arr = (ZCANReceiveData * num)()
        got = self._dll.ZCAN_Receive(channel_handle, arr, num, -1)
        frames = []
        for i in range(max(0, got)):
            f = arr[i].frame
            frames.append(_can_frame_to_dict(f, arr[i].timestamp))
        return frames

    def receive_fd(self, channel_handle, max_count: int = 100) -> list[dict]:
        """接收CAN FD帧列表"""
        num = self._dll.ZCAN_GetReceiveNum(channel_handle, CHANNEL_TYPE_CANFD)
        if num <= 0:
            return []
        num = min(num, max_count)
        arr = (ZCANReceiveFDData * num)()
        got = self._dll.ZCAN_ReceiveFD(channel_handle, arr, num, -1)
        frames = []
        for i in range(max(0, got)):
            f = arr[i].frame
            frames.append(_canfd_frame_to_dict(f, arr[i].timestamp))
        return frames


def make_can_id(msg_id: int, is_extended: bool, is_remote: bool = False) -> int:
    """构造SDK帧ID (高3位标志位)"""
    can_id = msg_id & CAN_ID_MASK
    if is_extended:
        can_id |= CAN_EFF_FLAG
    if is_remote:
        can_id |= 0x40000000
    return can_id


def parse_can_id(sdk_id: int) -> tuple[int, bool]:
    """解析SDK帧ID -> (实际ID, 是否扩展帧)"""
    return sdk_id & CAN_ID_MASK, bool(sdk_id & CAN_EFF_FLAG)


def _can_frame_to_dict(f: ZCANCanFrame, timestamp_us: int) -> dict:
    """CAN接收帧转统一dict"""
    actual_id, is_ext = parse_can_id(f.canId)
    dlc = f.canDlc & 0xFF
    return {
        'id': actual_id,
        'data': bytes(f.data[:min(dlc, 8)]),
        'dlc': dlc,
        'is_extended': is_ext,
        'is_fd': False,
        'direction': 'TX' if f.__pad in (SEND_ECHO, SEND_BRS) else 'RX',
        'timestamp': timestamp_us / 1_000_000.0,
    }


def _canfd_frame_to_dict(f: ZCANCanFdFrame, timestamp_us: int) -> dict:
    """CAN FD接收帧转统一dict"""
    actual_id, is_ext = parse_can_id(f.canId)
    length = f.len & 0xFF
    return {
        'id': actual_id,
        'data': bytes(f.data[:min(length, 64)]),
        'dlc': length,
        'is_extended': is_ext,
        'is_fd': True,
        'direction': 'TX' if f.flags in (SEND_ECHO, SEND_BRS) else 'RX',
        'timestamp': timestamp_us / 1_000_000.0,
    }


# 枚举探测常用型号 (ZLG无枚举接口, 按型号+索引探测打开)
ZLG_PROBE_MODELS = [
    "USBCANFD_200U", "USBCANFD_100U", "USBCANFD_MINI", "USBCANFD_800U",
    "USBCAN_2E_U", "USBCAN_4E_U", "USBCAN_8E_U",
    "PCIE_CANFD_100U", "PCIE_CANFD_200U", "PCIE_CANFD_400U",
]


def enumerate_zlg_devices(max_index: int = 2) -> list[dict]:
    """
    枚举本机ZLG设备 (探测式)

    ZLG官方无枚举接口, 此处按 常用型号 x 设备索引 逐个尝试打开:
    打开成功则读取设备信息(序列号/通道数)后立即关闭。
    被其他程序占用的设备会打开失败, 不会出现在结果中。

    Args:
        max_index: 每个型号探测的最大设备索引(不含)

    Returns:
        [{model, device_type, index, serial, can_num}, ...]
    """
    results: list[dict] = []
    seen_serials: set[str] = set()
    lib = ZlgLib()
    try:
        lib._load()
    except FileNotFoundError as e:
        logger.warning(f"ZLG枚举跳过: {e}")
        return results
    for model in ZLG_PROBE_MODELS:
        dtype = ZLG_DEVICE_TYPES.get(model)
        if dtype is None:
            continue
        for index in range(max_index):
            handle = None
            try:
                handle = lib.open_device(dtype, index)
            except Exception as e:
                logger.debug(f"ZLG探测异常 {model}#{index}: {e}")
                break
            if not handle:
                break
            info = lib.get_device_info(handle)
            lib.close_device(handle)
            serial = (info or {}).get('serial', '')
            # 同一物理设备可能被多个type常量打开, 按序列号去重(保留先匹配型号)
            if serial and serial in seen_serials:
                continue
            if serial:
                seen_serials.add(serial)
            results.append({
                'model': model,
                'device_type': dtype,
                'index': index,
                'serial': serial,
                'can_num': (info or {}).get('can_num', 0),
            })
            logger.info(f"ZLG设备枚举到: {model} #{index} "
                        f"serial={(info or {}).get('serial', '')}")
    return results
