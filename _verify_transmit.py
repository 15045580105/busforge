"""离屏冒烟: 仿真发送面板 / 树 i18n / 数据库图标分层 / IG+Generator 移除"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.core.ui_settings import UISettings
from app.ui.project_tree import (
    ProjectTree, PANEL_TYPES, PANEL_ID_PREFIX, CATEGORY_LIKE, ICON_DRAWERS)
from app.ui.widgets.transmit_panel import TransmitPanel

ui = UISettings.instance()
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


# ---- IG/Generator 已移除 ----
check("ig" not in PANEL_TYPES and "generator" not in PANEL_TYPES,
      "PANEL_TYPES 不含 ig/generator")
check("ig" not in PANEL_ID_PREFIX and "generator" not in PANEL_ID_PREFIX,
      "PANEL_ID_PREFIX 不含 ig/generator")
check("channel_ig" not in ICON_DRAWERS and "channel_gen" not in ICON_DRAWERS,
      "ICON_DRAWERS 不含 channel_ig/channel_gen")
check("transmit" in PANEL_TYPES, "PANEL_TYPES 含 transmit")
check("transmit" in ICON_DRAWERS, "ICON_DRAWERS 含 transmit 图标 (齐平)")

# ---- 数据库图标上下分层 ----
check(ICON_DRAWERS["channel_dbc"] is not ICON_DRAWERS["dbc_instance"],
      "channel_dbc 与 dbc_instance 图标不同")
check("channel_dbc" in CATEGORY_LIKE, "channel_dbc 为半透明容器节点")

# ---- 项目树 + 仿真发送 ----
tree = ProjectTree()
check(not hasattr(tree, "ig_requested") and not hasattr(tree, "generator_requested"),
      "ProjectTree 无 ig/generator 信号")
tree.create_project("T1")

created = []
tree.panel_created.connect(lambda pid, t, w, c: created.append((pid, t)))


from PySide6.QtCore import Qt
UR = Qt.ItemDataRole.UserRole


def find_category2(ptype):
    root = tree._find_project_item(0)
    for j in range(root.childCount()):
        child = root.child(j)
        if child.data(0, UR) in ("monitor", "sim"):
            for k in range(child.childCount()):
                g = child.child(k)
                if g.data(0, UR) == ptype:
                    return g
    return None


def find_group(role):
    root = tree._find_project_item(0)
    for j in range(root.childCount()):
        child = root.child(j)
        if child.data(0, UR) == role:
            return child
    return None


sim_node = find_group("sim")
mon_node = find_group("monitor")
src_node = find_group("source")
trace_cat = find_category2("trace")
check(sim_node is not None and mon_node is not None,
      "仿真 与 Monitor 同级存在")
check(sim_node.text(0) == "仿真", f"仿真节点名={sim_node.text(0)}")
for t in ("transmit", "panel", "script"):
    c = find_category2(t)
    check(c is not None and c.parent() is sim_node,
          f"{t} 挂在 仿真 下")
for t in ("trace", "signal", "graphy", "uds"):
    c = find_category2(t)
    check(c is not None and c.parent() is mon_node,
          f"{t} 挂在 Monitor 下")

cat = find_category2("transmit")
check(cat is not None and cat.text(0) == "仿真发送",
      f"仿真下有仿真发送分类 (text={cat.text(0) if cat else None})")

tree.create_panel("transmit")
check(len(created) == 1 and created[0][1] == "transmit", "create_panel 发射 transmit")
check(created[0][0].startswith("Transmit_"), f"实例 id 前缀 Transmit_ ({created[0][0]})")
inst = cat.child(0)
check(inst.data(0, UR + 1) == "panel_instance", "实例节点挂 仿真 分类下")
check(inst.text(0) == "仿真发送_1", f"中文实例显示名={inst.text(0)}")
check(inst.data(0, UR + 2) == "Transmit_1", "实例 panel_id 仍为 ascii")

# ---- 树 i18n ----
ui.set_language("en_US")
check(cat.text(0) == "Transmit", f"切英文后分类={cat.text(0)}")
check(sim_node.text(0) == "Simulation", f"切英文后仿真节点={sim_node.text(0)}")
check(mon_node.text(0) == "Monitor", f"切英文后监控节点={mon_node.text(0)}")
check(src_node.text(0) == "Bus", f"切英文后总线节点={src_node.text(0)}")
check(trace_cat.text(0) == "Trace", f"切英文后报文监控分类={trace_cat.text(0)}")
check(inst.text(0) == "Transmit_1", f"切英文后实例节点={inst.text(0)}")
ui.set_language("zh_CN")
check(cat.text(0) == "仿真发送", f"切回中文分类={cat.text(0)}")
check(sim_node.text(0) == "仿真", f"切回中文仿真节点={sim_node.text(0)}")
check(mon_node.text(0) == "监控", f"切回中文监控节点={mon_node.text(0)}")
check(src_node.text(0) == "总线", f"切回中文总线节点={src_node.text(0)}")
check(trace_cat.text(0) == "报文监控", f"切回中文报文监控分类={trace_cat.text(0)}")
check(inst.text(0) == "仿真发送_1", f"切回中文实例节点={inst.text(0)}")

# ---- TransmitPanel 行为 ----
p = TransmitPanel(channel_key="")
check(p._tree.topLevelItemCount() == 0, "初始空列表")
p._add_frame(False)
check(p._tree.topLevelItemCount() == 1, "添加自定义帧后 1 行")
p._add_sequence()
check(p._tree.topLevelItemCount() == 2, "添加序列后 2 行")
seq_item = p._tree.topLevelItem(1)
p._tree.setCurrentItem(seq_item)
p._add_frame(True)  # 作为序列成员
check(seq_item.childCount() == 1, "序列下嵌套成员帧")
check(len(p._item_meta(seq_item)['members']) == 1, "序列 members 登记 1 个")
# 列数
check(p._tree.columnCount() == 9, "9 列 (触发..间隔)")
# 语言切换重译按钮
ui.set_language("en_US")
check(p._start_all_btn.text() == "Start", f"英文启动按钮={p._start_all_btn.text()}")
check(p._tree.headerItem().text(8) == "Period(ms)",
      f"英文周期列={p._tree.headerItem().text(8)}")
ui.set_language("zh_CN")
check(p._start_all_btn.text() == "启动", f"中文启动按钮={p._start_all_btn.text()}")
check(p._tree.headerItem().text(8) == "周期(ms)",
      f"中文周期列={p._tree.headerItem().text(8)}")

# ---- 数据区 hex 直写 (选中字节后直接键入, 两位一字节自动前进) ----
from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeyEvent

frame_item = p._tree.topLevelItem(0)
p._tree.setCurrentItem(frame_item)
meta0 = p._item_meta(frame_item)
check(p._raw_table.rowCount() == 1, "数据区 8 字节 1 行")
p._raw_table._apply_byte_selection(0, 0)


def type_hex(ch):
    ev = QKeyEvent(QEvent.Type.KeyPress, ord(ch.upper()),
                   Qt.KeyboardModifier.NoModifier, ch)
    p._raw_table.keyPressEvent(ev)


type_hex("1")
type_hex("a")
check(meta0['data'][0] == 0x1A, f"键入 1a 后字节0=0x{meta0['data'][0]:02X}")
check(p._raw_table.item(0, 1).text() == "1A", "字节0 显示 1A")
type_hex("F")
type_hex("f")
check(meta0['data'][1] == 0xFF, f"键入 Ff 后字节1=0x{meta0['data'][1]:02X}")
rng = p._raw_table.selected_byte_range()
check(rng == (2, 2), f"输满一字节光标自动前进到字节2 (rng={rng})")
# 非 hex 键取消半字节态: 键入 3 后按 Esc, 再键入 4 应为新字节 0x40
type_hex("3")
p._raw_table.keyPressEvent(QKeyEvent(
    QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, ""))
type_hex("4")
check(meta0['data'][2] == 0x40,
      f"Esc 取消半字节后键入 4 -> 字节2=0x{meta0['data'][2]:02X}")
# 光标移动后半字节态清零 (模拟 mousePress 路径): 5 与前一半字节 4 合成 0x45,
# 光标前进到字节3; 清零后再键入 6 在字节3 重开新字节
type_hex("5")
check(meta0['data'][2] == 0x45,
      f"半字节 4 与 5 合成 -> 字节2=0x{meta0['data'][2]:02X}")
p._raw_table._nibble = -1   # 鼠标点击等价行为
type_hex("6")
check(meta0['data'][3] == 0x60,
      f"光标移动后键入 6 重开新字节 -> 字节3=0x{meta0['data'][3]:02X}")

# ---- 双击字节格弹出编辑器 (mousePressEvent 必须调 super 维护 pressedIndex) ----
from PySide6.QtCore import QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLineEdit

p.resize(900, 600)
p.show()   # 需要布局后 visualRect 才有效
app.processEvents()


def _mev(typ, pos):
    gp = p._raw_table.viewport().mapToGlobal(pos)
    return QMouseEvent(typ, QPointF(pos), QPointF(gp),
                       Qt.MouseButton.LeftButton,
                       Qt.MouseButton.NoButton
                       if typ == QEvent.Type.MouseButtonRelease
                       else Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)


cell_pos = p._raw_table.visualRect(p._raw_table.model().index(0, 1)).center()
for _typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
             QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease):
    QApplication.sendEvent(p._raw_table.viewport(), _mev(_typ, cell_pos))
check(isinstance(QApplication.focusWidget(), QLineEdit),
      "双击字节格弹出编辑器")
check(p._raw_table.state().value == 3, "双击后视图进入编辑态")

# ---- 筛选: ID 过滤 + 序列命中成员整组显示 ----
from app.ui.widgets.transmit_panel import COL_ID, COL_CH, COL_COUNT, COL_NAME

p3 = TransmitPanel(channel_key="")
p3.resize(900, 600)
p3.show()
app.processEvents()
p3._add_frame(False)
i1 = p3._tree.currentItem()
p3._item_meta(i1)['id'] = 0x100
p3._add_frame(False)
i2 = p3._tree.currentItem()
p3._item_meta(i2)['id'] = 0x200
p3._add_sequence()
seq_item = p3._tree.topLevelItem(2)
p3._tree.setCurrentItem(seq_item)
p3._add_frame(False)   # 序列成员
m1 = p3._tree.currentItem()
p3._item_meta(m1)['id'] = 0x300
p3._tree.setCurrentItem(seq_item)
p3._add_frame(False)
m2 = p3._tree.currentItem()
p3._item_meta(m2)['id'] = 0x400

p3._set_id_filter("0x300")
check(not seq_item.isHidden() and not m1.isHidden() and not m2.isHidden(),
      "序列含命中成员 -> 整组显示 (含未命中成员)")
check(i1.isHidden() and i2.isHidden(), "未命中顶层帧隐藏")
p3._set_id_filter("0x100")
check(not i1.isHidden() and i2.isHidden() and seq_item.isHidden(),
      "ID 0x100 仅显示命中帧")
p3._set_id_filter("1f4")   # 无 0x 前缀按 hex 兜底
check(i1.isHidden() and i2.isHidden() and seq_item.isHidden(),
      "hex 免前缀解析 1f4 (=0x1F4) 无命中 -> 全隐藏")
p3._set_id_filter("")
check(not i1.isHidden() and not i2.isHidden() and not seq_item.isHidden()
      and not m1.isHidden(), "清空筛选全部显示")

# ---- 排序: ID 表头升序/降序, 序列成员顺序不动 ----
# (排序整体延迟到事件循环执行, 每次点击后需 processEvents)
p3._on_header_clicked(COL_ID)
app.processEvents()
order = [p3._item_meta(p3._tree.topLevelItem(i)).get('id')
         for i in range(p3._tree.topLevelItemCount())]
check(order == [0x100, 0x200, None],
      f"ID 升序顶层行 0x100,0x200,序列 (={order})")
check(p3._item_meta(seq_item)['members'][0] is p3._item_meta(m1)
      and p3._item_meta(seq_item)['members'][1] is p3._item_meta(m2),
      "排序后序列成员顺序不变")
p3._on_header_clicked(COL_ID)   # 再点降序
app.processEvents()
order = [p3._item_meta(p3._tree.topLevelItem(i)).get('id')
         for i in range(p3._tree.topLevelItemCount())]
check(order == [None, 0x200, 0x100], f"ID 再点降序 (={order})")
p3._on_header_clicked(COL_ID)   # 第三态: 取消排序 -> 恢复排序前顺序
app.processEvents()
order = [p3._item_meta(p3._tree.topLevelItem(i)).get('id')
         for i in range(p3._tree.topLevelItemCount())]
check(order == [0x100, 0x200, None]
      and p3._sort_col == -1,
      f"第三点取消排序恢复原始顺序 (={order})")
hdr_item = p3._tree.headerItem()
check("▲" not in hdr_item.text(COL_ID) and "▼" not in hdr_item.text(COL_ID),
      "取消排序后表头无排序箭头")

# ---- 排序后行内控件存活 (take/insert 后 setItemWidget 关联失效, 必须重挂) ----
from PySide6.QtWidgets import QComboBox as _QC, QSpinBox as _QS
w_ok = True
for i in range(p3._tree.topLevelItemCount()):
    it = p3._tree.topLevelItem(i)
    if not isinstance(p3._tree.itemWidget(it, COL_CH), _QC) \
            or not isinstance(p3._tree.itemWidget(it, COL_COUNT), _QS):
        w_ok = False
check(w_ok, "排序后各行 通道下拉/次数框 仍挂接")
check(p3._item_meta(i1)['_w'][COL_CH] is p3._tree.itemWidget(i1, COL_CH),
      "排序后 meta['_w'] 与实际挂接控件一致 (重排重建后同步刷新)")

# ---- 上移/下移后行内控件存活 ----
p3._tree.setCurrentItem(i2)
p3._move_selected(-1)
check(isinstance(p3._tree.itemWidget(i2, COL_CH), _QC),
      "上移后行内控件仍挂接")

# ---- 排序后序列成员行内控件存活 (take 顶层行会导致整棵子树索引失效) ----
p3._on_header_clicked(COL_ID)   # 未排序 -> 升序
app.processEvents()
check(isinstance(p3._tree.itemWidget(m1, COL_CH), _QC)
      and isinstance(p3._tree.itemWidget(m2, COL_COUNT), _QS),
      "排序后序列成员行内控件仍挂接")
p3._on_header_clicked(COL_ID)   # 升序 -> 降序
app.processEvents()
p3._tree.setCurrentItem(seq_item)
p3._move_selected(1)   # 序列整体上移/下移, 成员控件同样重挂
check(isinstance(p3._tree.itemWidget(m1, COL_CH), _QC),
      "序列移动后成员行内控件仍挂接")
p3._on_header_clicked(COL_ID)   # 降序 -> 取消 (恢复本次排序前快照)
app.processEvents()

# ---- 选中不随鼠标滑动改变: 滑过行/控件均不得改变当前选中 ----
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint
p3._tree.setCurrentItem(p3._tree.topLevelItem(0))
app.processEvents()
r2_rect = p3._tree.visualRect(p3._tree.model().index(2, COL_NAME))
QTest.mouseMove(p3._tree.viewport(), r2_rect.center())
app.processEvents()
check(p3._tree.currentIndex().row() == 0,
      f"鼠标滑过行不改变选中 (row={p3._tree.currentIndex().row()})")
combo2 = p3._tree.itemWidget(p3._tree.topLevelItem(2), COL_CH)
QTest.mouseMove(combo2, QPoint(5, combo2.height() // 2))
app.processEvents()
check(p3._tree.currentIndex().row() == 0,
      f"鼠标滑过行内控件不改变选中 (row={p3._tree.currentIndex().row()})")

# ---- 报文类型: 8 种 + 标志位映射 + 发送透传 + 持久化 ----
from app.ui.widgets.transmit_panel import (
    FRAME_TYPES, FRAME_TYPE_FLAGS, _flags_to_type_index, COL_TYPE)
check(len(FRAME_TYPES) == 8 and len(FRAME_TYPE_FLAGS) == 8,
      "报文类型共 8 种 (含远程帧/FD加速)")
meta1 = p3._item_meta(i1)
combo_t = p3._tree.itemWidget(i1, COL_TYPE)
check(combo_t is not None and combo_t.count() == 8, "类型组合框 8 项")
meta1['channel'] = "CAN1"   # 离屏无真实通道, 绕过空通道拦截
sent = []
orig_send = p3._dm.send_async
p3._dm.send_async = lambda ch, mid, data, ext, fd, is_remote=False, is_brs=False: \
    sent.append((mid, bytes(data), ext, fd, is_remote, is_brs)) or True
try:
    for idx, (ext, rtr, fd, brs) in enumerate(FRAME_TYPE_FLAGS):
        combo_t.setCurrentIndex(idx)
        app.processEvents()
        got = (meta1['is_extended'], meta1['is_remote'],
               meta1['is_fd'], meta1['is_brs'])
        check(got == (ext, rtr, fd, brs),
              f"类型[{idx}] {FRAME_TYPES[idx]} 映射标志位")
        check(combo_t.currentIndex() == _flags_to_type_index(meta1),
              f"类型[{idx}] 标志位反查索引一致")
        # 离屏无通道, _on_widget_changed 会把 channel 回写为空, 发送前补回
        meta1['channel'] = "CAN1"
        p3._send_frame(meta1)
        _mid, _data, sext, sfd, srtr, sbrs = sent[-1]
        check((sext, sfd, srtr, sbrs) == (ext, fd, rtr, brs),
              f"类型[{idx}] {FRAME_TYPES[idx]} 发送参数透传到 dm.send_async")
finally:
    p3._dm.send_async = orig_send
# 持久化: 远程+扩展往返 (注意此前排序/移动测试后行序为 [i2, i1, seq], 按 id 定位 i1)
combo_t.setCurrentIndex(3)   # 扩展CAN远程帧
app.processEvents()
st = p3.export_state()
row0 = next(it for it in st['items'] if it.get('id') == 0x100)
check(row0.get('is_remote') is True and row0.get('is_extended') is True
      and row0.get('is_brs') is False,
      f"export 带 is_remote/is_brs (={row0.get('is_remote')},{row0.get('is_brs')})")
p4 = TransmitPanel(channel_key="")
p4.import_state(st)
item_i1 = next(p4._tree.topLevelItem(k) for k in range(p4._tree.topLevelItemCount())
               if p4._item_meta(p4._tree.topLevelItem(k))['id'] == 0x100)
mi1 = p4._item_meta(item_i1)
check(mi1['is_remote'] is True and mi1['is_extended'] is True
      and mi1['is_fd'] is False and mi1['is_brs'] is False,
      "import 恢复 is_remote/is_brs 标志位")
combo_p4 = p4._tree.itemWidget(item_i1, COL_TYPE)
check(combo_p4 is not None and combo_p4.currentIndex() == 3,
      f"import 后类型组合框恢复为 扩展CAN远程帧 (idx={combo_p4.currentIndex()})")
# 恢复 meta1 为普通帧避免干扰后续断言
combo_t.setCurrentIndex(0)
app.processEvents()

# ---- 总线层: send 签名接受 is_remote/is_brs ----
import inspect as _inspect
from app.bus.zlg import ZlgCanDevice
from app.bus.ts_master import TsMasterCanDevice
from app.bus.vector import VectorCanDevice
from app.bus.virtual import VirtualBusDevice
from app.core.device_manager import DeviceManager
for cls in (ZlgCanDevice, TsMasterCanDevice, VectorCanDevice, VirtualBusDevice):
    params = _inspect.signature(cls.send).parameters
    check(all(k in params for k in ('is_remote', 'is_brs')),
          f"{cls.__name__}.send 支持 is_remote/is_brs")
dm_params = _inspect.signature(DeviceManager.send).parameters
check('is_remote' in dm_params and 'is_brs' in dm_params,
      "DeviceManager.send 透传 is_remote/is_brs")

# ---- 表头漏斗筛选按钮: 吸附列右缘 ----
hdr = p3._tree.header()
x_ch_end = hdr.sectionViewportPosition(COL_CH) + hdr.sectionSize(COL_CH)
g = p3._fbtn_ch.geometry()
check(abs(g.x() + g.width() - x_ch_end) <= 4 and g.y() >= 0
      and g.y() + g.height() <= hdr.height(),
      f"通道漏斗按钮吸附通道列右缘 (x={g.x()}+{g.width()} vs {x_ch_end})")
x_id_end = hdr.sectionViewportPosition(COL_ID) + hdr.sectionSize(COL_ID)
g2 = p3._fbtn_id.geometry()
check(abs(g2.x() + g2.width() - x_id_end) <= 4,
      f"ID 漏斗按钮吸附 ID 列右缘 (x={g2.x()}+{g2.width()} vs {x_id_end})")
check(hdr.height() < 40, f"单行表头高度恢复 (={hdr.height()})")

# ==================== 发送功能 / 启停联动 ====================
from app.ui.widgets.transmit_panel import (
    COL_TRIG, COL_EN, COL_LEN, COL_INTV)
from PySide6.QtWidgets import QStyleOptionViewItem


class _Ch:
    def __init__(self, key):
        self.key = key


class _FakeDM:
    """发送链路假设备管理器: 记录连接/发送, 通道 CAN1/CAN2"""
    send_ok = True

    def __init__(self):
        self.sent = []
        self.connected = []
        self.instances = set()

    def list_channels(self):
        return [_Ch('CAN1'), _Ch('CAN2')]

    def get_instance(self, key):
        return object() if key in self.instances else None

    def connect_channel(self, key):
        self.connected.append(key)
        self.instances.add(key)
        return True, ""

    def send_async(self, ch, mid, data, ext, fd, is_remote=False, is_brs=False):
        self.sent.append((ch, mid, bytes(data)))
        return self.send_ok


# ---- 触发列/只读列禁止弹编辑器 (行级 ItemIsEditable 波及所有列) ----
p5 = TransmitPanel(channel_key="")
p5.resize(900, 600)
p5.show()
app.processEvents()
p5._add_frame(False)
idx_trig = p5._tree.model().index(0, COL_TRIG)
opt = QStyleOptionViewItem()
d_trig = p5._tree.itemDelegateForColumn(COL_TRIG)
check(d_trig is not None
      and d_trig.createEditor(p5._tree.viewport(), opt, idx_trig) is None,
      "触发列 delegate 不创建编辑器 (按钮不可编辑)")
no_edit_ok = True
for c in (COL_EN, COL_CH, COL_TYPE, COL_LEN, COL_COUNT, COL_INTV):
    d = p5._tree.itemDelegateForColumn(c)
    if d is None or d.createEditor(
            p5._tree.viewport(), opt, p5._tree.model().index(0, c)) is not None:
        no_edit_ok = False
check(no_edit_ok, "勾选/通道/类型/长度/次数/周期列均禁止弹编辑器")
check(p5._tree.itemDelegateForColumn(COL_NAME) is None,
      "名称列保持默认可编辑")
# 双击触发格: 不开编辑器 (离屏无通道, 触发启动会被拦, 不影响本断言)
trig_rect = p5._tree.visualRect(idx_trig)
for _typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
             QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease):
    gp = p5._tree.viewport().mapToGlobal(trig_rect.center())
    ev = QMouseEvent(_typ, QPointF(trig_rect.center()), QPointF(gp),
                     Qt.MouseButton.LeftButton,
                     Qt.MouseButton.NoButton
                     if _typ == QEvent.Type.MouseButtonRelease
                     else Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(p5._tree.viewport(), ev)
app.processEvents()
check(not isinstance(QApplication.focusWidget(), QLineEdit),
      "双击触发格不弹出行内编辑器")

# ---- 启停按钮联动 + 启动自动连接通道 + 次数用尽自动停止 ----
p6 = TransmitPanel(channel_key="")
p6._dm = _FakeDM()
check(not p6._start_all_btn.isEnabled() and not p6._stop_all_btn.isEnabled(),
      "空列表: 启动/停止均禁用")
p6._add_frame(False)   # fake 通道下默认选中 CAN1
i61 = p6._tree.topLevelItem(0)
m61 = p6._item_meta(i61)
check(m61['channel'] == 'CAN1', f"fake 通道默认选中 CAN1 (={m61['channel']})")
m61['count'] = 2
check(p6._start_all_btn.isEnabled() and not p6._stop_all_btn.isEnabled(),
      "有启用行: 启动可用/停止禁用")
p6._start_all()
check('CAN1' in p6._dm.connected, "启动自动连接未连接通道")
check(m61.get('timer') is not None, "启动后行定时器运行")
check(not p6._start_all_btn.isEnabled() and p6._stop_all_btn.isEnabled(),
      "启动后: 启动禁用/停止可用")
check(len(p6._dm.sent) == 1, "启动立即发送一帧")
p6._frame_tick(m61, i61)   # 第2帧, count=2 用尽 -> 自动停止
check(m61.get('timer') is None, "次数用尽自动停止")
check(p6._start_all_btn.isEnabled() and not p6._stop_all_btn.isEnabled(),
      "自动停止后按钮还原")

# ---- 序列按成员顺序发送 + 成员通道自动连接 + 遍数用尽自动停止 ----
p6._add_sequence()
sq = p6._tree.topLevelItem(1)
p6._tree.setCurrentItem(sq)
p6._add_frame(False)
ma_item = p6._tree.currentItem()
p6._item_meta(ma_item)['id'] = 0x111
p6._tree.setCurrentItem(sq)
p6._add_frame(False)
mb_item = p6._tree.currentItem()
p6._tree.itemWidget(mb_item, COL_CH).setCurrentText('CAN2')
p6._item_meta(mb_item)['id'] = 0x222
smeta = p6._item_meta(sq)
p6._tree.itemWidget(sq, COL_COUNT).setValue(2)   # 2 遍
p6._dm.sent.clear()
p6._dm.connected.clear()
p6._on_trigger(smeta, sq)   # 启动序列 (立即发成员0)
check('CAN2' in p6._dm.connected, "序列启动自动连接成员通道 CAN2")
p6._seq_tick(smeta, sq)
p6._seq_tick(smeta, sq)
p6._seq_tick(smeta, sq)
ids = [s[1] for s in p6._dm.sent]
check(ids == [0x111, 0x222, 0x111, 0x222],
      f"序列按成员顺序循环发送 (={[hex(i) for i in ids]})")
check(smeta.get('timer') is not None, "遍数未满序列仍在运行")
p6._seq_tick(smeta, sq)   # 结算: _pass=2 用尽 -> 停
check(smeta.get('timer') is None, "遍数用尽序列自动停止")

# ---- 发送失败: 提示条警示 + 一轮运行只提示一次 ----
p7 = TransmitPanel(channel_key="")
p7._dm = _FakeDM()
p7._dm.send_ok = False
p7._add_frame(False)
i71 = p7._tree.topLevelItem(0)
m71 = p7._item_meta(i71)
# 无穷周期 (默认 count=1 发一帧即自动停止; 经行内框写入同步 meta)
p7._tree.itemWidget(i71, COL_COUNT).setValue(0)
p7._on_trigger(m71, i71)   # 启动 -> 立即发送失败
check(m71.get('timer') is not None, "发送失败不阻断周期定时器")
check(p7._hint_label.property("alert") is True
      and "发送失败" in p7._hint_label.text(),
      f"发送失败提示条警示 (={p7._hint_label.text()[:20]}...)")
check(m71.get('_err_shown') is True, "失败节流标记")
p7._hint_label.setText("x")   # 模拟已被消费
p7._frame_tick(m71, i71)   # 第二次失败不再重闪
check(p7._hint_label.text() == "x", "周期失败不重复刷屏")
p7._stop_all()
check(m71.get('timer') is None and not p7._stop_all_btn.isEnabled(),
      "停止全部后按钮还原")

# ---- 通道连接失败: 启动被拦 + 警示 ----
class _NoConnDM(_FakeDM):
    def connect_channel(self, key):
        return False, "设备未绑定"

p8 = TransmitPanel(channel_key="")
p8._dm = _NoConnDM()
p8._add_frame(False)
i81 = p8._tree.topLevelItem(0)
m81 = p8._item_meta(i81)
p8._on_trigger(m81, i81)
check(m81.get('timer') is None, "连接失败不启动定时器")
check("启动失败" in p8._hint_label.text(),
      f"连接失败警示 (={p8._hint_label.text()[:20]}...)")
p8._start_all()
check(m81.get('timer') is None and "部分行启动失败" in p8._hint_label.text(),
      "启动全部时连接失败行跳过并警示")

print("\n==== %s ====" % ("ALL PASS" if not fails else f"{len(fails)} FAIL"))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
