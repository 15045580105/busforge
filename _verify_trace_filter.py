"""Trace 列头漏斗筛选 (CANoe 式) 离线验证"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.ui.styles import get_theme
from app.ui.widgets.trace_view import (
    TraceView, _COL_ID, _COL_DIR, _COL_CH, _COL_DLC, _COL_DATA, _FILTER_COLS,
    _ROLE_FRAME,
)
from app.models.dto import FrameDTO, SignalValueDTO


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(get_theme())
    v = TraceView()
    v.resize(900, 500)
    v.show()

    sig_a = SignalValueDTO(name='Speed', message_name='Msg_A',
                           channel_key='CAN1', phys=88.5, raw=177,
                           unit='km/h')
    sig_b = SignalValueDTO(name='Mode', message_name='Msg_A',
                           channel_key='CAN1', phys=2.0, raw=2,
                           value_desc='Sport')
    frames = [
        FrameDTO(timestamp=1.0, channel_key='CAN1', direction='RX',
                 id=0x100, name='Msg_A', dlc=8, data=b'\x01' * 8,
                 signals=[sig_a, sig_b]),
        FrameDTO(timestamp=2.0, channel_key='CAN2', direction='TX',
                 id=0x200, name='Msg_B', dlc=8, data=b'\x02' * 8),
        FrameDTO(timestamp=3.0, channel_key='CAN1', direction='RX',
                 id=0x300, name='Msg_C', dlc=8, data=b'\x03' * 8),
    ]
    # 1. 报文流累积不重复值 (含 DLC/数据列)
    v._on_push(v._sub_id, 'frame', frames)
    assert sorted(v._distinct[_COL_ID]) == [0x100, 0x200, 0x300]
    assert sorted(v._distinct[_COL_DIR]) == ['RX', 'TX']
    assert sorted(v._distinct[_COL_CH]) == ['CAN1', 'CAN2']
    assert v._distinct[_COL_DLC] == {8}
    assert v._distinct[_COL_DATA] == {b'\x01'*8, b'\x02'*8, b'\x03'*8}
    print('PASS 1 不重复值累积:', sorted(v._distinct[_COL_ID]))

    # 2. 入表 (树形顶层行)
    v._refresh_table()
    assert v._table.topLevelItemCount() == 3
    print('PASS 2 入表行数:', v._table.topLevelItemCount())

    # 2a. 相对时间 (CANoe 式: 首帧为 0.000 原点, 随时间增长) + 禁排序
    times = [v._table.topLevelItem(r).text(0) for r in range(3)]
    assert times == ['0.000', '1.000', '2.000'], times
    assert not v._table.isSortingEnabled()
    assert v._table.topLevelItem(1).text(2) == 'TX'   # 方向透传
    print('PASS 2a 相对时间/禁排序/方向:', times)
    # 新一轮运行: 零点=启动时刻 (CANoe 测量起点, 非首帧)
    v._on_running_changed(True)
    assert isinstance(v._t0, float) and v._hub_running
    v._on_running_changed(False)
    assert not v._hub_running
    v._t0 = 1.0   # 还原 (后续行时间仍按 1.0 原点)
    print('PASS 2b 运行启动时刻为零点')

    # 3. ID 漏斗弹窗列出全部不重复值
    v._on_funnel_clicked(_COL_ID)
    lst = v._popup._list
    assert lst.count() == 3
    print('PASS 3 弹窗列表:', [lst.item(i).text() for i in range(3)])

    # 4. 搜索框过滤可见项
    v._popup._search.setText('0x100')
    vis = [lst.item(i).text() for i in range(3) if not lst.item(i).isHidden()]
    assert vis == ['0x100'], vis
    print('PASS 4 搜索过滤可见项:', vis)

    # 5. 只勾选 0x100 -> 行隐藏联动 (先清搜索, 全不选才作用于全部项)
    v._popup._search.clear()
    v._popup._check_visible(False)
    lst.item(0).setCheckState(Qt.CheckState.Checked)
    assert v._checked[_COL_ID] == {0x100}, v._checked[_COL_ID]
    hidden = [v._table.topLevelItem(r).isHidden() for r in range(3)]
    vis_rows = [r for r in range(3)
                if not v._table.topLevelItem(r).isHidden()]
    assert len(vis_rows) == 1, hidden
    f = v._table.topLevelItem(vis_rows[0]).data(0, _ROLE_FRAME)
    assert f.id == 0x100, f.id
    print('PASS 5 勾选过滤行隐藏:', hidden, '(按内容断言)')

    # 6. 恢复全选 -> 不过滤
    v._popup._check_visible(True)
    assert v._checked[_COL_ID] is None
    assert not any(v._table.topLevelItem(r).isHidden() for r in range(3))
    print('PASS 6 全选恢复不过滤')

    # 7. 方向列弹窗
    v._on_funnel_clicked(_COL_DIR)
    lst2 = v._popup._list
    assert [lst2.item(i).text() for i in range(lst2.count())] == ['RX', 'TX']
    print('PASS 7 方向列列表: RX/TX')

    # 8. DLC 列过滤: 勾选 8 后全部可见; 数据列弹窗
    v._on_funnel_clicked(_COL_DLC)
    assert v._popup._list.count() == 1
    v._on_funnel_clicked(_COL_DATA)
    assert v._popup._list.count() == 3
    print('PASS 8 DLC/数据列弹窗:', v._popup._list.count())

    # 9. 除时间列外全部登记漏斗; 漏斗命中区在列右缘
    assert set(_FILTER_COLS) == {1, 2, 3, 4, 5, 6}
    fr = v._header._funnel_rect(_COL_ID)
    assert not fr.isEmpty() and fr.width() == 16
    pos = v._header.funnel_anchor_pos(_COL_ID)
    assert pos is not None
    print('PASS 9 漏斗登记与命中区:', _FILTER_COLS)

    # 10. 激活态重绘 + 表头整体渲染 (paintSection 走一遍)
    v._header.set_funnel_active(_COL_ID, True)
    assert _COL_ID in v._header._active_funnels
    v._header.set_funnel_active(_COL_ID, False)
    assert _COL_ID not in v._header._active_funnels
    v.grab()
    print('PASS 10 激活态与表头渲染')

    # 11. 可解析报文展开标识 + 展开懒填充信号子行 (CANoe 式)
    from PySide6.QtWidgets import QTreeWidgetItem
    msg_item = None
    for r in range(v._table.topLevelItemCount()):
        it = v._table.topLevelItem(r)
        if it.data(0, _ROLE_FRAME).id == 0x100:
            msg_item = it
            break
    assert msg_item is not None
    assert msg_item.childIndicatorPolicy() == (
        QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
    assert msg_item.childCount() == 0          # 未展开零开销
    v._table.expandItem(msg_item)
    assert msg_item.childCount() == 2          # 展开后两个信号子行
    # 信号子行: 第 0 列跨列 + 树形引导符 (落在小加号正下方, CANoe 式)
    c0 = msg_item.child(0)
    assert c0.isFirstColumnSpanned()
    assert c0.text(0).startswith('├─ Speed')
    assert '88.5' in c0.text(0) and 'km/h' in c0.text(0)
    c1 = msg_item.child(1)
    assert c1.text(0).startswith('└─ Mode')   # 末条用 └
    assert 'Sport' in c1.text(0)
    # 无信号报文无展开标识
    no_sig = [v._table.topLevelItem(r) for r in range(3)
              if v._table.topLevelItem(r).data(0, _ROLE_FRAME).id == 0x200][0]
    assert no_sig.childIndicatorPolicy() != (
        QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
    print('PASS 11 展开标识与信号子行懒填充')

    # 12. 本机发送 TX 显示链路 (环回标记 / 设备层补回显 / 中台管线)
    from app.bus.virtual import VirtualBusDevice
    from app.core.device_manager import DeviceManager
    from app.core.data_hub import DataHub

    # 12a. 虚拟总线: 环回标记 TX, 广播到对端仍为 RX
    d1 = VirtualBusDevice(channel=1, bus_name='probe_tx')
    d2 = VirtualBusDevice(channel=2, bus_name='probe_tx')
    d1.open(); d2.open(); d1.start(); d2.start()
    assert d1.tx_self_echo is True
    assert d1.send(0x123, b'\xAA' * 8)
    f_self = d1.receive(timeout=0.5)
    assert f_self is not None and f_self.get('direction') == 'TX', f_self
    f_other = d2.receive(timeout=0.5)
    assert f_other is not None and 'direction' not in f_other, f_other
    d1.close(); d2.close()
    print('PASS 12a 虚拟总线环回 TX 标记 / 对端 RX')

    # 12b. DeviceManager: 无自回显设备发送成功 -> frame_sent 补 TX 回显
    dm = DeviceManager.instance()
    echoes = []
    dm.frame_sent.connect(lambda ch, fr: echoes.append((ch, fr)))

    class _NoEchoInst:
        tx_self_echo = False
        channel = 1
        def send(self, *a, **k):
            return True

    dm._instances['CAN9'] = _NoEchoInst()
    assert dm.send('CAN9', 0x456, b'\x01' * 8)
    assert len(echoes) == 1 and echoes[0][0] == 'CAN9'
    assert echoes[0][1]['direction'] == 'TX' and echoes[0][1]['id'] == 0x456
    dm._instances.pop('CAN9', None)
    print('PASS 12b 硬件无自回显时补发 TX 回显')

    # 12c. 自回显设备不重复补发
    vinst = VirtualBusDevice(channel=1, bus_name='probe_tx2')
    vinst.open(); vinst.start()
    dm._instances['CAN9'] = vinst
    assert dm.send('CAN9', 0x456, b'\x01' * 8)
    assert len(echoes) == 1, echoes
    dm._instances.pop('CAN9', None)
    vinst.close()
    print('PASS 12c 自回显设备不重复补发')

    # 12d. 中台: 运行态 + 工程通道才入 Trace, direction=TX 透传显示
    hub = DataHub.instance()
    hub._running = True
    hub._project_channels = ['CAN1']
    before = v._table.topLevelItemCount()
    hub._on_frame_sent('CAN1', {'id': 0x777, 'data': b'\x05' * 8, 'dlc': 8,
                                'is_extended': False, 'is_fd': False,
                                'is_remote': False, 'is_brs': False,
                                'channel': 1, 'timestamp': 5.0,
                                'direction': 'TX'})
    hub._flush_push()
    v._refresh_table()
    assert v._table.topLevelItemCount() == before + 1
    last = v._table.topLevelItem(v._table.topLevelItemCount() - 1)
    assert last.text(2) == 'TX' and last.text(0) == '4.000'
    # 未运行不入 Trace
    hub._running = False
    hub._on_frame_sent('CAN1', {'id': 0x778, 'data': b'\x06' * 8, 'dlc': 8,
                                'timestamp': 6.0, 'direction': 'TX'})
    hub._flush_push()
    v._refresh_table()
    assert v._table.topLevelItemCount() == before + 1
    hub._project_channels = []
    print('PASS 12d 中台回显帧管线 (运行态门禁 + TX 显示)')

    # 12e. 合批推送按时间戳排序: 多通道乱序 -> 时间单调无负值
    hub._running = True
    hub._project_channels = ['CAN1', 'CAN2']
    v._clear()   # _t0=None
    hub._ingest('CAN1', [{'id': 1, 'data': b'', 'dlc': 0, 'timestamp': 10.0}])
    hub._ingest('CAN2', [{'id': 2, 'data': b'', 'dlc': 0, 'timestamp': 9.5}])
    hub._flush_push()
    v._refresh_table()
    times = [v._table.topLevelItem(r).text(0)
             for r in range(v._table.topLevelItemCount())]
    assert times == ['0.000', '0.500'], times
    hub._running = False
    hub._project_channels = []
    print('PASS 12e 合批时间戳排序 (乱序入 -> 单调出):', times)

    # 12f. 启动轮询丢弃积压帧 (运行前发送面板自动连接发帧的排队残留)
    from types import SimpleNamespace
    v7 = VirtualBusDevice(channel=7, bus_name='probe_drain')
    v7.open(); v7.start()
    v7.send(0x777, b'\x01' * 8)   # 运行前积压
    import time as _time
    _time.sleep(0.05)
    # 通道表是活动工程池的属性, 需建临时工程池注入
    prev_proj = dm._active_project
    dm._pools['probe_proj'] = {'devices': {}, 'channels': {}}
    dm._active_project = 'probe_proj'
    dm._channels['CAN7'] = SimpleNamespace(device_id='dev7')
    dm._instances['CAN7'] = v7
    hub2 = DataHub.instance()
    ok, _ = hub2.begin_polling(['CAN7'])
    assert ok
    assert v7.receive_batch(16) == []   # 积压已被启动时丢弃
    hub2.stop_polling()
    dm._active_project = prev_proj
    dm._pools.pop('probe_proj', None)
    dm._instances.pop('CAN7', None)
    v7.close()
    print('PASS 12f 启动轮询丢弃积压帧 (零点不被旧帧拉偏)')

    # 12g. 虚拟总线批量接收必须非阻塞 (基类默认实现空转自旋
    # ~10ms/通道/轮询, 轮询在 UI 线程 -> 界面卡死)
    v8 = VirtualBusDevice(channel=8, bus_name='probe_nb')
    v8.open(); v8.start()
    _t0 = _time.perf_counter()
    assert v8.receive_batch(64) == []
    _dt = _time.perf_counter() - _t0
    assert _dt < 0.005, f'空队列批量接收耗时 {_dt*1000:.1f}ms'
    v8.close()
    print(f'PASS 12g 虚拟批量接收非阻塞: {_dt*1000:.2f}ms')

    # 13. CANoe 式分支小加/减号图标已生成并挂载
    import os as _os
    from app.ui.widgets.trace_view import _ensure_branch_icons
    br_c, br_o = _ensure_branch_icons()
    assert _os.path.exists(br_c) and _os.path.exists(br_o)
    assert 'branch' in v._table.styleSheet()
    print('PASS 13 分支小加/减号图标:', _os.path.basename(br_c),
          _os.path.basename(br_o))
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
