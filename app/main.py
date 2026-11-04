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


def _selftest(path):
    """打包后的环境自检：写 logs/selftest.txt（给别人装完出问题时用来定位）。"""
    lines = []
    ok = True
    try:
        import imagecodecs, tifffile, oiffile, czifile, liffile      # noqa: F401
        lines.append("imagecodecs %s (%s)" % (imagecodecs.__version__,
                                               imagecodecs.__file__))
        for name in ("lzw_decode", "zlib_decode", "jpeg_decode", "deflate_decode"):
            ok = ok and hasattr(imagecodecs, name)
            lines.append("  %s: %s" % (name, "ok" if hasattr(imagecodecs, name) else "MISSING"))
        lines.append("tifffile %s / oiffile / czifile / liffile: import ok"
                     % tifffile.__version__)
    except Exception as exc:                     # noqa: BLE001
        ok = False
        lines.append("依赖导入失败: %r" % (exc,))
    if path:
        try:
            from core import loader
            item = loader.probe(path)
            lines.append("探测: %s frames=%s channels=%s %sx%s"
                         % (item.name, item.frames, len(item.channels or []),
                            item.width, item.height))
            stack = loader.load_stack(item)
            lines.append("解码: shape=%s dtype=%s" % (stack.shape, stack.dtype))
        except Exception as exc:                 # noqa: BLE001
            ok = False
            lines.append("打开文件失败: %r" % (exc,))
    try:
        with open(os.path.join(paths.LOG_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
            f.write(("OK\n" if ok else "FAIL\n") + "\n".join(lines))
    except Exception:                            # noqa: BLE001
        pass
    print("\n".join(lines))
    return 0 if ok else 2


def main():
    _setup_log()
    if "--selftest" in sys.argv:
        _setup_log()
        i = sys.argv.index("--selftest")
        target = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        return _selftest(target)
    try:
        from version import VERSION as app_version
    except Exception:                           # noqa: BLE001
        app_version = "dev"
    import logging
    logging.info("=== Image capture %s 启动 ===", app_version)
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from ui import theme
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setApplicationVersion(app_version)
    app.setOrganizationName("Image capture")
    app.setFont(theme.ui_font(theme.SIZE_BODY))
    app.setStyleSheet(theme.qss())      # 全局：菜单 / 对话框 / 弹层也统一

    # Qt 自带控件的文字（是/否、确定/取消、下拉列表…）用中文，避免中英混排
    from ui.appstyle import ThemedStyle
    app.setStyle(ThemedStyle(app.style()))

    _tr = QTranslator(app)
    _qn = os.path.join(QLibraryInfo.path(QLibraryInfo.TranslationsPath), "qtbase_zh_CN.qm")
    if os.path.exists(_qn) and _tr.load(_qn):
        app.installTranslator(_tr)
    QLocale.setDefault(QLocale(QLocale.Chinese, QLocale.China))
    icon = os.path.join(paths.ASSETS_DIR, "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
