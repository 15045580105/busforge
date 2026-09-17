"""
Graphy面板 - 信号折线图 (纯展示层)

左侧20%: 通道选择 + 信号列表(勾选要显示的信号, 元数据来自DataHub)
右侧80%: pyqtgraph实时曲线 (数据来自DataHub推送的SignalValueDTO)
"""

import time
import logging
from collections import deque

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QSplitter, QLineEdit, QLabel, QComboBox
)
from PySide6.QtCore import Qt, QTimer

from app.core.data_hub import DataHub, KIND_SIGNAL
from app.core.device_manager import DeviceManager

logger = logging.getLogger(__name__)

try:
    import pyqtgraph as pg
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    pg = None
    PYQTGRAPH_AVAILABLE = False


class GraphyView(QWidget):
    """信号折线图面板 - 全局统一单实例, 通道可切换"""

    def __init__(self, channel_key: str = "", parent=None):
        super().__init__(parent)
        self._hub = DataHub.instance()
        self._dm = DeviceManager.instance()
        self._sub_id = f"graphy_{id(self):x}"
        self._channel_key = channel_key or ""
        self._plot_curves: dict[str, object] = {}
        self._data_buffers: dict[str, deque] = {}
        self._watched: set[str] = set()
        self._max_buffer = 6000  # 60s @ 100Hz
        self._start_time = time.time()

        self._setup_ui()
        self._hub.push.connect(self._on_push)
        self._hub.dbc_changed.connect(self._on_dbc_changed)
        self._rebuild_tree()
        self._resubscribe()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self._refresh_plots)
        self._refresh_timer.start()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("通道:"))
        self._channel_combo = QComboBox()
        self._refresh_channel_combo()
        self._channel_combo.currentTextChanged.connect(self._on_channel_changed)
        ch_row.addWidget(self._channel_combo)
        left_layout.addLayout(ch_row)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索信号...")
        self._search.setFixedHeight(28)
        self._search.textChanged.connect(self._filter_tree)
        left_layout.addWidget(self._search)

        self._signal_tree = QTreeWidget()
        self._signal_tree.setHeaderHidden(True)
        self._signal_tree.itemChanged.connect(self._on_item_changed)
        left_layout.addWidget(self._signal_tree)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        if PYQTGRAPH_AVAILABLE:
            pg.setConfigOptions(antialias=True)
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setLabel('bottom', '时间', 's')
            self._plot_widget.setLabel('left', '物理值')
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self._plot_widget.addLegend()
            right_layout.addWidget(self._plot_widget)
        else:
            right_layout.addWidget(QLabel("pyqtgraph未安装\npip install pyqtgraph"))

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        layout.addWidget(splitter)

        self._colors = [
            (255, 100, 100), (100, 255, 100), (100, 100, 255),
            (255, 255, 100), (255, 100, 255), (100, 255, 255),
            (255, 180, 100), (180, 100, 255), (100, 255, 180),
        ]
        self._color_idx = 0

    def _refresh_channel_combo(self):
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        for ch in self._dm.list_channels():
            self._channel_combo.addItem(ch.key)
        idx = self._channel_combo.findText(self._channel_key)
        self._channel_combo.setCurrentIndex(idx if idx >= 0 else -1)
        self._channel_combo.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  信号树 (元数据只读展示)
    # ------------------------------------------------------------------ #

    def _on_dbc_changed(self, channel_key: str, dbc):
        if channel_key == self._channel_key:
            self._rebuild_tree()

    def _rebuild_tree(self):
        self._signal_tree.blockSignals(True)
        self._signal_tree.clear()
        self._watched.clear()
        dbc = self._hub.get_dbc(self._channel_key) if self._channel_key else None
        if dbc:
            for msg in dbc.messages:
                msg_item = QTreeWidgetItem(self._signal_tree, [msg.name])
                msg_item.setExpanded(False)
                for sig in msg.signals:
                    sig_item = QTreeWidgetItem(msg_item, [sig.name])
                    sig_item.setData(0, Qt.ItemDataRole.UserRole, {
                        'signal_name': sig.name, 'message_name': msg.name
                    })
                    sig_item.setCheckState(0, Qt.CheckState.Unchecked)
        self._signal_tree.blockSignals(False)
        self._resubscribe()

    def _filter_tree(self, text: str):
        text = text.lower()
        for i in range(self._signal_tree.topLevelItemCount()):
            msg_item = self._signal_tree.topLevelItem(i)
            visible = False
            for j in range(msg_item.childCount()):
                sig_item = msg_item.child(j)
                match = text in sig_item.text(0).lower()
                sig_item.setHidden(not match)
                if match:
                    visible = True
            msg_item.setHidden(not visible)
            if visible and text:
                msg_item.setExpanded(True)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not isinstance(data, dict):
            return
        sig_name = data.get('signal_name', '')
        checked = item.checkState(0) == Qt.CheckState.Checked

        if checked and sig_name not in self._plot_curves:
            self._watched.add(sig_name)
            if PYQTGRAPH_AVAILABLE:
                color = self._colors[self._color_idx % len(self._colors)]
                self._color_idx += 1
                pen = pg.mkPen(color=color, width=2)
                curve = self._plot_widget.plot([], [], pen=pen, name=sig_name)
                self._plot_curves[sig_name] = curve
                self._data_buffers[sig_name] = deque(maxlen=self._max_buffer)
        elif not checked and sig_name in self._plot_curves:
            self._watched.discard(sig_name)
            if PYQTGRAPH_AVAILABLE:
                self._plot_widget.removeItem(self._plot_curves[sig_name])
            del self._plot_curves[sig_name]
            self._data_buffers.pop(sig_name, None)
        self._resubscribe()

    # ------------------------------------------------------------------ #
    #  订阅与推送
    # ------------------------------------------------------------------ #

    def _resubscribe(self):
        channels = [self._channel_key] if self._channel_key else None
        filt = {'signal_names': set(self._watched)}
        if self._hub.get_subscription(self._sub_id):
            self._hub.update_subscription(
                self._sub_id, kinds={KIND_SIGNAL}, channels=channels,
                filter=filt)
        else:
            self._hub.register(self._sub_id, {KIND_SIGNAL},
                               channels=channels, filter=filt)

    def _on_push(self, sid: str, kind: str, payload):
        """中台推送 - 只追加曲线缓冲, 不做解码"""
        if sid != self._sub_id or kind != KIND_SIGNAL:
            return
        now = time.time() - self._start_time
        for dto in payload:
            buf = self._data_buffers.get(dto.name)
            if buf is not None:
                buf.append((now, dto.phys))

    def _refresh_plots(self):
        if not PYQTGRAPH_AVAILABLE:
            return
        for sig_name, curve in self._plot_curves.items():
            buf = self._data_buffers.get(sig_name)
            if not buf:
                continue
            times = [p[0] for p in buf]
            values = [p[1] for p in buf]
            curve.setData(times, values)

    # ------------------------------------------------------------------ #
    #  交互
    # ------------------------------------------------------------------ #

    def _on_channel_changed(self, text: str):
        self._channel_key = text
        if PYQTGRAPH_AVAILABLE:
            for curve in self._plot_curves.values():
                self._plot_widget.removeItem(curve)
        self._plot_curves.clear()
        self._data_buffers.clear()
        self._rebuild_tree()

    def set_channel(self, channel_key: str):
        self._channel_key = channel_key or ""
        self._refresh_channel_combo()
        self._on_channel_changed(self._channel_key)

    def closeEvent(self, event):
        self._hub.unregister(self._sub_id)
        super().closeEvent(event)
