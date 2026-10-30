# -*- coding: utf-8 -*-
"""检查滚轮缩放：能放大、能缩小、不会越出图片范围。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"          # 自检不要动用户的参数文件
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtCore import QPoint, QPointF, Qt                  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase, QWheelEvent      # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

import paths                                                     # noqa: E402
from core import loader, render                                  # noqa: E402
from ui.main_window import MainWindow                            # noqa: E402
from _samples import P  # noqa: E402

FILES = [P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib"),
         P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\2a-1.oib"),
         P(r"E:\XY\相分离部\6.3\6.3\frap\3-6\FRAPR1.oib")]


def wheel(canvas, pos, notches):
    ev = QWheelEvent(QPointF(pos), QPointF(pos), QPoint(0, 0), QPoint(0, 120 * notches),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QApplication.sendEvent(canvas, ev)


def main():
    out = os.path.join(paths.OUTPUT_DIR, "_自检")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv[:1])
    for f in (r"C:\Windows\Fonts\msyh.ttc",):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1460, 940)
    items = [loader.probe(p) for p in FILES if os.path.exists(p)]
    win.items = items
    win._regroup()
    for it in items:
        try:
            win._thumbs[it.path] = render.make_thumb(it, 256)
        except Exception:                          # noqa: BLE001
            pass
    win.refresh_groups()
    win.refresh_strip()
    win.refresh_preview()
    win.show()
    app.processEvents()
    win.resize(1460, 940)
    app.processEvents()

    cv = win.canvas
    print("按钮:", [b.text() for b in win.findChildren(type(win.btn_view_full))][:4])

    def state(tag):
        r = cv._view_rect()
        inside = (r.left() <= 0 and r.top() <= 0
                  and r.right() >= cv.width() - 1 and r.bottom() >= cv.height() - 1)
        print("%-14s 缩放=%.2f  视图=%s  覆盖整个控件=%s" % (tag, cv.zoom(), r.getRect(), inside))

    state("初始")
    wheel(cv, QPoint(cv.width() // 2, cv.height() // 2), 4)
    state("放大 4 格")
    wheel(cv, QPoint(cv.width() // 2, cv.height() // 2), 10)
    state("再放大 10 格")
    win.grab().save(os.path.join(out, "界面_滚轮放大.png"))
    wheel(cv, QPoint(cv.width() // 2, cv.height() // 2), -40)
    state("往回缩到底")
    print("截图:", os.path.join(out, "界面_滚轮放大.png"))

    win.set_view_mode("crop")
    app.processEvents()
    print("切到裁剪结果后 缩放=%.2f" % cv.zoom())
    win.set_view_mode("full")
    app.processEvents()
    print("切回原图显示后 缩放=%.2f" % cv.zoom())


if __name__ == "__main__":
    main()
