"""
Script编辑器面板

Python语法高亮 + 变量浏览器 + 运行/停止 + 日志
"""

import logging
import time
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPlainTextEdit,
    QPushButton, QLabel, QComboBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QCompleter, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter

from app.common.variable_system import VariableRegistry
from app.datahub.data_hub import DataHub, KIND_FRAME
from app.devices.device_manager import DeviceManager

logger = logging.getLogger(__name__)


class PythonHighlighter(QSyntaxHighlighter):
    """Python语法高亮"""

    KEYWORDS = [
        'and', 'as', 'assert', 'async', 'await', 'break', 'class',
        'continue', 'def', 'del', 'elif', 'else', 'except', 'False',
        'finally', 'for', 'from', 'global', 'if', 'import', 'in',
        'is', 'lambda', 'None', 'nonlocal', 'not', 'or', 'pass',
        'raise', 'return', 'True', 'try', 'while', 'with', 'yield',
    ]

    def __init__(self, document):
        super().__init__(document)
        self._rules = []

        # 关键字
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#89b4fa"))
        kw_fmt.setFontWeight(QFont.Weight.Bold)
        for kw in self.KEYWORDS:
            self._rules.append((rf'\b{kw}\b', kw_fmt))

        # 字符串
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#a6e3a1"))
        self._rules.append((r'"[^"\\]*(\\.[^"\\]*)*"', str_fmt))
        self._rules.append((r"'[^'\\]*(\\.[^'\\]*)*'", str_fmt))

        # 注释
        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor("#6c7086"))
        cmt_fmt.setFontItalic(True)
        self._rules.append((r'#[^\n]*', cmt_fmt))

        # 数字
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#fab387"))
        self._rules.append((r'\b\d+\.?\d*\b', num_fmt))

        import re
        self._compiled = [(re.compile(pattern, re.MULTILINE), fmt)
                          for pattern, fmt in self._rules]

    def highlightBlock(self, text: str):
        for pattern, fmt in self._compiled:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class ScriptWorker(QThread):
    """脚本执行线程"""
    output = Signal(str)
    finished = Signal(bool)

    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self._code = code
        self._running = True
        self.handlers: dict = {}

    def run(self):
        try:
            # 创建脚本运行环境
            output_fn = lambda *a, **kw: self.output.emit(
                ' '.join(str(x) for x in a))
            dm = DeviceManager.instance()
            env = {
                '__builtins__': __builtins__,
                'print': output_fn,
                'var_get': VariableRegistry.instance().get_value,
                'var_set': VariableRegistry.instance().set_value,
                'var_create': lambda n, v=None: VariableRegistry.instance().create(n, v),
                'send_can': lambda ch, mid, data: dm.send(ch, mid, bytes(data)),
            }
            exec(self._code, env)
            # 注册事件处理器 (on_message 由 DataHub 订阅喂入)
            self.handlers = {k: env[k] for k in
                             ("on_start", "on_stop", "on_message")
                             if callable(env.get(k))}
            if 'on_start' in self.handlers:
                self.handlers['on_start']()
            self.finished.emit(True)
        except Exception as e:
            self.output.emit(f"错误: {e}")
            self.finished.emit(False)

    def stop(self):
        self._running = False


