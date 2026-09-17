# -*- coding: utf-8 -*-
"""真实窗口卡顿探针: 启动工程+启动仿真发送, 监测事件循环延迟与发送计数
(自动运行 ~8 秒后自退, 无需人工操作)"""
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    mw = MainWindow(AppConfig())
    mw.show()

    state = {'ticks': [], 'last': None}
    w = mw._widget

    def tick():
        now = time.perf_counter()
        if state['last'] is not None:
            state['ticks'].append(now - state['last'])
        state['last'] = now

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)

    log = []

    def step(t, msg):
        log.append(f'[{time.perf_counter():.1f}] {msg}')

    # t=1s: 启动工程
    def start_project():
        ok = w.run_project()
        step(1, f'run_project -> {ok}, hub running={w._hub.running}')

    def diag(tag):
        from app.core.device_manager import DeviceManager
        dm = DeviceManager.instance()
        worker = getattr(w, '_connect_worker', None)
        step(tag, f'instances={list(dm._instances.keys())} '
                  f'states={dict(dm._channel_state)} '
                  f'worker={"alive" if worker and worker.isRunning() else worker} '
                  f'hub_running={w._hub.running} '
                  f'proj_channels={w._hub._project_channels}')

    # t=3s: 启动仿真发送 (全部启用行)
    def start_tx():
        panels = [p for p in w.findChildren(type(w).__mro__[0])]  # noop
        tp = None
        from app.ui.widgets.transmit_panel import TransmitPanel
        for x in mw.findChildren(TransmitPanel):
            tp = x
            break
        if tp is None:
            step(3, 'TransmitPanel 未找到!')
            return
        state['tp'] = tp
        from app.core.device_manager import DeviceManager
        step(3, f'tp._dm is singleton: {tp._dm is DeviceManager.instance()}')
        tp._start_all()
        running = sum(1 for i in range(tp._tree.topLevelItemCount())
                      if (tp._item_meta(tp._tree.topLevelItem(i)) or {}).get('timer'))
        step(3, f'_start_all 后运行行数={running}, 总行数={tp._tree.topLevelItemCount()}')

    # t=7s: 统计并退出
    def report():
        timer.stop()
        tp = state.get('tp')
        ticks = state['ticks']
        if ticks:
            avg = sum(ticks) / len(ticks) * 1000
            mx = max(ticks) * 1000
            over = sum(1 for t in ticks if t > 0.2)
            print(f'事件循环 tick(50ms期望): avg={avg:.0f}ms max={mx:.0f}ms '
                  f'>200ms次数={over}/{len(ticks)}')
        if tp:
            from app.core.device_manager import DeviceManager
            dm = DeviceManager.instance()
            inst = dm.get_instance('CAN1')
            print('CAN1 inst:', type(inst).__name__ if inst else None,
                  'state=', getattr(inst, 'state', '?'),
                  'listen_only=', getattr(inst, '_listen_only', '?'),
                  'ch_handle=', getattr(inst, '_channel_handle', '?'))
            for _ in range(3):
                _t0 = time.perf_counter()
                inst.receive_batch(64)
                print(f'  receive_batch 耗时: {(time.perf_counter()-_t0)*1000:.1f}ms')
            _t0 = time.perf_counter()
            _ok = dm.send('CAN1', 0x123, b'\x01' * 8)
            print(f'  直发 dm.send -> {_ok} 耗时 {(time.perf_counter()-_t0)*1000:.1f}ms')
            for key, inst in dm.connected_instances().items():
                st = getattr(inst, '_stats', None)
                print(f'通道 {key}: tx={st.tx_count if st else "?"} '
                      f'rx={st.rx_count if st else "?"} '
                      f'队列~{inst._rx_queue.qsize() if hasattr(inst, "_rx_queue") else "?"}')
            for i in range(tp._tree.topLevelItemCount()):
                meta = tp._item_meta(tp._tree.topLevelItem(i))
                if meta:
                    print(f'行{i}: progress={meta.get("progress")} '
                          f'timer={"有" if meta.get("timer") else "无"} '
                          f'err_shown={meta.get("_err_shown")}')
        tr = None
        from app.ui.widgets.trace_view import TraceView
        for x in mw.findChildren(TraceView):
            tr = x
            break
        if tr:
            print(f'Trace 行数: {tr._table.topLevelItemCount()}, '
                  f'缓冲积压: {len(tr._frames_buffer)}')
        print('\n'.join(log))
        app.quit()

    QTimer.singleShot(1000, start_project)
    QTimer.singleShot(1200, lambda: diag(1.2))
    QTimer.singleShot(2000, lambda: diag(2.0))
    QTimer.singleShot(2900, lambda: diag(2.9))
    QTimer.singleShot(3000, start_tx)
    QTimer.singleShot(3100, lambda: diag(3.1))
    QTimer.singleShot(3200, timer.start)
    QTimer.singleShot(7000, report)
    app.exec()
    return 0


if __name__ == '__main__':
    sys.exit(main())
