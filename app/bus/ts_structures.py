"""
TSMaster DLL C结构体定义

对应 tosuncan/jna/ 下的:
- TLibCanStructure.java (基类结构)
- TLIBCAN.java (CAN帧)
- TLIBCANFD.java (CAN FD帧)
- TLIBHWInfo.java (硬件信息)
- HardwareMapping.java (设备类型枚举)
- TCCANConstant.java (属性常量)
"""

import ctypes
from ctypes import Structure, c_byte, c_int, c_uint, c_longlong, c_ubyte


# ---- 设备类型常量 (对应 HardwareMapping.java) ----

class TLIBBusToolDeviceType:
    BUS_UNKNOWN_TYPE = 0
    TS_TCP_DEVICE = 1
    XL_USB_DEVICE = 2
    TS_USB_DEVICE = 3
    PEAK_USB_DEVICE = 4
    KVASER_USB_DEVICE = 5
    ZLG_USB_DEVICE = 6
    ICS_USB_DEVICE = 7
    TS_TC1005_DEVICE = 8


class TLIBTSDeviceSubType:
    TS_UNKNOWN_DEVICE = 0
    TSCAN_PRO = 1
    TC1001 = 3
    TL1001 = 4
    TC1011 = 5
    TM5011 = 6
    TC1002 = 7
    TC1014 = 8
    TSCANFD2517 = 9
    TC1026 = 10
    TC1016 = 11
    TC1012 = 12
    TC1013 = 13
    TLog1002 = 14
    TC1034 = 15
    TC1018 = 16
    GW2116 = 17
    TC2115 = 18
    MP1013 = 19
    TC1113 = 20
    TC1114 = 21
    TP1013 = 22
    TC1017 = 23
    TP1018 = 24
    TF10XX = 25
    TL1004_FD_4_LIN_2 = 26
    TE1051 = 27
    TP1051 = 28


# ---- CAN属性常量 (对应 TCCANConstant.java) ----

class TCCANProperty:
    RX_DATA_STD_UNLOGGED = 0x00
    RX_DATA_EXT_UNLOGGED = 0x04
    RX_REMOTE_STD_UNLOGGED = 0x02
    RX_REMOTE_EXT_UNLOGGED = 0x06
    TX_DATA_STD_UNLOGGED = 0x01
    TX_DATA_EXT_UNLOGGED = 0x05
    TX_REMOTE_STD_UNLOGGED = 0x03
    TX_REMOTE_EXT_UNLOGGED = 0x07
    RX_DATA_STD_LOGGED = 0x40
    RX_DATA_EXT_LOGGED = 0x44


class TCCANFDProperty:
    CAN_NO_BRS_NO_ERROR = 0x00
    CAN_NO_BRS_ERROR = 0x04
    CAN_BRS_NO_ERROR = 0x02
    CAN_BRS_ERROR = 0x06
    FDCAN_NO_BRS_NO_ERROR = 0x01
    FDCAN_NO_BRS_ERROR = 0x05
    FDCAN_BRS_NO_ERROR = 0x03
    FDCAN_BRS_ERROR = 0x07


class TCCANFDControllerType:
    CANFD_LFDTCAN = 0        # 普通CAN模式
    CANFD_LFDTISOCAN = 1     # ISO-CANFD模式
    CANFD_LFDTNONISOCAN = 2  # NoISO-CANFD模式


class TCCANFDControllerMode:
    CANFD_LFDMNORMAL = 0       # 正常工作模式
    CANFD_LFDMACKOFF = 1       # 关闭ACK应答模式
    CANFD_LFDMRESTRICTED = 2   # 受限模式


# ---- C结构体定义 ----

class TLIBHWInfo(Structure):
    """硬件设备信息 - 对应 TLIBHWInfo.java"""
    _fields_ = [
        ("FDeviceType", c_int),           # TLIBBusToolDeviceType
        ("FDeviceIndex", c_int),
        ("FVendorName", c_ubyte * 32),
        ("FDeviceName", c_ubyte * 32),
        ("FSerialString", c_ubyte * 64),
    ]


class TLIBCAN(Structure):
    """CAN帧结构 - 对应 TLIBCAN.java / TLibCanStructure.java

    内存布局:
      FIdxChn     (byte)   通道号
      FProperties (byte)   帧属性(TX/RX, STD/EXT, Data/Remote, Error)
      FDLC        (byte)   数据长度码
      FReserved   (byte)   保留(对齐用)
      FIdentifier (int)    CAN ID
      FTimeUS     (longlong) 时间戳(微秒)
      FData       (byte[8]) 数据
    """
    _fields_ = [
        ("FIdxChn", c_byte),
        ("FProperties", c_byte),
        ("FDLC", c_byte),
        ("FReserved", c_byte),       # 对齐
        ("FIdentifier", c_int),
        ("FTimeUS", c_longlong),
        ("FData", c_ubyte * 8),
    ]


