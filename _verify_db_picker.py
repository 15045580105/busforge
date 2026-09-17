"""离屏冒烟: 数据库报文选择对话框 (通道→数据库→报文 层级 + 搜索 + 选择 + 集成)"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QHeaderView

app = QApplication(sys.argv)

from app.core.ui_settings import UISettings
from app.core.data_hub import DataHub
from app.models.dbc_model import DbcDatabase, DbcMessage
from app.ui.db_message_dialog import DbMessagePickerDialog

ui = UISettings.instance()
hub = DataHub.instance()
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def make_dbc(name, msgs):
    db = DbcDatabase(name=name)
    db.messages.extend(msgs)
    db.build_index()
    return db


def m(name, mid, dlc=8, sender="ECU"):
    return DbcMessage(name=name, message_id=mid, dlc=dlc, sender=sender)


# ---- 构造: CAN1 单库2报文; CAN2 双库 (含一个 FD 报文) ----
hub.set_channel_dbc("CAN1", make_dbc("DbA",
                    [m("Engine", 0x100), m("Brake", 0x200, sender="ESP")]))
hub.add_channel_dbc("CAN2", make_dbc("DbB", [m("Steering", 0x300)]))
hub.add_channel_dbc("CAN2", make_dbc("DbC", [m("Throttle", 0x1A3, dlc=16)]))

allc = hub.all_channel_dbc()
check(set(allc.keys()) == {"CAN1", "CAN2"},
      f"all_channel_dbc 通道={sorted(allc.keys())}")
check(len(allc["CAN2"]) == 2, "CAN2 含 2 个数据库 (原始未合并)")

# ---- 层级构建 ----
dlg = DbMessagePickerDialog(hub, ui)
tree = dlg._tree
check(tree.topLevelItemCount() == 2, "顶层 2 个通道节点")
ch1 = tree.topLevelItem(0)
check(ch1.text(0).startswith("CAN1"), f"通道0={ch1.text(0)}")
check(ch1.childCount() == 1, "CAN1 下 1 个数据库")
db1 = ch1.child(0)
check(db1.text(0).startswith("DbA"), f"数据库={db1.text(0)}")
check(db1.childCount() == 2, "DbA 下 2 报文")
mm0 = db1.child(0)
check(mm0.text(0) == "Engine", f"报文按ID排序, 首行名={mm0.text(0)}")
check(mm0.text(1) == ui.fmt_id(0x100), f"报文ID列={mm0.text(1)}")
check(mm0.text(2) == "8", f"报文DLC列={mm0.text(2)}")
check(mm0.text(3) == "ECU", f"报文发送节点列={mm0.text(3)}")
# ---- 列头: 全部可拖动 + 窗口缩放时等比填满 ----
_hdr = dlg._tree.header()
for _c in range(4):
    check(_hdr.sectionResizeMode(_c) == QHeaderView.ResizeMode.Interactive,
          f"列{_c} Interactive (可拖动列宽)")
dlg._fit_columns_to_viewport(total=1000)
_after = [dlg._tree.columnWidth(_c) for _c in range(4)]
check(sum(_after) == 1000, f"缩放后列宽和==视口宽1000 (实际 {sum(_after)})")
check(abs(_after[0] - 472) <= 3, f"名称列等比放大~472 (实际 {_after[0]})")
check(abs(_after[1] - 163) <= 3, f"ID列等比放大~163 (实际 {_after[1]})")

# ---- 选择 ----
check(dlg.get_selected() is None, "未选中时 get_selected=None")
tree.setCurrentItem(mm0)
sel = dlg.get_selected()
check(sel is not None and sel[0] == "CAN1" and sel[1].name == "Engine",
      f"选中报文 -> ({sel[0]}/{sel[1].name})" if sel else "选中报文 -> None")
tree.setCurrentItem(ch1)
check(dlg.get_selected() is None, "选中通道节点 get_selected=None (仅报文可选)")

# ---- 搜索: 报文名 ----
dlg._on_search("brake")
check(db1.child(0).isHidden() and not db1.child(1).isHidden(),
      "搜 'brake' 仅显 Brake")
# ---- 搜索: 十六进制 ID (0x1A3 -> CAN2/DbC/Throttle) ----
dlg._on_search("0x1a3")
ch2 = tree.topLevelItem(1)
check(ch1.isHidden(), "搜 0x1a3 -> CAN1 隐藏 (无匹配)")
check(not ch2.isHidden(), "搜 0x1a3 -> CAN2 显示")
# ---- 搜索: 十进制 ID (256 = 0x100 -> Engine) ----
dlg._on_search("256")
check(not ch1.isHidden(), "搜 256(=0x100) -> CAN1 显示")
# ---- 清空搜索 ----
dlg._on_search("")
check(not ch1.isHidden() and not ch2.isHidden(), "清空搜索 -> 全部通道恢复显示")

# ---- 空数据 ----
hub.set_channel_dbc("CAN1", None)
hub.remove_channel_dbc("CAN2", "DbB")
hub.remove_channel_dbc("CAN2", "DbC")
check(hub.all_channel_dbc() == {}, "清空后 all_channel_dbc 为空")
dlg2 = DbMessagePickerDialog(hub, ui)
check(dlg2._tree.topLevelItemCount() == 1, "无数据库时显示 1 个提示节点")
check(dlg2.get_selected() is None, "提示节点不可选中")

# ---- 集成: TransmitPanel._add_db_frame (复现并验证空 channel_key 修复) ----
hub.set_channel_dbc("CAN1", make_dbc("DbA", [m("Engine", 0x100)]))
import app.ui.widgets.transmit_panel as tp
from app.ui.widgets.transmit_panel import TransmitPanel


class _FakeDlg:
    """模拟用户在对话框中选中 CAN1/Engine 并确认"""
    def __init__(self, hub_, ui_, parent=None):
        self._sel = ("CAN1", hub_.get_dbc("CAN1").messages[0])

    def exec(self):
        return 1  # QDialog.DialogCode.Accepted

    def get_selected(self):
        return self._sel


tp.DbMessagePickerDialog = _FakeDlg
p = TransmitPanel(channel_key="")   # 独立面板 channel_key 为空 = 原 bug 场景
p._add_db_frame()
check(p._tree.topLevelItemCount() == 1, "从数据库添加帧后 1 行")
meta = p._item_meta(p._tree.topLevelItem(0))
check(meta.get('src') == 'db', f"帧 src=db ({meta.get('src')})")
check(meta.get('channel') == 'CAN1',
      f"帧通道取自报文所在通道=CAN1 (修复空channel_key) ({meta.get('channel')})")
check(meta.get('name') == 'Engine', f"帧名=Engine ({meta.get('name')})")
check(meta.get('id') == 0x100, f"帧 id=0x100 ({meta.get('id')})")

print("\n==== %s ====" % ("ALL PASS" if not fails else f"{len(fails)} FAIL"))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
