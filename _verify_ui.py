"""临时冒烟: 工程私有设备池 + 工程作用域设备面板 + Trace/Signal 纯展示链路 (离屏)"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from app.ui.styles import get_theme
from app.core.device_manager import DeviceManager
from app.core.data_hub import DataHub
from app.models.dbc_model import DbcDatabase, DbcMessage
from app.models.signal import Signal, ByteOrder

app = QApplication(sys.argv)
app.setStyleSheet(get_theme("soft_tech"))

dm = DeviceManager.instance()
hub = DataHub.instance()

# 1. 先建工程并设为活动工程池
from app.ui.project_tree import ProjectTree
tree = ProjectTree()
tree.create_project("P1")
pid = tree.project_manager.active_project.project_id
dm.set_active_project(pid)

# 设备管理侧: 添加物理设备
dev = dm.add_device("Virtual", model="V1", index=0)
assert dev is not None, "活动工程下应能创建设备"

# 2. 工程树侧: 在 CAN 下添加未绑定通道 (直接调底层, 避开引导弹窗)
proj = tree._find_project_item(0)
can_cat = proj.child(0).child(0)     # Source -> CAN
ok, err = dm.assign_channel("CAN1", device_id="", bus_type="can")
assert ok, err
assert not dm.channel_bound("CAN1"), "新建通道应未绑定"
tree._add_channel_node(can_cat, "CAN1")
assert tree.collect_project_channels() == ["CAN1"], tree.collect_project_channels()

# 设备管理侧: 将通道绑定到设备
ok, err = dm.bind_channel("CAN1", dev.device_id, 1)
assert ok, err
assert dm.channel_bound("CAN1"), "绑定后应为已绑定"
print("[OK] 工程树加通道(未绑定) -> 设备管理绑定设备")

# 3. 统一设备管理面板
from app.ui.widgets.device_manage_panel import DeviceManagePanel
dmp = DeviceManagePanel()
dmp.show_device(dev.device_id)
assert dmp._ch_table.rowCount() == 1
print("[OK] 统一设备管理面板: 设备列表/通道表加载")

# 4. 监控面板纯展示
from app.ui.widgets.trace_view import TraceView
from app.ui.widgets.signal_monitor import SignalMonitorPanel
tr = TraceView()
sm = SignalMonitorPanel(channel_key="CAN1")

dbc = DbcDatabase(name="TestDb")
dbc.messages.append(DbcMessage(
    name="Engine", message_id=0x100,
    signals=[Signal(name="Spd", start_bit=0, length=8,
                    byte_order=ByteOrder.LITTLE_ENDIAN,
                    factor=0.1, offset=0.0, unit="km/h")]))
dbc.build_index()
assert hub.set_channel_dbc("CAN1", dbc)
assert sm._signal_tree.topLevelItemCount() == 1

# 勾选信号 -> 订阅
sig_item = sm._signal_tree.topLevelItem(0).child(0)
sig_item.setCheckState(0, sig_item.checkState(0))  # trigger
from PySide6.QtCore import Qt as QtCore_Qt
sm._watched.add("Spd")
sm._rebuild_value_table()
sm._resubscribe()

# 5. 运行工程 -> 推送 -> 面板展示
ok, err = hub.start_project(tree.collect_project_channels())
assert ok, err
assert tree._tree.running_project_index is None  # 徽标由widget设置, 此处未设
inst = dm.get_instance("CAN1")
for i in range(5):
    inst.inject_frame({"id": 0x100, "data": bytes([100 + i, 0, 0, 0, 0, 0, 0, 0]),
                       "dlc": 8, "timestamp": time.time()})
deadline = time.time() + 3
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.01)
    if tr._table.rowCount() > 0 and sm._values.get("Spd"):
        break
assert tr._table.rowCount() > 0, "Trace 应收到帧推送"
assert sm._values.get("Spd") is not None, "Signal 应收到信号推送"
assert abs(sm._values["Spd"].phys - (100 + 4) * 0.1) < 1e-6
print("[OK] 运行->中台推送->Trace/Signal 纯展示 (无解码代码)")

# 6. 终止 -> 断开本工程连接
hub.stop_project()
assert not dm.is_connected(dev.device_id), "终止后应断开连接"
print("[OK] 终止后断开连接")

# 7. 序列化完整定义
data = tree._serialize_project()
assert data['devices'][0]['device_id'] == dev.device_id
assert data['channels'][0]['key'] == "CAN1"
print("[OK] bfproj 存完整定义:",
      [d['device_id'] for d in data['devices']],
      [c['key'] for c in data['channels']])

dm.shutdown()
print("UI SMOKE PASS")
