"""
全局配置面板 - 单实例 (ADS dock)

像"设备管理"一样以停靠面板打开。左侧分区导航 + 右侧堆叠页:
- 工作空间: 记忆中的项目列表 (名称/文件路径/保存状态) + 会话控制
            (启动自动恢复开关 / 保存 / 导入 / 从记忆移除 / 清空工作空间)
- 主题:     主题选择器 (实时换肤并持久化到 AppConfig.theme)

所有文本经 tr(), 订阅 UISettings.language_changed 实现中英文实时切换。
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QLabel,
    QCheckBox, QComboBox, QMessageBox, QAbstractItemView, QApplication,
    QLineEdit, QFileDialog, QSpinBox
)
from PySide6.QtCore import Qt

from pathlib import Path

from app.core.device_manager import DeviceManager
from app.core.workspace import WorkspaceManager
from app.core.ui_settings import UISettings
from app.core.i18n import tr
from app.core.can_logger import MIN_SIZE_MB, MAX_SIZE_MB, logger_root
from app.ui.styles import THEMES, get_theme

logger = logging.getLogger(__name__)

# 工作空间项目表列
WS_COLS = ["名称", "文件路径", "状态"]


class SettingsPanel(QWidget):
    """全局配置面板 (单实例)"""

    def __init__(self, project_tree, config, parent=None):
        super().__init__(parent)
        self._tree = project_tree
        self._config = config
        self._dm = DeviceManager.instance()
        self._ui = UISettings.instance()
        self._loading = False

        self._setup_ui()
        self._connect_signals()
        self.retranslateUi()
        self.reload_workspace()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ---- 左侧分区导航 ----
        self._nav = QListWidget()
        self._nav.setFixedWidth(140)
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self._nav)

        # ---- 右侧堆叠页 ----
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_workspace_page())
        self._stack.addWidget(self._build_theme_page())
        self._stack.addWidget(self._build_logger_page())
        layout.addWidget(self._stack, 1)

        self._nav.setCurrentRow(0)

    def _build_workspace_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        self._ws_title = QLabel()
        f = self._ws_title.font()
        f.setBold(True)
        self._ws_title.setFont(f)
        v.addWidget(self._ws_title)

        self._auto_restore = QCheckBox()
        self._auto_restore.setChecked(
            bool(getattr(self._config, "auto_restore_session", True)))
        self._auto_restore.toggled.connect(self._on_auto_restore_toggled)
        v.addWidget(self._auto_restore)

        # 保存路径配置 (自动保存模型: 此处只配置保存到哪里)
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._path_label = QLabel()
        path_row.addWidget(self._path_label)
        self._path_edit = QLineEdit()
        self._path_edit.setText(str(WorkspaceManager.save_dir()))
        self._path_edit.editingFinished.connect(self._on_path_edited)
        path_row.addWidget(self._path_edit, 1)
        self._btn_browse = QPushButton()
        self._btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_browse.clicked.connect(self._on_browse_save_dir)
        path_row.addWidget(self._btn_browse)
        self._btn_default = QPushButton()
        self._btn_default.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_default.clicked.connect(self._on_reset_save_dir)
        path_row.addWidget(self._btn_default)
        v.addLayout(path_row)

        self._path_hint = QLabel()
        self._path_hint.setWordWrap(True)
        self._path_hint.setStyleSheet("color: #6c7086;")
        v.addWidget(self._path_hint)

        self._ws_table = QTableWidget()
        self._ws_table.setColumnCount(len(WS_COLS))
        self._ws_table.setAlternatingRowColors(True)
        self._ws_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._ws_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._ws_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._ws_table.verticalHeader().setVisible(False)
        hdr = self._ws_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self._ws_table, 1)
        return page

    def _build_theme_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        self._theme_title = QLabel()
        f = self._theme_title.font()
        f.setBold(True)
        self._theme_title.setFont(f)
        v.addWidget(self._theme_title)

        row = QHBoxLayout()
        self._theme_label = QLabel()
        row.addWidget(self._theme_label)
        self._theme_combo = QComboBox()
        self._loading = True
        for key, disp in THEMES.items():
            self._theme_combo.addItem(disp, key)
        cur = getattr(self._config, "theme", "soft_tech")
        idx = self._theme_combo.findData(cur)
        self._theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._loading = False
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        row.addWidget(self._theme_combo)
        row.addStretch()
        v.addLayout(row)
        v.addStretch()
        return page

    def _build_logger_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        self._lg_title = QLabel()
        f = self._lg_title.font()
        f.setBold(True)
        self._lg_title.setFont(f)
        v.addWidget(self._lg_title)

        # 存储位置
        row = QHBoxLayout()
        self._lg_dir_label = QLabel()
        row.addWidget(self._lg_dir_label)
        self._lg_dir_edit = QLineEdit()
        self._lg_dir_edit.setText(
            getattr(self._config, "logger_dir", "") or str(logger_root()))
        self._lg_dir_edit.editingFinished.connect(self._on_logger_dir_edited)
        row.addWidget(self._lg_dir_edit, 1)
        self._lg_dir_browse = QPushButton()
        self._lg_dir_browse.clicked.connect(self._on_logger_dir_browse)
        row.addWidget(self._lg_dir_browse)
        self._lg_dir_default = QPushButton()
        self._lg_dir_default.clicked.connect(self._on_logger_dir_reset)
        row.addWidget(self._lg_dir_default)
        v.addLayout(row)
        self._lg_dir_hint = QLabel()
        self._lg_dir_hint.setWordWrap(True)
        self._lg_dir_hint.setStyleSheet("color: #6c7086;")
        v.addWidget(self._lg_dir_hint)

        # 单文件上限
        row2 = QHBoxLayout()
        self._lg_size_label = QLabel()
        row2.addWidget(self._lg_size_label)
        self._lg_size_spin = QSpinBox()
        self._lg_size_spin.setRange(MIN_SIZE_MB, MAX_SIZE_MB)
        self._lg_size_spin.setSingleStep(50)
        self._lg_size_spin.setSuffix(" MB")
        self._lg_size_spin.setValue(
            int(getattr(self._config, "logger_max_size_mb", 100) or 100))
        self._lg_size_spin.valueChanged.connect(self._on_logger_size_changed)
        row2.addWidget(self._lg_size_spin)
        row2.addStretch()
        v.addLayout(row2)
        v.addStretch()
        return page

    def show_page(self, key: str):
        """快捷跳转: workspace/theme/logger"""
        idx = {"workspace": 0, "theme": 1, "logger": 2}.get(key, 0)
        self._stack.setCurrentIndex(idx)
        self._nav.setCurrentRow(idx)

    def _connect_signals(self):
        # 工程结构变化 -> 刷新工作空间列表
        if self._tree is not None:
            self._tree.project_created.connect(lambda _n: self.reload_workspace())
            self._tree.project_loaded.connect(lambda _n: self.reload_workspace())
            self._tree.project_switched.connect(lambda _i: self.reload_workspace())
        self._dm.pool_changed.connect(self.reload_workspace)
        # 语言切换 -> 重译
        self._ui.language_changed.connect(lambda _l: self.retranslateUi())

    def _on_nav_changed(self, row: int):
        self._stack.setCurrentIndex(row)

    # ------------------------------------------------------------------ #
    #  工作空间
    # ------------------------------------------------------------------ #

    def reload_workspace(self):
        """刷新记忆中的项目列表 (数据源: 实时工程列表)"""
        if self._tree is None:
            return
        self._ws_table.setRowCount(0)
        projects = self._tree.serialize_all_projects()
        active = self._tree.project_manager.active_index
        for i, p in enumerate(projects):
            row = self._ws_table.rowCount()
            self._ws_table.insertRow(row)
            name_item = QTableWidgetItem(p.get('project_name', ''))
            if i == active:
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
            self._ws_table.setItem(row, 0, name_item)
            path = p.get('file_path', '') or ""
            self._ws_table.setItem(row, 1, QTableWidgetItem(path))
            saved = tr("已保存") if path else tr("未保存")
            self._ws_table.setItem(row, 2, QTableWidgetItem(saved))

    def _on_auto_restore_toggled(self, checked: bool):
        self._config.auto_restore_session = checked
        try:
            self._config.save()
        except Exception as e:
            logger.warning(f"保存 auto_restore_session 失败: {e}")
        if not checked:
            # 关闭自动恢复即清空会话文件, 下次启动不再恢复
            WorkspaceManager.clear()

    def _on_path_edited(self):
        """手动编辑保存路径后应用"""
        self._apply_save_dir(self._path_edit.text().strip())

    def _on_browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, tr("选择保存路径"), str(WorkspaceManager.save_dir()))
        if d:
            self._apply_save_dir(d)

    def _on_reset_save_dir(self):
        """恢复默认保存路径 (运行/安装路径)"""
        self._apply_save_dir(str(WorkspaceManager.default_save_dir()))

    def _apply_save_dir(self, path: str):
        """应用新保存目录: 写配置 + 把现有工程迁移过去 + 刷新"""
        if not path:
            return
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, tr("提示"),
                                tr("无法创建目录: {path}").format(path=path))
            return
        self._config.save_dir = path
        try:
            self._config.save()
        except Exception as e:
            logger.warning(f"保存 save_dir 失败: {e}")
        self._path_edit.setText(str(WorkspaceManager.save_dir()))
        # 迁移现有工程存档到新目录 (autosave 会删除旧路径文件)
        if self._tree is not None:
            self._tree.autosave()
        self.reload_workspace()
        logger.info(f"保存路径已更新: {path}")

    # ------------------------------------------------------------------ #
    #  主题
    # ------------------------------------------------------------------ #

    def _on_theme_changed(self, index: int):
        if self._loading or index < 0:
            return
        name = self._theme_combo.itemData(index)
        if not name:
            return
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_theme(name))
        self._config.theme = name
        try:
            self._config.save()
        except Exception as e:
            logger.warning(f"保存主题失败: {e}")
        logger.info(f"主题已切换: {name}")

    # ------------------------------------------------------------------ #
    #  Logger
    # ------------------------------------------------------------------ #

    def _on_logger_dir_edited(self):
        self._apply_logger_dir(self._lg_dir_edit.text().strip())

    def _on_logger_dir_browse(self):
        d = QFileDialog.getExistingDirectory(
            self, tr("选择保存路径"), str(logger_root()))
        if d:
            self._apply_logger_dir(d)

    def _on_logger_dir_reset(self):
        """恢复默认: 保存目录/logger"""
        from app.core.workspace import WorkspaceManager as WM
        self._apply_logger_dir(str(WM.save_dir() / "logger"))

    def _apply_logger_dir(self, path: str):
        if not path:
            return
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, tr("提示"),
                                tr("无法创建目录: {path}").format(path=path))
            return
        self._config.logger_dir = path
        try:
            self._config.save()
        except Exception as e:
            logger.warning(f"保存 logger_dir 失败: {e}")
        self._lg_dir_edit.setText(path)

    def _on_logger_size_changed(self, val: int):
        self._config.logger_max_size_mb = val
        try:
            self._config.save()
        except Exception as e:
            logger.warning(f"保存 logger_max_size_mb 失败: {e}")

    # ------------------------------------------------------------------ #
    #  国际化
    # ------------------------------------------------------------------ #

    def retranslateUi(self):
        """按当前语言重设全部文本"""
        # 导航
        self._nav.clear()
        self._nav.addItem(tr("工作空间"))
        self._nav.addItem(tr("主题"))
        self._nav.addItem(tr("Logger"))
        row = self._stack.currentIndex()
        self._nav.setCurrentRow(row if row >= 0 else 0)

        # 工作空间页
        self._ws_title.setText(tr("工作空间"))
        self._auto_restore.setText(tr("启动时自动恢复上次会话"))
        self._ws_table.setHorizontalHeaderLabels([tr(c) for c in WS_COLS])
        self._path_label.setText(tr("保存路径:"))
        self._btn_browse.setText(tr("浏览..."))
        self._btn_default.setText(tr("恢复默认"))
        self._path_hint.setText(tr(
            "工程在创建/更改/删除时自动保存到该目录; "
            "删除工程或面板会同步删除对应存档。"))

        # 主题页
        self._theme_title.setText(tr("主题"))
        self._theme_label.setText(tr("当前主题"))
        self._loading = True
        for i in range(self._theme_combo.count()):
            key = self._theme_combo.itemData(i)
            self._theme_combo.setItemText(i, tr(THEMES.get(key, key)))
        self._loading = False

        # Logger 页
        self._lg_title.setText(tr("Logger"))
        self._lg_dir_label.setText(tr("存储位置:"))
        self._lg_dir_browse.setText(tr("浏览..."))
        self._lg_dir_default.setText(tr("恢复默认"))
        self._lg_dir_hint.setText(tr(
            "记录时自动在其下按 项目名/日期 创建子目录, 文件按时间命名; "
            "单文件超过上限自动轮转新文件。"))
        self._lg_size_label.setText(tr("单文件上限:"))

        self.reload_workspace()
