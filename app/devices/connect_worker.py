"""
ConnectWorker - 运行工程时的异步连接线程

将"逐通道打开硬件"的耗时操作移出UI线程, 避免点击运行后界面冻结。
- 在工作线程内顺序调用 DeviceManager.connect_channel (硬件操作在子线程执行)
- 逐条上报进度 progress(done, total, key), 供状态栏/工具栏显示"连接中 i/n"
- 支持 cancel(): 置取消标志, 循环内检测后提前退出 (切换/终止工程时调用)
- 完成上报 finished_ok(ok, error); 信号跨线程自动排队到主线程处理

注意: 本线程只做"连接", 绝不启动任何 QTimer; 轮询定时器由主线程在
连接成功后经 DataHub.begin_polling 启动。
"""

import logging

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class ConnectWorker(QThread):
    """异步连接一组软件通道的工作线程"""

    # done, total, channel_key
    progress = Signal(int, int, str)
    # ok, error_text
    finished_ok = Signal(bool, str)

    def __init__(self, dm, channel_keys: list, parent=None):
        super().__init__(parent)
        self._dm = dm
        self._keys = list(channel_keys or [])
        self._cancel = False

    def cancel(self):
        """请求取消 (在下一条通道连接前生效)"""
        self._cancel = True

    def run(self):
        total = len(self._keys)
        errors = []
        connected = 0
        for i, key in enumerate(self._keys):
            if self._cancel:
                logger.info("连接任务已取消")
                self.finished_ok.emit(False, "已取消")
                return
            ok, err = self._dm.connect_channel(key)
            if ok:
                connected += 1
            elif err:
                errors.append(err)
            self.progress.emit(i + 1, total, key)

        if self._cancel:
            self.finished_ok.emit(False, "已取消")
            return
        ok = connected > 0 or total == 0
        self.finished_ok.emit(ok, "; ".join(errors))
