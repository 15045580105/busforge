# -*- coding: utf-8 -*-
"""性能探针: 工程运行 + Trace订阅 全链路压测, cProfile 定位 UI 线程热点"""
import cProfile
import pstats
import sys
import time
from io import StringIO

from PySide6.QtWidgets import QApplication

from app.bus.virtual import VirtualBusDevice
from app.core.data_hub import DataHub, KIND_FRAME, KIND_MESSAGE, KIND_STATS


def main():
    app = QApplication(sys.argv)
    hub = DataHub.instance()
    sub = hub.register('bench', kinds={KIND_FRAME, KIND_MESSAGE, KIND_STATS})

    dev = VirtualBusDevice(channel=1, bus_name='bench_bus')
    dev.open()
    dev.start()

    # 直接驱动 _ingest 模拟轮询收数 (500帧/批 x 20批 = 1万帧)
    frames = [{'id': 0x100 + (i % 8), 'data': bytes([i & 0xFF] * 8), 'dlc': 8,
               'is_extended': False, 'is_fd': False, 'is_remote': False,
               'is_brs': False, 'channel': 1, 'timestamp': time.time() + i * 0.002,
               'direction': 'TX' if i % 2 else 'RX'}
              for i in range(500)]

    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    for _ in range(20):
        hub._ingest('CAN1', frames)
        hub._flush_push()
    pr.disable()
    dt = time.perf_counter() - t0
    print(f'ingest+flush 10000帧: {dt*1000:.0f}ms ({dt*1e6/10000:.0f}us/帧)')

    s = StringIO()
    pstats.Stats(pr, stream=s).sort_stats('cumulative').print_stats(18)
    print(s.getvalue())
    return 0


if __name__ == '__main__':
    sys.exit(main())
