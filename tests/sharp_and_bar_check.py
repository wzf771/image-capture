# -*- coding: utf-8 -*-
"""验证两件事：① 预览清晰度 ② 标尺可拖动且导出位置一致。"""
import os
import sys

import numpy as np
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                 # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

import paths                                                    # noqa: E402
from core import loader, render                                 # noqa: E402
from core.model import Group, Settings                          # noqa: E402
from ui.main_window import MainWindow                           # noqa: E402
from _samples import P  # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检")
SRC = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")
CZI = os.environ.get("IMAGECAPTURE_CZI", "")


def sharpness(rgb):
    g = np.asarray(Image.fromarray(rgb).convert("L")).astype(np.float32)
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1])
    return float(lap.var())


def main():
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))

    # ---------- ① 预览清晰度：老管线 vs 新管线
    item = loader.probe(SRC)
    target = 620
    old_planes = render.preview_planes(item, 0, 1100)
    old_rgb = render.compose(old_planes, item.channels)
    old_rgb = np.asarray(Image.fromarray(old_rgb).resize((target, target), Image.BILINEAR))
    new_planes, _used = render.preview_for_view(item, 0, (0.0, 0.0, 1.0, 1.0),
                                                (target, target))
    new_rgb = render.compose(new_planes, item.channels)
    s_old, s_new = sharpness(old_rgb), sharpness(new_rgb)
    print("① 预览清晰度（数值越大越锐）")
    print("   老管线 %.0f  →  新管线 %.0f   （提升 %.0f%%）" % (s_old, s_new, (s_new / max(s_old, 1) - 1) * 100))
    board = Image.new("RGB", (target * 2 + 12, target), (10, 10, 14))
    board.paste(Image.fromarray(old_rgb), (0, 0))
    board.paste(Image.fromarray(new_rgb), (target + 12, 0))
    board.save(os.path.join(OUT, "预览清晰度对比.png"))

    # ---------- ② 标尺拖动 + 导出位置一致
    win = MainWindow()
    win.resize(1460, 940)
    win.items = [loader.probe(SRC), loader.probe(CZI)]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.cb_pos.blockSignals(True)
    win.cb_pos.setCurrentIndex(4)          # 自定义
    win.cb_pos.blockSignals(False)
    win.set_view_mode("crop")
    app.processEvents()
    before = win._last_bar_anchor
    # 真实鼠标拖动：按在标尺上，拖到画布中间偏上
    from PySide6.QtCore import QPoint, Qt as QtNS
    from PySide6.QtTest import QTest
    canvas = win.canvas
    zone = canvas._bar_zones["bar"]
    start = QPoint(zone.center().x(), zone.center().y())
    w0, h0 = canvas._bar_anchors["size"]
    target_dx = int((0.35 - before[0]) * w0)
    target_dy = int((0.28 - before[1]) * h0)
    QTest.mousePress(canvas, QtNS.LeftButton, QtNS.NoModifier, start)
    QTest.mouseMove(canvas, QPoint(start.x() + target_dx, start.y() + target_dy))
    QTest.mouseRelease(canvas, QtNS.LeftButton, QtNS.NoModifier,
                       QPoint(start.x() + target_dx, start.y() + target_dy))
    app.processEvents()
    after = win._last_bar_anchor
    print("② 标尺拖动：拖之前 %s → 拖之后 %s" % (
        tuple(round(v, 3) for v in before), tuple(round(v, 3) for v in after)))
    win.grab().save(os.path.join(OUT, "标尺拖动_界面.png"))
    item2 = win.cur_item
    group = win.cur_group
    st = Settings()
    st.out_subdir = "flat"
    st.out_suffix = "_drag"
    st.bar_thickness = 0
    st.bar_font_size = 0
    st.bar_margin = 0
    st.bar_text = True
    st.bar_ticks = "ends6"
    st.bar_color = "auto"
    group.box = group.box_for(item2)
    files, row = render.export_item(item2, group, st, frame=0, out_root=OUT)
    # 再导一张"不画标尺"的，两张做差才能精确量出标尺的位置
    st2 = Settings()
    st2.out_subdir = "flat"
    st2.out_suffix = "_nobar"
    st2.bar_enabled = False
    files2, _row2 = render.export_item(item2, group, st2, frame=0, out_root=OUT)
    a = np.asarray(Image.open(files[0]).convert("L")).astype(np.float32)
    b = np.asarray(Image.open(files2[0]).convert("L")).astype(np.float32)
    H, W = a.shape
    diff = np.abs(a - b)
    ys, xs = np.where(diff > 30)
    if xs.size:
        cx, cy = xs.mean() / W, ys.mean() / H
        print("   导出图里标尺（与无标尺图做差）重心：(%.3f, %.3f)，目标位置 (0.350, 0.280)"
              % (cx, cy))
    print("   导出文件:", os.path.basename(files[0]), a.shape)


if __name__ == "__main__":
    main()
