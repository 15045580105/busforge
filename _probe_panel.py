# -*- coding: utf-8 -*-
"""探针2: LoggerPanel show 崩溃二分定位"""
import faulthandler
import sys

faulthandler.enable()
sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from app.ui.widgets.logger_panel import LoggerPanel

p = LoggerPanel()
print("ctor ok", flush=True)
p._refresh_root_label()
print("root ok", flush=True)
p._refresh_channels()
print("channels ok", flush=True)
p._refresh_files()
print("files ok", flush=True)
p._show_default_path()
print("default ok", flush=True)
p.retranslate()
print("retranslate ok", flush=True)
p.show()
print("show ok", flush=True)
app.processEvents()
print("PANEL OK")
