# -*- coding: utf-8 -*-
"""Image capture · 显微图像统一视野裁剪工具 —— 程序入口。"""
import os
import sys
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import paths                                       # noqa: E402


def _setup_log():
    paths.ensure_dirs()
    import logging
    logging.basicConfig(
        filename=paths.LOG_FILE, level=logging.INFO, filemode="a",
        format="%(asctime)s %(levelname)s %(message)s")

    def hook(kind, value, tb):
        text = "".join(traceback.format_exception(kind, value, tb))
        logging.error("未捕获的异常\n%s", text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                QMessageBox.critical(None, "出错了",
                                     "程序遇到问题：\n%s\n\n日志：%s"
                                     % (value, paths.LOG_FILE))
        except Exception:                           # noqa: BLE001
            pass
    sys.excepthook = hook


def main():
    _setup_log()
    try:
        from version import VERSION as app_version
    except Exception:                           # noqa: BLE001
        app_version = "dev"
    import logging
    logging.info("=== Image capture %s 启动 ===", app_version)
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setApplicationVersion(app_version)
    app.setOrganizationName("Image capture")
    app.setFont(QFont("Microsoft YaHei", 9))
    icon = os.path.join(paths.ASSETS_DIR, "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
