# -*- coding: utf-8 -*-
"""离屏验证: Trace 分支展开指示符矢量绘制效果 (重影修复后)"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from app.models.dto import FrameDTO, SignalValueDTO
from app.ui.widgets.trace_view import TraceView

app = QApplication([])

tv = TraceView(channel_key="")
tv.resize(800, 300)

t0 = time.time()
tv._t0 = t0
f = FrameDTO(channel_key="CAN1", id=0x100, data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
             dlc=8, direction="RX", timestamp=t0 + 0.001234, name="TestMsg")
for i in range(3):
    f.signals.append(SignalValueDTO(
        name=f"Sig{i}", message_name="TestMsg", channel_key="CAN1",
        phys=1.5 * i, raw=10 * i, unit="V", value_desc="", timestamp=t0))
tv._frames_buffer.append(f)
tv._refresh_table()

item = tv._table.topLevelItem(0)
tv._table.expandItem(item)
app.processEvents()

# 放大截取分支图标区域
pm = tv._table.grab()
pm.save("_branch_probe.png")

# 2x 缩放渲染模拟高DPI清晰度
pm2 = tv._table.grab()
big = pm2.scaled(pm2.width() * 2, pm2.height() * 2)
big.save("_branch_probe_2x.png")

print("time text:", item.text(0))
print("children:", item.childCount())
print("OK")
