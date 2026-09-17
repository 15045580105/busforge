"""临时自测: DeviceManager + DataHub 链路 (离屏)"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QCoreApplication

from app.core.device_manager import DeviceManager
from app.core.data_hub import DataHub, KIND_FRAME, KIND_SIGNAL, KIND_STATS
from app.models.dbc_model import DbcDatabase, DbcMessage
from app.models.signal import Signal, ByteOrder

app = QCoreApplication(sys.argv)

dm = DeviceManager.instance()
hub = DataHub.instance()
# 设备定义归属工程: 先注册并激活一个工程池
dm.register_project("P1")
dm.set_active_project("P1")

received = []
hub.push.connect(lambda sid, kind, payload: received.append((sid, kind, payload)))

# 1. 设备池与软件通道唯一性
dev = dm.add_device("Virtual", model="V1", index=0)
ok, err = dm.assign_channel("CAN1", dev.device_id, hw_channel=1)
assert ok, err
ok2, err2 = dm.assign_channel("CAN1", dev.device_id, hw_channel=2)
assert not ok2 and "已存在" in err2, (ok2, err2)
assert dm.suggest_channel_key("can") == "CAN2"
print("[OK] 软件通道工程内唯一校验")

# 2. 连接 (仅开硬件不收数)
ok, err = dm.connect_device(dev.device_id)
assert ok, err
inst = dm.get_instance("CAN1")
assert inst is not None
assert not hub.running
print("[OK] 连接仅开硬件, 中台未运行")

# 3. 绑定DBC + 注册订阅
dbc = DbcDatabase(name="TestDb")
dbc.messages.append(DbcMessage(
    name="Engine", message_id=0x100,
    signals=[Signal(name="Spd", start_bit=0, length=8,
                    byte_order=ByteOrder.LITTLE_ENDIAN,
                    factor=0.1, offset=0.0, unit="km/h")]))
dbc.build_index()
assert hub.set_channel_dbc("CAN1", dbc)
hub.register("trace_test", {KIND_FRAME, KIND_STATS}, channels=["CAN1"])
hub.register("sig_test", {KIND_SIGNAL}, channels=["CAN1"],
             filter={'signal_names': {"Spd"}})
print("[OK] 订阅注册 (frame/stats + signal过滤)")

# 4. 运行工程 -> 收数解码推送
ok, err = hub.start_project(["CAN1"])
assert ok, err
assert hub.running and dm.is_acquired(dev.device_id)
inst.inject_frame({"id": 0x100, "data": bytes([100, 0, 0, 0, 0, 0, 0, 0]),
                   "dlc": 8, "timestamp": time.time()})
deadline = time.time() + 3
kinds_seen = set()
while time.time() < deadline and kinds_seen != {KIND_FRAME, KIND_SIGNAL, KIND_STATS}:
    app.processEvents()
    time.sleep(0.01)
    for _, kind, payload in received:
        kinds_seen.add(kind)
assert KIND_FRAME in kinds_seen and KIND_SIGNAL in kinds_seen, kinds_seen
sig_payload = [p for _, k, p in received if k == KIND_SIGNAL][0]
assert abs(sig_payload[0].phys - 10.0) < 1e-6, sig_payload[0]
frame_payload = [p for _, k, p in received if k == KIND_FRAME][0]
assert frame_payload[0].name == "Engine"
print("[OK] 运行态收数+解码+合批推送, 信号物理值=10.0")

# 5. 终止 -> 停推送 + 断开本工程连接
hub.stop_project()
assert not hub.running
assert not dm.is_acquired(dev.device_id)
assert not dm.is_connected(dev.device_id), "终止后应断开连接"
print("[OK] 终止后停推送并断开连接")

# 6. 注销订阅
hub.unregister("trace_test")
hub.unregister("sig_test")
assert hub.get_subscription("trace_test") is None
print("[OK] 订阅注销")

print("ALL PASS")