class ScriptEditorPanel(QWidget):
    """脚本编辑器面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._var_registry = VariableRegistry.instance()
        self._hub = DataHub.instance()
        self._sub_id = f"script_{id(self):x}"
        self._worker: Optional[ScriptWorker] = None
        self._current_file: str = ""

        self._setup_ui()
        self._hub.push.connect(self._on_push)

        # 变量刷新定时器
        self._var_timer = QTimer(self)
        self._var_timer.setInterval(500)
        self._var_timer.timeout.connect(self._refresh_variables)
        self._var_timer.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 工具栏
        toolbar = QHBoxLayout()

        self._run_btn = QPushButton("运行")
        self._run_btn.setObjectName("successBtn")
        self._run_btn.clicked.connect(self._run_script)
        toolbar.addWidget(self._run_btn)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setObjectName("dangerBtn")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_script)
        toolbar.addWidget(self._stop_btn)

        toolbar.addWidget(QLabel("通道:"))
        self._channel_combo = QComboBox()
        self._channel_combo.addItem("全局")
        for ch in DeviceManager.instance().list_channels():
            self._channel_combo.addItem(ch.key)
        toolbar.addWidget(self._channel_combo)

        toolbar.addStretch()

        load_btn = QPushButton("加载")
        load_btn.clicked.connect(self._load_file)
        toolbar.addWidget(load_btn)

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_file)
        toolbar.addWidget(save_btn)

        layout.addLayout(toolbar)

        # 主区域: 编辑器 + 变量浏览器
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 编辑器
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Cascadia Code", 11))
        self._editor.setTabStopDistance(40)
        self._editor.setPlaceholderText("# 输入Python脚本...\n# 可用API:\n# var_create(name, value)\n# var_get(name)\n# var_set(name, value)\n# print(...)")
        self._highlighter = PythonHighlighter(self._editor.document())
        editor_layout.addWidget(self._editor)

        splitter.addWidget(editor_widget)

        # 变量浏览器
        var_widget = QWidget()
        var_layout = QVBoxLayout(var_widget)
        var_layout.setContentsMargins(0, 0, 0, 0)

        var_layout.addWidget(QLabel("变量浏览器"))
        self._var_tree = QTreeWidget()
        self._var_tree.setHeaderLabels(["名称", "值", "类型"])
        self._var_tree.setColumnCount(3)
        self._var_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._var_tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._var_tree.header().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        var_layout.addWidget(self._var_tree)

        splitter.addWidget(var_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # 日志输出
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(2000)
        self._output.setFont(QFont("Cascadia Code", 10))
        self._output.setFixedHeight(120)
        layout.addWidget(self._output)

    def _run_script(self):
        code = self._editor.toPlainText()
        if not code.strip():
            return

        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._output.appendPlainText("--- 运行开始 ---")

        self._worker = ScriptWorker(code)
        self._worker.output.connect(self._on_output)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
        # 创建即注册: 中台按通道推送帧给 on_message
        ch = self._channel_combo.currentText()
        channels = None if ch == "全局" else [ch]
        self._hub.register(self._sub_id, {KIND_FRAME}, channels=channels)

    def _stop_script(self):
        if self._worker:
            if 'on_stop' in self._worker.handlers:
                try:
                    self._worker.handlers['on_stop']()
                except Exception as e:
                    logger.error(f"on_stop 异常: {e}")
            self._worker.stop()
            self._worker.terminate()
            self._worker = None
        self._hub.unregister(self._sub_id)
        self._on_finished(False)
        self._output.appendPlainText("--- 已停止 ---")

    def _on_push(self, sid: str, kind: str, payload):
        """中台推送帧 -> 脚本 on_message"""
        if sid != self._sub_id or kind != KIND_FRAME:
            return
        if not self._worker or 'on_message' not in self._worker.handlers:
            return
        handler = self._worker.handlers['on_message']
        for dto in payload:
            try:
                handler(dto.id, dto.data, dto.channel_key)
            except Exception as e:
                logger.error(f"on_message 异常: {e}")
                self._output.appendPlainText(f"on_message 异常: {e}")

    def _on_output(self, text: str):
        self._output.appendPlainText(text)

    def _on_finished(self, success: bool):
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._hub.unregister(self._sub_id)
        status = "成功" if success else "失败"
        self._output.appendPlainText(f"--- 运行{status} ---")

    def _refresh_variables(self):
        """刷新变量浏览器"""
        self._var_tree.clear()
        for var in self._var_registry.list_variables():
            item = QTreeWidgetItem(self._var_tree, [
                var.name,
                str(var.value),
                var.var_type.name,
            ])

    def _load_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "加载脚本", "", "Python Files (*.py);;All Files (*)")
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        """加载脚本文件"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._editor.setPlainText(content)
            self._current_file = path
            logger.info(f"脚本已加载: {path}")
        except Exception as e:
            logger.error(f"加载脚本失败: {e}")

    def _save_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存脚本", self._current_file,
            "Python Files (*.py);;All Files (*)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self._editor.toPlainText())
                self._current_file = path
                logger.info(f"脚本已保存: {path}")
            except Exception as e:
                logger.error(f"保存脚本失败: {e}")

    def closeEvent(self, event):
        self._hub.unregister(self._sub_id)
        super().closeEvent(event)
