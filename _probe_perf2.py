# -*- coding: utf-8 -*-
"""性能探针2: TraceView 显示路径压测 + TransmitPanel 发送路径压测"""
import cProfile
import pstats
import sys
import time
from io import StringIO

from PySide6.QtWidgets import QApplication

from app.core.data_hub import DataHub, KIND_FRAME, KIND_MESSAGE, KIND_STATS
from app.models.dto import FrameDTO
from app.ui.widgets.trace_view import TraceView


def main():
    app = QApplication(sys.argv)
    v = TraceView()

    frames = [FrameDTO(id=0x100 + (i % 8), data=bytes([i & 0xFF] * 8), dlc=8,
                       channel_key='CAN1', timestamp=time.time() + i * 0.002,
                       direction='TX' if i % 2 else 'RX', name='')
              for i in range(500)]

    # 显示路径: 推送缓冲 + 刷新入表 (1万帧, 表上限1万行 -> 含逐出)
    t0 = time.perf_counter()
    for _ in range(20):
        v._frames_buffer.extend(frames)
        v._refresh_table()
    dt = time.perf_counter() - t0
    print(f'Trace入表 10000帧: {dt*1000:.0f}ms ({dt*1e6/10000:.0f}us/帧), '
          f'rows={v._table.topLevelItemCount()}')

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(20):
        v._frames_buffer.extend(frames)
        v._refresh_table()
    pr.disable()
    s = StringIO()
    pstats.Stats(pr, stream=s).sort_stats('tottime').print_stats(15)
    print(s.getvalue())

    # fmt_data 单独计时
    from app.core.ui_settings import UISettings
    ui = UISettings.instance()
    d = bytes(range(8))
    t0 = time.perf_counter()
    for _ in range(10000):
        ui.fmt_data(d)
    print(f'fmt_data x10000: {(time.perf_counter()-t0)*1000:.0f}ms')
    return 0


if __name__ == '__main__':
    sys.exit(main())
