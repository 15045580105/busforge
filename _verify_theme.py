"""离屏冒烟: TransmitPanel 主题美化 (soft 语义按钮 / 提示条 / 树交替色 / 像素校验)"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from app.ui.styles import get_theme
from app.core.ui_settings import UISettings
from app.ui.widgets.transmit_panel import TransmitPanel

qss = get_theme("soft_tech")
app.setStyleSheet(qss)
UISettings.instance()
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


# ---- QSS 含新样式 ----
for role in ("success", "danger", "primary", "neutral"):
    check(f'QPushButton[btnRole="{role}"]' in qss, f"QSS 含 {role} soft 按钮")
check("QLabel#hintBar" in qss, "QSS 含提示条 hintBar")
check("alternate-background-color" in qss, "QSS 含树交替行色")

# ---- TransmitPanel 按钮角色 ----
p = TransmitPanel(channel_key="")
roles = [
    (p._start_all_btn, "run"), (p._stop_all_btn, "stop"),
    (p._add_can_btn, "add_can"), (p._add_fd_btn, "add_fd"),
    (p._add_db_btn, "add_db"), (p._add_seq_btn, "add_seq"),
    (p._remove_btn, "remove_item"), (p._up_btn, "move_up"),
    (p._down_btn, "move_down"),
]
for btn, expect in roles:
    check(getattr(btn, "_icon_key", None) == expect, f"工具栏按钮图标={expect}")
check(p._hint_label.objectName() == "hintBar", "提示 label objectName=hintBar")

# 触发列 delegate 自绘按钮 (填满单元格)
p._add_frame(False)
from app.ui.widgets.transmit_panel import _TriggerDelegate
check(isinstance(p._tree.itemDelegateForColumn(0), _TriggerDelegate),
      "触发列 delegate 自绘按钮 (填满单元格)")

# ---- 报文表无进度列 / 信号表6列 / hex dump 单字节编辑 ----
check(p._tree.columnCount() == 9, "报文表 9 列 (无进度列)")
check(p._signal_table.columnCount() == 6, "信号表 6 列 (含起始位/长度)")
p._tree.setCurrentItem(p._tree.topLevelItem(0))
check(p._raw_table.columnCount() == 18, "hex dump 18 列 (地址+16hex+ASCII)")
check(p._raw_table.rowCount() >= 1, "hex dump 行数>=1")
_cell = p._raw_table.item(0, 1)
check(_cell is not None
      and bool(_cell.flags() & Qt.ItemFlag.ItemIsEditable),
      "hex 字节单元格可编辑")
_cell.setText("AB")
p._on_raw_byte_edited(_cell)
check(p._item_meta(p._tree.topLevelItem(0))['data'][0] == 0xAB,
      "单字节编辑回写 0xAB")


# ---- 像素校验: soft 色真正渲染 (非 fallback 通用灰 #e4e2dd) ----
def render_bg(role):
    b = QPushButton("X")
    b.setProperty("btnRole", role)
    b.resize(90, 32)
    b.show()
    app.processEvents()
    img = b.grab().toImage()
    c = img.pixelColor(5, img.height() // 2)   # 左 padding 区取底色
    b.hide()
    return (c.red(), c.green(), c.blue())


EXPECT = {
    "success": (228, 239, 231),   # #e4efe7
    "danger": (245, 230, 228),    # #f5e6e4
    "primary": (230, 238, 246),   # #e6eef6
    "neutral": (235, 233, 228),   # #ebe9e4
}
for role, (er, eg, eb) in EXPECT.items():
    r, g, bl = render_bg(role)
    ok = abs(r - er) < 14 and abs(g - eg) < 14 and abs(bl - eb) < 14
    check(ok, f"{role} 渲染底色~({er},{eg},{eb}) 实际({r},{g},{bl})")

# ---- 生成整面板快照供人工核对 ----
snap = TransmitPanel(channel_key="")
snap._add_frame(False)
snap._add_frame(True)
snap._add_sequence()
snap._add_frame(False)
snap.resize(960, 520)
snap.show()
app.processEvents()
out = os.path.join(HERE, "_transmit_theme.png")
snap.grab().save(out)
print("snapshot ->", out)

print("\n==== %s ====" % ("ALL PASS" if not fails else f"{len(fails)} FAIL"))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