class TLIBCANFD(Structure):
    """CAN FD帧结构 - 对应 TLIBCANFD.java

    与TLIBCAN类似但FData为64字节, 多一个FFDProperties字段
    """
    _fields_ = [
        ("FIdxChn", c_byte),
        ("FProperties", c_byte),
        ("FDLC", c_byte),
        ("FFDProperties", c_byte),   # CAN FD额外属性
        ("FIdentifier", c_int),
        ("FTimeUS", c_longlong),
        ("FData", c_ubyte * 64),
    ]


# ---- 辅助函数 ----

def hw_info_to_dict(hw_info: TLIBHWInfo) -> dict:
    """将TLIBHWInfo转为Python dict"""
    vendor = bytes(hw_info.FVendorName).split(b'\x00')[0].decode('utf-8', errors='replace')
    device = bytes(hw_info.FDeviceName).split(b'\x00')[0].decode('utf-8', errors='replace')
    serial = bytes(hw_info.FSerialString).split(b'\x00')[0].decode('utf-8', errors='replace')
    return {
        'device_type': hw_info.FDeviceType,
        'device_index': hw_info.FDeviceIndex,
        'vendor_name': vendor,
        'device_name': device,
        'serial': serial,
        'model': device,
        'index': hw_info.FDeviceIndex,
    }


def can_to_dict(can: TLIBCAN) -> dict:
    """将TLIBCAN转为Python dict"""
    props = can.FProperties
    return {
        'id': can.FIdentifier,
        'data': bytes(can.FData[:can.FDLC]),
        'dlc': can.FDLC,
        'channel': can.FIdxChn + 1,  # 0-based -> 1-based
        'timestamp': can.FTimeUS / 1_000_000.0,  # us -> s
        'is_rx': (props & 0x01) == 0,
        'is_tx': (props & 0x01) != 0,
        'is_extended': (props & 0x04) != 0,
        'is_remote': (props & 0x02) != 0,
        'is_error': (props & 0x80) != 0,
    }


def dict_to_can(d: dict) -> TLIBCAN:
    """将Python dict转为TLIBCAN结构"""
    can = TLIBCAN()
    can.FIdxChn = d.get('channel', 1) - 1  # 1-based -> 0-based
    can.FIdentifier = d.get('id', 0)
    data = d.get('data', b'\x00' * 8)
    can.FDLC = len(data)
    for i in range(min(8, len(data))):
        can.FData[i] = data[i]

    props = TCCANProperty.TX_DATA_STD_UNLOGGED
    if d.get('is_extended', False):
        props |= 0x04
    if d.get('is_remote', False):
        props |= 0x02
    can.FProperties = props
    return can


def canfd_to_dict(canfd: TLIBCANFD) -> dict:
    """将TLIBCANFD转为Python dict"""
    props = canfd.FProperties
    fd_props = canfd.FFDProperties
    # 计算实际数据长度(DLC映射)
    dlc_map = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7,
               8: 8, 9: 12, 10: 16, 11: 20, 12: 24, 13: 32, 14: 48, 15: 64}
    data_len = dlc_map.get(canfd.FDLC, 8)
    return {
        'id': canfd.FIdentifier,
        'data': bytes(canfd.FData[:data_len]),
        'dlc': canfd.FDLC,
        'channel': canfd.FIdxChn + 1,
        'timestamp': canfd.FTimeUS / 1_000_000.0,
        'is_rx': (props & 0x01) == 0,
        'is_tx': (props & 0x01) != 0,
        'is_extended': (props & 0x04) != 0,
        'is_remote': (props & 0x02) != 0,
        'is_error': (props & 0x80) != 0,
        'is_fd': (fd_props & 0x01) != 0,
        'is_brs': (fd_props & 0x02) != 0,
    }


# DLC长度到DLC编码的映射
def data_len_to_dlc(length: int) -> int:
    """数据长度 -> DLC编码"""
    if length <= 8:
        return length
    elif length <= 12:
        return 9
    elif length <= 16:
        return 10
    elif length <= 20:
        return 11
    elif length <= 24:
        return 12
    elif length <= 32:
        return 13
    elif length <= 48:
        return 14
    else:
        return 15
