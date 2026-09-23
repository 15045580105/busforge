"""
UDS诊断面板

设备/通道选择器 + UDS服务标签页(会话控制/安全访问/DID读写/例行控制/原始报文)
"""

import logging
import time
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox,
    QFormLayout, QLabel, QComboBox, QPushButton, QLineEdit,
    QSpinBox, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from app.devices.device_manager import DeviceManager
from app.datahub.data_hub import DataHub
from app.common.ui_settings import UISettings

logger = logging.getLogger(__name__)


class DiagnosticPanel(QWidget):
    """UDS诊断面板 - 发送走DeviceManager, 响应由UdsClient同步接收"""

    def __init__(self, channel_key: str = "", parent=None):
        super().__init__(parent)
        self._channel_key = channel_key
        self._dm = DeviceManager.instance()
        self._hub = DataHub.instance()
        self._ui = UISettings.instance()
        self._uds_client = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 顶部: 设备/通道选择
        conn_group = QGroupBox("连接配置")
        conn_layout = QFormLayout(conn_group)

        self._channel_combo = QComboBox()
        self._channel_combo.addItem(self._channel_key or "未选择")
        conn_layout.addRow("通道:", self._channel_combo)

        req_layout = QHBoxLayout()
        self._req_id = QLineEdit("0x7E0")
        self._req_id.setFixedWidth(100)
        req_layout.addWidget(QLabel("请求ID:"))
        req_layout.addWidget(self._req_id)
        req_layout.addWidget(QLabel("响应ID:"))
        self._resp_id = QLineEdit("0x7E8")
        self._resp_id.setFixedWidth(100)
        req_layout.addWidget(self._resp_id)
        conn_layout.addRow("通信参数:", req_layout)

        connect_btn = QPushButton("连接")
        connect_btn.clicked.connect(self._connect_uds)
        conn_layout.addRow("", connect_btn)

        layout.addWidget(conn_group)

        # 标签页
        self._tabs = QTabWidget()

        # 10服务: 会话控制
        self._tabs.addTab(self._create_session_tab(), "会话控制 (10)")
        # 27服务: 安全访问
        self._tabs.addTab(self._create_security_tab(), "安全访问 (27)")
        # 22/2E服务: DID读写
        self._tabs.addTab(self._create_did_tab(), "DID读写 (22/2E)")
        # 31服务: 例行控制
        self._tabs.addTab(self._create_routine_tab(), "例行控制 (31)")
        # 原始报文
        self._tabs.addTab(self._create_raw_tab(), "原始报文")

        layout.addWidget(self._tabs)

        # 日志区
        log_group = QGroupBox("通信日志")
        log_layout = QVBoxLayout(log_group)
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(2000)
        self._log_text.setFont(QFont("Cascadia Code", 10))
        log_layout.addWidget(self._log_text)

        clear_log_btn = QPushButton("清除日志")
        clear_log_btn.clicked.connect(self._log_text.clear)
        log_layout.addWidget(clear_log_btn)

        layout.addWidget(log_group)

    def _create_session_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        self._session_type = QComboBox()
        self._session_type.addItems(["默认会话 (0x01)", "编程会话 (0x02)", "扩展会话 (0x03)"])
        layout.addRow("会话类型:", self._session_type)

        send_btn = QPushButton("发送 10 服务")
        send_btn.clicked.connect(self._send_session_control)
        layout.addRow("", send_btn)

        self._session_result = QLabel("")
        layout.addRow("结果:", self._session_result)
        return w

    def _create_security_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        self._sec_level = QSpinBox()
        self._sec_level.setRange(1, 255)
        self._sec_level.setValue(1)
        layout.addRow("安全等级:", self._sec_level)

        send_btn = QPushButton("请求种子")
        send_btn.clicked.connect(self._send_security_request)
        layout.addRow("", send_btn)

        self._sec_key_edit = QLineEdit()
        self._sec_key_edit.setPlaceholderText("输入安全密钥 (Hex)")
        layout.addRow("发送密钥:", self._sec_key_edit)

        send_key_btn = QPushButton("发送密钥")
        send_key_btn.clicked.connect(self._send_security_key)
        layout.addRow("", send_key_btn)

        self._sec_result = QLabel("")
        layout.addRow("结果:", self._sec_result)
        return w

    def _create_did_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        self._did_edit = QLineEdit("F190")
        self._did_edit.setFixedWidth(100)
        layout.addRow("DID (Hex):", self._did_edit)

        read_btn = QPushButton("读取 (22)")
        read_btn.clicked.connect(self._read_did)
        layout.addRow("", read_btn)

        self._did_data_edit = QLineEdit()
        self._did_data_edit.setPlaceholderText("数据 (Hex)")
        layout.addRow("写入数据:", self._did_data_edit)

        write_btn = QPushButton("写入 (2E)")
        write_btn.clicked.connect(self._write_did)
        layout.addRow("", write_btn)

        self._did_result = QLabel("")
        layout.addRow("结果:", self._did_result)
        return w

    def _create_routine_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        self._routine_id = QLineEdit("FF00")
        self._routine_id.setFixedWidth(100)
        layout.addRow("例行ID (Hex):", self._routine_id)

        self._routine_type = QComboBox()
        self._routine_type.addItems(["启动 (0x01)", "停止 (0x02)", "查询结果 (0x03)"])
        layout.addRow("操作类型:", self._routine_type)

        send_btn = QPushButton("发送 31 服务")
        send_btn.clicked.connect(self._send_routine)
        layout.addRow("", send_btn)

        self._routine_result = QLabel("")
        layout.addRow("结果:", self._routine_result)
        return w

    def _create_raw_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        self._raw_edit = QLineEdit()
        self._raw_edit.setPlaceholderText("10 01 / 22 F190 / 27 01 ...")
        layout.addRow("原始报文 (Hex):", self._raw_edit)

        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self._send_raw)
        layout.addRow("", send_btn)

        self._raw_result = QLabel("")
        layout.addRow("响应:", self._raw_result)
        return w

    # ---- UDS操作 ----

    def _connect_uds(self):
        inst = self._dm.get_instance(self._channel_key)
        if not inst:
            self._log("连接失败: 通道未连接, 请先在设备管理中连接设备")
            return
        try:
            from app.diagnostic.uds_client import UdsClient, UdsConfig
            req_id = int(self._req_id.text(), 16)
            resp_id = int(self._resp_id.text(), 16)
            cfg = UdsConfig(request_id=req_id, response_id=resp_id)
            self._uds_client = UdsClient(inst, cfg)
            self._uds_client.set_log_callback(self._log)
            # UDS同步收发期间暂停中台轮询, 避免抢帧
            self._hub.set_channel_paused(self._channel_key, True)
            self._log("UDS客户端已创建 (通道轮询已暂停)")
        except Exception as e:
            self._log(f"连接失败: {e}")

    def _show_resp(self, label, resp):
        if resp is None:
            label.setText("无响应 (超时)")
        elif resp.is_positive:
            label.setText(f"正响应: {self._ui.fmt_data(resp.raw_response)}")
        else:
            label.setText(
                f"负响应 NRC {self._ui.fmt_int(resp.nrc)} ({resp.nrc_name})")

    def _send_session_control(self):
        if not self._uds_client:
            self._session_result.setText("请先创建UDS连接")
            return
        idx = self._session_type.currentIndex()
        sub_func = [0x01, 0x02, 0x03][idx]
        self._log(f">>> 10 {sub_func:02X}")
        self._show_resp(self._session_result,
                        self._uds_client.diagnostic_session_control(sub_func))

    def _send_security_request(self):
        if not self._uds_client:
            self._sec_result.setText("请先创建UDS连接")
            return
        level = self._sec_level.value()
        self._log(f">>> 27 {level:02X} (请求种子)")
        ok = self._uds_client.execute_security_access(level)
        self._sec_result.setText("安全访问成功" if ok else "安全访问失败")

    def _send_security_key(self):
        if not self._uds_client:
            self._sec_result.setText("请先创建UDS连接")
            return
        level = self._sec_level.value()
        key = self._sec_key_edit.text().strip()
        self._log(f">>> 27 {level+1:02X} {key}")
        try:
            resp = self._uds_client.security_access(level + 1,
                                                    bytes.fromhex(key))
            self._show_resp(self._sec_result, resp)
        except ValueError:
            self._sec_result.setText("密钥Hex格式错误")

    def _read_did(self):
        if not self._uds_client:
            self._did_result.setText("请先创建UDS连接")
            return
        did = self._did_edit.text().strip()
        self._log(f">>> 22 {did}")
        try:
            resp = self._uds_client.read_data_by_identifier(int(did, 16))
            self._show_resp(self._did_result, resp)
        except ValueError:
            self._did_result.setText("DID Hex格式错误")

    def _write_did(self):
        if not self._uds_client:
            self._did_result.setText("请先创建UDS连接")
            return
        did = self._did_edit.text().strip()
        data = self._did_data_edit.text().strip()
        self._log(f">>> 2E {did} {data}")
        try:
            resp = self._uds_client.write_data_by_identifier(
                int(did, 16), bytes.fromhex(data))
            self._show_resp(self._did_result, resp)
        except ValueError:
            self._did_result.setText("DID/数据 Hex格式错误")

    def _send_routine(self):
        if not self._uds_client:
            self._routine_result.setText("请先创建UDS连接")
            return
        rid = self._routine_id.text().strip()
        idx = self._routine_type.currentIndex()
        ctrl = [0x01, 0x02, 0x03][idx]
        self._log(f">>> 31 {ctrl:02X} {rid}")
        try:
            resp = self._uds_client.routine_control(int(rid, 16), ctrl)
            self._show_resp(self._routine_result, resp)
        except ValueError:
            self._routine_result.setText("RoutineID Hex格式错误")

    def _send_raw(self):
        raw = self._raw_edit.text().strip()
        self._log(f">>> {raw}")
        if not self._channel_key:
            self._raw_result.setText("未选择通道")
            return
        try:
            data = bytes.fromhex(raw.replace(' ', ''))
        except ValueError:
            self._raw_result.setText("Hex格式错误")
            return
        req_id = int(self._req_id.text(), 16)
        if self._dm.get_instance(self._channel_key) is None:
            self._raw_result.setText("发送失败(通道未连接)")
            return
        # 异步发送: 硬件无ACK时同步 send 会阻塞 UI ~1.5s/帧
        ok = self._dm.send_async(self._channel_key, req_id, data)
        self._raw_result.setText("已发送" if ok else "发送队列已满, 帧被丢弃")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._log_text.appendPlainText(f"[{ts}] {msg}")
        logger.info(f"UDS: {msg}")

    def set_channel(self, channel_key: str):
        self._channel_key = channel_key
        self._channel_combo.clear()
        for ch in self._dm.list_channels():
            self._channel_combo.addItem(ch.key)
        idx = self._channel_combo.findText(channel_key)
        self._channel_combo.setCurrentIndex(idx if idx >= 0 else -1)

    def closeEvent(self, event):
        if self._channel_key:
            self._hub.set_channel_paused(self._channel_key, False)
        super().closeEvent(event)
