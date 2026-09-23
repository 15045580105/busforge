"""
BusForge - 独立总线分析与诊断工具

启动入口。完全独立运行，不依赖任何后端服务。
直接通过DLL与CAN硬件通信。

用法:
    python main.py
"""

import sys
import os
import logging

# 确保项目根目录在Python路径中
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.config import AppConfig


def setup_logging():
    """配置日志"""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )


def main():
    """主入口"""
    setup_logging()
    logger = logging.getLogger("BusForge")
    logger.info("=" * 50)
    logger.info("BusForge v0.1.0 - 总线分析与诊断工具")
    logger.info("=" * 50)

    # 加载配置
    config = AppConfig.load()
    logger.info(f"配置已加载 (主题: {config.theme})")

    # 创建Qt应用
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    # 高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("BusForge")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("BusForge")

    # 全局应用暖灰专业工业风主题
    from app.ui.styles import get_theme
    app.setStyleSheet(get_theme(config.theme))

    # 绑定全局UI状态单例 (语言/进制) - 必须在创建任何UI组件前,
    # 以便工具栏/工程树/面板按已持久化的语言与进制渲染
    from app.common.ui_settings import UISettings
    UISettings.instance().bind(config)

    # 绑定工作空间管理器 (读取 save_dir, 默认=运行/安装路径)
    from app.common.workspace import WorkspaceManager
    WorkspaceManager.bind(config)

    # 初始化设备管理器 (设备定义按工程私有, 随 .bfproj 加载; 启动不连硬件)
    from app.devices.device_manager import DeviceManager
    DeviceManager.instance()

    # Logger 自动记录监听 (跟随项目运行自动开始, 开关在全局配置)
    from app.recorder.can_logger import AutoLogger
    AutoLogger.instance()

    # 创建主窗口
    from app.ui.main_window import MainWindow
    window = MainWindow(config)
    window.show()

    logger.info("应用已启动")

    # 运行事件循环
    exit_code = app.exec()

    logger.info("应用已退出")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
