"""
设备/通道配置对话框

- DeviceSelectDialog: TSMaster/Vector/ZLG设备选择
- ChannelConfigDialog: 通道波特率/CAN FD配置
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSpinBox, QWidget,
    QCheckBox, QGroupBox, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt


class DeviceSelectDialog(QDialog):
    """设备选择对话框 - 枚举可用硬件"""

    def __init__(self, vendor: str = "TSMaster", parent=None):
        super().__init__(parent)
        self._vendor = vendor
        self._devices = []
        self._selected_info = None
        self.setWindowTitle(f"选择{vendor}设备")
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)
        self._setup_ui()
        self._enumerate_devices()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 设备列表
        group = QGroupBox(f"可用{self._vendor}设备")
        group_layout = QVBoxLayout(group)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["型号", "序列号", "类型", "索引"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        group_layout.addWidget(self._table)

        refresh_btn = QPushButton("刷新设备列表")
        refresh_btn.clicked.connect(self._enumerate_devices)
        group_layout.addWidget(refresh_btn)

        layout.addWidget(group)

        tip = QLabel("请在列表中选中一台设备后点击 OK; 若列表为空, 请检查硬件连接与驱动后刷新。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #666666;")
        layout.addWidget(tip)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _enumerate_devices(self):
        """枚举设备 (TSMaster: DLL枚举; ZLG: 型号x索引探测)"""
        self._table.setRowCount(0)
        self._devices = []

        if self._vendor == "TSMaster":
            try:
                from app.devices.drivers.ts_jna import TsMasterLib
                lib = TsMasterLib()
                lib.initialize()
                count = lib.enumerate_hw_devices()
                for i in range(count):
                    info = lib.get_hw_info_by_index(i)
                    if info:
                        self._devices.append({
                            'index': i,
                            'model': info.get('device_name', 'Unknown'),
                            'serial': info.get('serial', ''),
                            'type': info.get('device_type', 0),
                            'vendor': info.get('vendor_name', ''),
                        })
                lib.finalize()
            except Exception:
                pass
        elif self._vendor == "ZLG":
            try:
                from app.devices.drivers.zlg_lib import enumerate_zlg_devices
                for dev in enumerate_zlg_devices():
                    self._devices.append({
                        'index': dev['index'],
                        'model': dev['model'],
                        'serial': dev['serial'],
                        'type': dev['device_type'],
                        'vendor': 'ZLG',
                    })
            except Exception:
                pass

        # Vector/Virtual 无DLL枚举: 提供默认设备行供选择
        if not self._devices and self._vendor in ("Vector", "Virtual"):
            self._devices.append({
                'index': 0,
                'model': self._vendor,
                'serial': '',
                'type': '',
            })

        # 填充表格
        for dev in self._devices:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(dev.get('model', '')))
            self._table.setItem(row, 1, QTableWidgetItem(dev.get('serial', '')))
            self._table.setItem(row, 2, QTableWidgetItem(str(dev.get('type', ''))))
            self._table.setItem(row, 3, QTableWidgetItem(str(dev.get('index', ''))))

    def get_selected_device(self):
        """获取列表中选中的设备信息; 未选中返回 None"""
        row = self._table.currentRow()
        if 0 <= row < len(self._devices):
            dev = self._devices[row]
            return {
                'vendor': self._vendor,
                'model': dev.get('model', ''),
                'serial': dev.get('serial', ''),
                'index': dev.get('index', 0),
            }
        return None

    def accept(self):
        """未选中设备时不允许确认"""
        if self.get_selected_device() is None:
            QMessageBox.warning(self, "提示", "请先在列表中选中一台设备")
            return
        super().accept()


class ChannelConfigDialog(QDialog):
    """通道配置对话框 - 波特率/CAN FD"""

    def __init__(self, bus_type: str = "can", parent=None):
        super().__init__(parent)
        self._bus_type = bus_type
        self.setWindowTitle("通道配置")
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # 通道号
        self._ch_spin = QSpinBox()
        self._ch_spin.setRange(1, 8)
        self._ch_spin.setValue(1)
        form.addRow("通道号:", self._ch_spin)

        # 波特率
        self._baud_combo = QComboBox()
        baud_rates = ["125", "250", "500", "800", "1000"]
        self._baud_combo.addItems(baud_rates)
        self._baud_combo.setCurrentText("500")
        form.addRow("波特率 (kbps):", self._baud_combo)

        # CAN FD
        if self._bus_type == "can":
            self._fd_check = QCheckBox("启用 CAN FD")
            form.addRow("", self._fd_check)

            self._data_baud_combo = QComboBox()
            data_rates = ["500", "1000", "2000", "4000", "5000", "8000"]
            self._data_baud_combo.addItems(data_rates)
            self._data_baud_combo.setCurrentText("2000")
            form.addRow("数据段波特率 (kbps):", self._data_baud_combo)
        else:
            self._fd_check = None
            self._data_baud_combo = None

        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_channel_info(self) -> dict:
        """获取通道配置"""
        info = {
            'channel_index': self._ch_spin.value(),
            'baud_rate': int(self._baud_combo.currentText()),
        }
        if self._fd_check:
            info['is_can_fd'] = self._fd_check.isChecked()
        if self._data_baud_combo:
            info['data_baud_rate'] = int(self._data_baud_combo.currentText())
        return info


class ChannelParamDialog(QDialog):
    """设备参数配置 - 波特率/FD/数据波特率/只听/终端电阻

    设备绑定与硬件通道已在通道表内直接设置, 故本弹窗不再重复。
    """

    _BAUDS = [125, 250, 500, 800, 1000]
    _DATA_RATES = [500, 1000, 2000, 4000, 5000, 8000]

    def __init__(self, channel_key: str, ch, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"设备参数配置 - {channel_key}")
        self.setMinimumWidth(430)
        self._setup_ui(ch)

    def _setup_ui(self, ch):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._baud_combo = QComboBox()
        for b in self._BAUDS:
            self._baud_combo.addItem(str(b), b)
        bi = self._baud_combo.findData(int(ch.baud_rate))
        self._baud_combo.setCurrentIndex(bi if bi >= 0 else 2)
        form.addRow("波特率(k):", self._baud_combo)

        self._fd_check = QCheckBox("启用 CAN FD")
        self._fd_check.setChecked(bool(ch.is_fd))
        self._fd_check.toggled.connect(self._on_fd_toggled)
        form.addRow("", self._fd_check)

        self._data_combo = QComboBox()
        for r in self._DATA_RATES:
            self._data_combo.addItem(str(r), r)
        di = self._data_combo.findData(int(ch.data_baud_rate))
        self._data_combo.setCurrentIndex(di if di >= 0 else 2)

        # Windows原生风格不绘制QComboBox的disabled背景, 置灰时用灰底占位标签替换显示
        self._data_placeholder = QLabel()
        self._data_placeholder.setObjectName("disabledField")
        self._data_placeholder.setVisible(False)
        data_holder = QWidget()
        data_layout = QHBoxLayout(data_holder)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.addWidget(self._data_combo)
        data_layout.addWidget(self._data_placeholder)
        form.addRow("数据段波特率(k):", data_holder)

        self._listen_check = QCheckBox("只听模式 (只收不发)")
        self._listen_check.setChecked(bool(ch.listen_only))
        form.addRow("", self._listen_check)

        self._term_check = QCheckBox("启用 120Ω 终端电阻")
        self._term_check.setChecked(bool(ch.terminal_resistor))
        form.addRow("", self._term_check)

        layout.addLayout(form)

        tip = QLabel("提示: 设备绑定与硬件通道请在通道表内直接选择/设置。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #8a6d3b;")
        layout.addWidget(tip)

        self._on_fd_toggled(self._fd_check.isChecked())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_fd_toggled(self, on: bool):
        self._data_combo.setEnabled(bool(on))
        self._data_combo.setVisible(bool(on))
        if not on:
            self._data_placeholder.setText(self._data_combo.currentText())
        self._data_placeholder.setVisible(not on)

    def get_result(self) -> dict:
        """获取设备参数 (不含设备绑定/硬件通道/DBC, 三者均在通道表或工程树设置)"""
        return {
            'baud_rate': self._baud_combo.currentData(),
            'is_fd': self._fd_check.isChecked(),
            'data_baud_rate': self._data_combo.currentData(),
            'listen_only': self._listen_check.isChecked(),
            'terminal_resistor': self._term_check.isChecked(),
        }
