# -*- coding: utf-8 -*-
"""验证：① 滚轮缩放时裁剪框不变形 ② 通道改了缩略图会重出。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtCore import QPoint, QPointF, Qt                    # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase, QWheelEvent        # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

import paths                                                       # noqa: E402
from core import loader, render                                    # noqa: E402
from ui.main_window import MainWindow                              # noqa: E402
from _samples import P  # noqa: E402

CZI = P(r"E:\ImageCapture\789\Snap-14700-Airyscan Processing-04.czi")


def box_physical(canvas):
    """把裁剪框在屏幕上的位置换算回图片物理坐标（µm）。"""
    box = canvas.box()
    br = canvas._box_rect()
    vx, vy, vw, vh = canvas.view_um()
    # 视图永远铺满控件，所以按控件尺寸换算（跟画布内部一致）
    W, H = float(max(1, canvas.width())), float(max(1, canvas.height()))
    px = vx + br.left() / W * vw
    py = vy + br.top() / H * vh
    pw = br.width() / W * vw
    ph = br.height() / H * vh
    return (round(px, 2), round(py, 2), round(pw, 2), round(ph, 2), box)


def wheel(canvas, notches):
    pos = QPointF(canvas.width() / 2.0, canvas.height() / 2.0)
    ev = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, 120 * notches),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QApplication.sendEvent(canvas, ev)


def main():
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1460, 940)
    item = loader.probe(CZI)
    win.items = [item]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.refresh_preview()
    win.show()
    app.processEvents()
    win.resize(1460, 940)
    app.processEvents()
    cv = win.canvas
    print("① 缩放时裁剪框是否跟着变形")
    base = box_physical(cv)
    print("   缩放 1.00x：框物理位置 %s（组里存的 %s）" % (base[:4], base[4]))
    for n in (4, 4, 4, 4, 4, -20, 4, 4, -20, 4):
        wheel(cv, n)
        now = box_physical(cv)
        tol = max(1.0, 0.015 * base[2])      # 允许整数像素取整带来的 1.5% 误差
        same = all(abs(a - b) < tol for a, b in zip(now[:4], base[:4]))
        print("   滚轮 %+3d 格 → 缩放 %.2fx：框 %s  %s" % (n, cv.zoom(), now[:4],
                                                        "一致 OK" if same else "偏了 BAD"))
    print("② 改通道后缩略图是否重出")
    p1 = loader.thumb_path(item)
    item.channels[0].color = (255, 214, 0)
    item.channels[0].black, item.channels[0].white = 3, 40
    p2 = loader.thumb_path(item)
    print("   改之前缓存:", os.path.basename(p1)[:12])
    print("   改之后缓存:", os.path.basename(p2)[:12],
          "已换新 OK" if p1 != p2 else "还是旧的 BAD")
    path = render.make_thumb(item, 256)
    print("   新缩略图:", os.path.basename(path), os.path.getsize(path), "字节")
    out = os.path.join(paths.OUTPUT_DIR, "_自检")
    os.makedirs(out, exist_ok=True)
    win.refresh_strip()
    app.processEvents()
    win.grab().save(os.path.join(out, "缩略图刷新.png"))


if __name__ == "__main__":
    main()
