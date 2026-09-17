# -*- coding: utf-8 -*-
"""硬件探针: FD帧发送后, 接收方两个接收队列(CAN/CANFD)的实际分布

用法: 需先关闭 BusForge (独占设备), CH1<->CH2 需物理连接(或接真实总线)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.bus.zlg_lib import (
    ZlgLib, ZCANChannelInitConfig, ZCANTransmitFDData,
    ZCANReceiveData, ZCANReceiveFDData,
    CHANNEL_TYPE_CAN, CHANNEL_TYPE_CANFD, make_can_id, SEND_ECHO,
)

lib = ZlgLib()
lib._load()

dev = lib.open_device(41, 0)   # USBCANFD_200U
print("device handle:", dev)
prop = lib.get_iproperty(dev)
handles = []
for ch in (0, 1):
    lib.set_property(prop, ch, "canfd_standard", 0)
    lib.set_property(prop, ch, "canfd_abit_baud_rate", 500000)
    lib.set_property(prop, ch, "canfd_dbit_baud_rate", 2000000)
for ch in (0, 1):
    cfg = ZCANChannelInitConfig()
    cfg.canType = 1
    h = lib.init_can(dev, ch, cfg)
    assert h, f"init_can CH{ch} failed"
    lib.start_can(h)
    lib.clear_buffer(h)
    handles.append(h)
print("channels started")

time.sleep(0.3)

# CH1 发 64 字节 FD 帧
tx = ZCANTransmitFDData()
tx.transmitType = 0
tx.frame.canId = make_can_id(0x123, False, False)
tx.frame.len = 64
tx.frame.flags = SEND_ECHO
for i in range(64):
    tx.frame.data[i] = i
n = lib.transmit_fd(handles[0], tx)
print("transmit_fd(CH1, 64B FD) ->", n)
time.sleep(0.5)

for chname, h in (("CH1", handles[0]), ("CH2", handles[1])):
    ncan = lib._dll.ZCAN_GetReceiveNum(h, CHANNEL_TYPE_CAN)
    nfd = lib._dll.ZCAN_GetReceiveNum(h, CHANNEL_TYPE_CANFD)
    print(f"{chname}: classic队列={ncan}  FD队列={nfd}")
    if ncan:
        arr = (ZCANReceiveData * ncan)()
        got = lib._dll.ZCAN_Receive(h, arr, ncan, 100)
        for i in range(max(0, got)):
            f = arr[i].frame
            print(f"  {chname} [CAN] id=0x{f.canId & 0x1FFFFFFF:X} "
                  f"dlc={f.canDlc & 0xFF} pad={f.__pad & 0xFF:#04x} "
                  f"data={bytes(f.data[:8]).hex(' ')}")
    if nfd:
        arr = (ZCANReceiveFDData * nfd)()
        got = lib._dll.ZCAN_ReceiveFD(h, arr, nfd, 100)
        for i in range(max(0, got)):
            f = arr[i].frame
            ln = min(f.len & 0xFF, 64)
            print(f"  {chname} [FD ] id=0x{f.canId & 0x1FFFFFFF:X} "
                  f"len={f.len & 0xFF} flags={f.flags & 0xFF:#04x} "
                  f"data={bytes(f.data[:ln]).hex(' ')}")

for h in handles:
    lib.reset_can(h)
lib.close_device(dev)
print("done")
