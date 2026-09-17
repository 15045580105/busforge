# -*- coding: utf-8 -*-
"""探针2: 用 ZlgCanDevice 完整封装复现 app 内发送/接收链路
CH1 发 64B FD -> CH2 receive_batch, 打印 is_fd/数据长度
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.bus.zlg import ZlgCanDevice

d1 = ZlgCanDevice(channel=1, device_index=0, device_model="USBCANFD_200U",
                  terminal_resistor=True)
d2 = ZlgCanDevice(channel=2, device_index=0, device_model="USBCANFD_200U",
                  terminal_resistor=True)
d1.set_baud_rate(500000)
d2.set_baud_rate(500000)
d1.set_can_fd(True, 2000000)
d2.set_can_fd(True, 2000000)
assert d1.open() and d1.start(), "d1 open/start failed"
assert d2.open() and d2.start(), "d2 open/start failed"
time.sleep(0.3)

payload = bytes(range(64))
t0 = time.time()
ok = d1.send(0x123, payload, is_extended=False, is_fd=True)
print(f"d1.send(FD 64B) -> {ok}  耗时 {(time.time()-t0)*1000:.0f}ms")
time.sleep(0.5)

for name, d in (("CH1", d1), ("CH2", d2)):
    frames = d.receive_batch(64)
    for f in frames:
        print(f"  {name} id=0x{f['id']:X} dir={f['direction']} "
              f"is_fd={f['is_fd']} dlc={f['dlc']} len(data)={len(f['data'])} "
              f"ts={f['timestamp']:.6f}")
    if not frames:
        print(f"  {name} (无帧)")

d1.stop(); d1.close()
d2.stop(); d2.close()
print("done")
