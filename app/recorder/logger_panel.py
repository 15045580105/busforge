# -*- coding: utf-8 -*-
"""Logger 面板 - 独立报文记录模块 (与 Trace 平级, 各自独立订阅中台)

布局: 图标标题 -> 存储位置+全局配置快接 -> 格式/路径 -> 开始/停止
      -> 跟随项目运行自动记录 -> 项目日志文件预览 (可导出/删除)
"""
import re
import shutil
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QLabel, QFileDialog, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView, QDialog, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import QTimer, Qt, QEvent, QPoint, QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl

from app.recorder.can_logger import (
    CanLogger, default_log_path, logger_root,
)
from app.devices.device_manager import DeviceManager
from app.common.i18n import tr
from app.ui.toolbar_widget import _ToolButton

# 通道多选下拉列表行高 (px) - 保证至少 4 路可见时高度一致
_ROW_H = 30


class _CheckCombo(QWidget):
    """多选下拉: 按钮弹出内嵌可勾选列表的弹层 (QListWidget in QDialog Popup)。

    用 QDialog(Popup) 替代 QMenu+QWidgetAction——QMenu 在 PySide6 下
    点击内部条目会触发自动收起，导致复选框难以连续点击；QDialog Popup
    仅在点击弹层外部时关闭，内部条目点击完全由 QListWidget 处理。
    整行点击即切换勾选, 选中项以逗号串显示在按钮上。
    对外 API: set_keys(list) / selected_keys()->set / count()->int。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._btn = QPushButton()
        self._btn.setObjectName("checkComboBtn")   # 仿输入框字段外观 (见 styles.py)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._show_popup)
        lay.addWidget(self._btn)

        # 弹层: QDialog(Popup) — 点外部自动关闭, 点内部条目不收起
        self._dlg = QDialog(self,
                            Qt.WindowType.Popup
                            | Qt.WindowType.FramelessWindowHint)
        self._dlg.setObjectName("checkComboPopup")
        dlg_lay = QVBoxLayout(self._dlg)
        dlg_lay.setContentsMargins(2, 2, 2, 2)
        dlg_lay.setSpacing(0)
        self._list = QListWidget()
        self._list.setObjectName("checkComboList")
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemChanged.connect(lambda *_: self._update_text())
        dlg_lay.addWidget(self._list)
        self._update_text()

    def _show_popup(self):
        """在按钮正下方弹出, 宽度对齐按钮, 高度至少可显示 4 路通道"""
        w = max(self._btn.width(), 140)
        self._dlg.setFixedWidth(w)
        self._list.setMinimumWidth(w - 8)
        rows = max(self._list.count(), 4)   # 不足 4 路也预留 4 行高度
        self._list.setFixedHeight(min(rows * _ROW_H + 8, 320))
        pos = self._btn.mapToGlobal(QPoint(0, self._btn.height()))
        self._dlg.move(pos)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    def _on_item_clicked(self, it):
        """整行点击切换勾选 (弹层不关闭)"""
        it.setCheckState(
            Qt.CheckState.Unchecked
            if it.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked)

    def set_keys(self, keys: list):
        """重建条目: 保留已有勾选, 新通道默认勾选"""
        old = {self._list.item(i).text():
               self._list.item(i).checkState() == Qt.CheckState.Checked
               for i in range(self._list.count())}
        self._list.blockSignals(True)
        self._list.clear()
        for k in keys:
            it = QListWidgetItem(k)
            # 不设 ItemIsUserCheckable: Qt 原生响应复选框点击 + itemClicked
            # 手动切换 = 双重切换等于没切; 去掉后 itemClicked 是唯一切换源,
            # 点复选框图标和点文字行效果一致
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            it.setSizeHint(QSize(0, _ROW_H))
            it.setCheckState(Qt.CheckState.Checked if old.get(k, True)
                             else Qt.CheckState.Unchecked)
            self._list.addItem(it)
        self._list.blockSignals(False)
        self._update_text()

    def count(self) -> int:
        return self._list.count()

    def selected_keys(self) -> set:
        return {self._list.item(i).text() for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked}

    def _update_text(self):
        sel = sorted(self.selected_keys())
        text = ", ".join(sel) if sel else tr("全部(未选择)")
        self._btn.setText(f"{text}  \u25be")


class LoggerPanel(QWidget):
    """报文记录面板: 配置 + 起停 + 自动记录 + 文件预览"""

    def __init__(self, channel_key: str = "", parent=None):
        super().__init__(parent)
        self._channel_key = channel_key or ""
        self._logger = CanLogger.instance()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # ---- 顶部工具栏 (与 Trace 同款: panelToolbar + 图标按钮) ----
        toolbar_wrap = QWidget()
        toolbar_wrap.setObjectName("panelToolbar")
        toolbar_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        toolbar = QHBoxLayout(toolbar_wrap)
        toolbar.setContentsMargins(6, 4, 6, 4)
        toolbar.setSpacing(4)

        # 跟随项目启停 (最左, 可勾选)
        self._auto_btn = _ToolButton("auto", "跟随项目启停", "跟随项目运行自动开始记录")
        self._auto_btn.setCheckable(True)
        from app.recorder.can_logger import _app_config
        cfg = _app_config()
        self._auto_btn.setChecked(
            bool(getattr(cfg, "logger_auto_start", False)))
        self._auto_btn.toggled.connect(self._on_auto_toggled)
        toolbar.addWidget(self._auto_btn)

        # 开始/停止记录
        self._start_btn = _ToolButton("run", "开始记录", "开始记录")
        self._start_btn.clicked.connect(self._start)
        toolbar.addWidget(self._start_btn)
        self._stop_btn = _ToolButton("stop", "停止记录", "停止记录", True)
        self._stop_btn.clicked.connect(self._stop)
        toolbar.addWidget(self._stop_btn)
        toolbar.addSpacing(8)

        # 全局配置 / 打开文件夹
        self._settings_btn = _ToolButton("settings", "全局配置", "全局配置")
        self._settings_btn.clicked.connect(self._open_global_settings)
        toolbar.addWidget(self._settings_btn)
        self._open_dir_btn = _ToolButton("new_project", "打开文件夹", "打开文件夹")
        self._open_dir_btn.clicked.connect(self._open_project_dir)
        toolbar.addWidget(self._open_dir_btn)

        toolbar.addStretch()
        # 记录状态指示 (最右)
        self._state_label = QLabel(tr("空闲"))
        self._state_label.setStyleSheet("color: #6c7086;")
        toolbar.addWidget(self._state_label)
        lay.addWidget(toolbar_wrap)

        # ---- 存储位置 + 格式 + 路径 ----
        form = QFormLayout()
        form.setContentsMargins(2, 6, 2, 2)
        self._root_label = QLabel()
        self._root_label.setObjectName("hintBar")   # 柔和提示条样式
        self._root_label.setWordWrap(True)
        form.addRow(self._root_label)
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        self._lbl_fmt = QLabel()
        fmt_row.addWidget(self._lbl_fmt)
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(["ASC", "BLF"])
        self._fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)
        self._fmt_combo.setFixedWidth(90)
        fmt_row.addWidget(self._fmt_combo)
        self._lbl_file = QLabel()
        fmt_row.addWidget(self._lbl_file)
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(tr("留空=按默认规则(项目名/日期/时间)"))
        fmt_row.addWidget(self._path_edit, 1)
        self._browse_btn = QPushButton(tr("浏览"))
        self._browse_btn.setProperty("btnRole", "neutral")
        self._browse_btn.clicked.connect(self._browse)
        fmt_row.addWidget(self._browse_btn)
        form.addRow(fmt_row)
        lay.addLayout(form)

        # ---- 记录过滤 (通道/报文ID/方向) ----
        self._flt_title = QLabel()
        self._flt_title.setObjectName("sectionHeader")
        lay.addWidget(self._flt_title)
        form2 = QFormLayout()
        form2.setContentsMargins(2, 4, 2, 2)
        self._lbl_ch = QLabel()
        self._lbl_ids = QLabel()
        self._lbl_dir = QLabel()
        self._ch_combo = _CheckCombo()   # 多选通道 (全选/空选=不限)
        form2.addRow(self._lbl_ch, self._ch_combo)
        self._ids_edit = QLineEdit()
        form2.addRow(self._lbl_ids, self._ids_edit)
        dir_row = QHBoxLayout()
        self._tx_chk = QCheckBox("TX")
        self._tx_chk.setChecked(True)
        self._rx_chk = QCheckBox("RX")
        self._rx_chk.setChecked(True)
        dir_row.addWidget(self._tx_chk)
        dir_row.addWidget(self._rx_chk)
        dir_row.addStretch()
        form2.addRow(self._lbl_dir, dir_row)
        lay.addLayout(form2)

        # ---- 文件预览 (项目文件夹下全部日志文件) ----
        self._prev_title = QLabel()
        self._prev_title.setObjectName("sectionHeader")
        lay.addWidget(self._prev_title)
        self._file_tree = QTreeWidget()
        self._file_tree.setColumnCount(3)
        self._file_tree.setHeaderLabels(
            [tr("文件名"), tr("大小"), tr("修改时间")])
        self._file_tree.setRootIsDecorated(False)
        self._file_tree.setAlternatingRowColors(True)
        self._file_tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._file_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 多选: Ctrl/Shift 加选, 供批量导出/删除
        self._file_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        hdr = self._file_tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self._file_tree, 1)

        # ---- 文件操作工具栏 (与顶部同款 panelToolbar) ----
        filebar_wrap = QWidget()
        filebar_wrap.setObjectName("panelToolbar")
        filebar_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        filebar = QHBoxLayout(filebar_wrap)
        filebar.setContentsMargins(6, 4, 6, 4)
        filebar.setSpacing(4)
        self._refresh_btn = _ToolButton("refresh", "刷新", "刷新")
        self._refresh_btn.clicked.connect(self._refresh_files)
        filebar.addWidget(self._refresh_btn)
        self._export_btn = _ToolButton("export", "导出", "导出")
        self._export_btn.clicked.connect(self._export_files)
        filebar.addWidget(self._export_btn)
        self._delete_btn = _ToolButton("clear", "删除", "删除", True)
        self._delete_btn.clicked.connect(self._delete_files)
        filebar.addWidget(self._delete_btn)
        filebar.addStretch()
        lay.addWidget(filebar_wrap)

        self._logger.state_changed.connect(self._on_state)
        self._logger.notice.connect(self._on_notice)
        from app.common.ui_settings import UISettings
        # 绑定方法: 工程切换丢弃本面板后 C++ 销毁自动断开
        # (lambda 连接不会自动断开, 会访问已删除的 C++ 对象)
        UISettings.instance().language_changed.connect(
            self._on_language_changed)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh_state)
        self._default_shown = ""   # 当前显示在路径框的默认路径 (未改过时起录重新生成)
        self._refresh_root_label()
        self.retranslate()
        self._show_default_path()
        self._start_btn.setEnabled(not self._logger.recording)
        self._stop_btn.setEnabled(self._logger.recording)

    # ------------------------------------------------------------------ #
    #  配置/起停
    # ------------------------------------------------------------------ #

    @property
    def recording(self) -> bool:
        return self._logger.recording

    def _on_language_changed(self, _lang):
        self.retranslate()

    def retranslate(self):
        self._start_btn.setText(tr("开始记录"))
        self._stop_btn.setText(tr("停止记录"))
        self._settings_btn.setText(tr("全局配置"))
        self._open_dir_btn.setText(tr("打开文件夹"))
        self._auto_btn.setText(tr("跟随项目启停"))
        self._auto_btn.setToolTip(tr("跟随项目运行自动开始记录"))
        self._prev_title.setText(tr("文件预览"))
        self._lbl_fmt.setText(tr("保存格式"))
        self._lbl_file.setText(tr("保存文件"))
        self._path_edit.setPlaceholderText(
            tr("留空=按默认规则(项目名/日期/时间)"))
        self._browse_btn.setText(tr("浏览"))
        self._refresh_btn.setText(tr("刷新"))
        self._export_btn.setText(tr("导出"))
        self._delete_btn.setText(tr("删除"))
        self._flt_title.setText(tr("记录过滤"))
        self._lbl_ch.setText(tr("通道"))
        self._lbl_ids.setText(tr("报文ID"))
        self._ids_edit.setPlaceholderText(tr("空=全部, 例: 0x5F, 95"))
        self._lbl_dir.setText(tr("方向"))
        self._file_tree.setHeaderLabels(
            [tr("文件名"), tr("大小"), tr("修改时间")])
        self._refresh_state()
        self._refresh_root_label()

    def _refresh_root_label(self):
        self._root_label.setText(str(logger_root()))

    def _open_global_settings(self):
        """快接: 打开全局配置并跳到 Logger 页"""
        w = self.parent()
        while w is not None and not hasattr(w, "open_settings_panel"):
            w = w.parent()
        if w is not None:
            w.open_settings_panel("logger")
        self._refresh_root_label()

    def _open_project_dir(self):
        """直接打开项目日志文件夹 (不存在则先创建)"""
        d = self._project_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _show_default_path(self):
        """路径框显示默认路径 (仅计算不建目录); 记录中不打扰"""
        if self._logger.recording:
            return
        p = default_log_path(self._fmt_combo.currentText().lower(),
                             create=False)
        self._path_edit.setText(p)
        self._default_shown = p

    def _on_auto_toggled(self, checked: bool):
        from app.recorder.can_logger import _app_config
        cfg = _app_config()
        if cfg is not None:
            cfg.logger_auto_start = checked
            try:
                cfg.save()
            except Exception:
                pass

    def _on_fmt_changed(self, _idx):
        # 路径还是默认/旧扩展名时随格式刷新默认路径
        p = self._path_edit.text().strip()
        if not p or p == self._default_shown \
                or p.lower().endswith((".asc", ".blf")):
            self._show_default_path()

    def _browse(self):
        ext = self._fmt_combo.currentText().lower()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("保存文件"),
            self._path_edit.text() or default_log_path(ext),
            f"{ext.upper()} (*.{ext})")
        if path:
            self._path_edit.setText(path)

    def _start(self):
        path = self._path_edit.text().strip()
        # 空或未改过的默认路径: 起录时重新生成 (时间戳取起录时刻)
        if not path or path == self._default_shown:
            path = default_log_path(self._fmt_combo.currentText().lower())
            self._path_edit.setText(path)
        ok, err = self._logger.start(
            path, self._fmt_combo.currentText().lower(), self._build_filt())
        if not ok:
            self._state_label.setText(err)
            self._state_label.setStyleSheet("color: #e53935;")

    def _stop(self):
        self._logger.stop()

    def _on_state(self, recording: bool, _path: str):
        self._start_btn.setEnabled(not recording)
        self._stop_btn.setEnabled(recording)
        self._fmt_combo.setEnabled(not recording)
        self._path_edit.setReadOnly(recording)
        if recording:
            self._tick.start()
        else:
            self._tick.stop()
            self._show_default_path()   # 停止后路径复位为新默认
        self._refresh_state()
        self._refresh_files()

    def _refresh_state(self):
        if self._logger.recording:
            self._state_label.setText(
                f"{tr('记录中')}: {self._logger.path} "
                f"({self._logger.count} {tr('帧')})")
            self._state_label.setStyleSheet("color: #4caf50;")
        else:
            self._state_label.setText(tr("空闲"))
            self._state_label.setStyleSheet("color: #6c7086;")

    def _on_notice(self, msg: str):
        """引擎提示 (如 0 帧未保存): 状态栏琥珀色展示"""
        self._state_label.setText(msg)
        self._state_label.setStyleSheet("color: #e8a33d;")

    # ------------------------------------------------------------------ #
    #  文件预览
    # ------------------------------------------------------------------ #

    def _project_dir(self) -> Path:
        name = DeviceManager.instance().active_project_name or "default"
        return logger_root() / name

    def _refresh_channels(self):
        """通道多选列表随活动工程刷新 (保留勾选, 新通道默认勾选)"""
        keys = list(DeviceManager.instance()._channels.keys())
        self._ch_combo.set_keys(keys)

    def _build_filt(self) -> dict:
        """收集过滤配置: 通道全选/空选=不限; ID 空=不限"""
        n = self._ch_combo.count()
        chs = self._ch_combo.selected_keys()
        ids = set()
        for tok in re.split(r"[,;\s]+", self._ids_edit.text().strip()):
            if not tok:
                continue
            try:
                ids.add(int(tok, 0))
            except ValueError:
                continue
        return {
            "channels": None if (not chs or len(chs) >= n) else chs,
            "ids": ids or None,
            "tx": self._tx_chk.isChecked(),
            "rx": self._rx_chk.isChecked(),
        }

    def _refresh_files(self):
        self._refresh_root_label()
        self._refresh_channels()
        self._file_tree.clear()
        d = self._project_dir()
        if not d.exists():
            return
        files = sorted(
            (p for p in d.rglob("*") if p.is_file()),
            key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            st = p.stat()
            item = QTreeWidgetItem([
                str(p.relative_to(d)),
                f"{st.st_size / 1024:.1f} KB",
                time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(st.st_mtime)),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, str(p))
            self._file_tree.addTopLevelItem(item)

    def _selected_paths(self) -> list[str]:
        return [it.data(0, Qt.ItemDataRole.UserRole)
                for it in self._file_tree.selectedItems()]

    def _export_files(self):
        paths = self._selected_paths()
        if not paths:
            return
        d = QFileDialog.getExistingDirectory(self, tr("导出到目录..."))
        if not d:
            return
        for s in paths:
            try:
                shutil.copy2(s, Path(d) / Path(s).name)
            except Exception as e:
                QMessageBox.warning(self, tr("提示"), f"{s}: {e}")
        self._refresh_files()

    def _delete_files(self):
        paths = self._selected_paths()
        if not paths:
            return
        if QMessageBox.question(
                self, tr("删除"),
                tr("确认删除所选 {n} 个文件?").format(n=len(paths))) \
                != QMessageBox.StandardButton.Yes:
            return
        for s in paths:
            try:
                Path(s).unlink(missing_ok=True)
            except Exception as e:
                logger_warn(e)
        self._refresh_files()

    def showEvent(self, event):
        self._refresh_files()
        self._show_default_path()
        super().showEvent(event)


def logger_warn(e):
    import logging
    logging.getLogger(__name__).warning(f"删除日志文件失败: {e}")
