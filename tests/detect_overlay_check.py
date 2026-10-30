# -*- coding: utf-8 -*-
"""标尺识别可视化自检（规格书 5.4.6 + 验收第 7 条）。

做什么：
  1 造一张带标尺的图（白线 300 px + 白字 "50 µm"）→ 跑自动标定
  2 检查识别结果被存到 item.detect，且 _detect_info 的端点对得上那条线
  3 离屏截图，**在画布像素里找青绿色的识别线**，核对画的位置对不对
  4 点「识别不对，手动框」→ 线要预填、长度要是真实线长、标签要提示
  5 放大后再截一次，线仍要贴在同一条线上（坐标换算不能只在 1× 对）
  6 切到"裁剪结果"视图，识别线必须收起来
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase, QImage            # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

import paths                                                      # noqa: E402
from core import loader                                           # noqa: E402
from ui.main_window import MainWindow                             # noqa: E402
from ui import worker                                             # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "识别可视化")
W, H = 900, 700
BAR_X0, BAR_X1, BAR_Y = 300, 600, 470     # 白线：300 px 长、6 px 粗
TEXT = "50 µm"


def make_png(path):
    a = np.full((H, W), 22, np.uint8)
    img = Image.fromarray(a).convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle([BAR_X0, BAR_Y, BAR_X1, BAR_Y + 6], fill=(240, 240, 240))
    try:
        f = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 34)
    except Exception:                                             # noqa: BLE001
        f = ImageFont.load_default(size=34)
    tw = d.textbbox((0, 0), TEXT, font=f)[2]
    d.text((BAR_X0 + (BAR_X1 - BAR_X0 - tw) / 2.0, BAR_Y - 52), TEXT,
           font=f, fill=(240, 240, 240))
    img.save(path)
    return path


def teal_pixels(pm, widget_w):
    """在截图里找识别线的青绿色 #00C2A8（含徽标）。返回 (xs, ys, 缩放比)。"""
    # 用 RGBA8888：字节序明确是 R,G,B,A（ARGB32 在小端机器上其实是 B,G,R,A，会认错色）
    qimg = pm.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pw, ph = qimg.width(), qimg.height()
    bpl = qimg.bytesPerLine()                     # 每行可能带对齐填充，不能直接 reshape
    flat = np.frombuffer(bytes(qimg.constBits()), np.uint8)[:bpl * ph]
    arr = flat.reshape(ph, bpl)[:, :pw * 4].reshape(ph, pw, 4).astype(int)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # 放宽一点：徽标是半透明的（alpha 220），和深灰底混过之后会暗一档
    m = (r < 80) & (g > 105) & (b > 80) & (g - b > 5) & (g - b < 90)
    ys, xs = np.where(m)
    return xs, ys, (pw / float(max(1, widget_w)))


def main():
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    for f in (r"C:\Windows\Fonts\msyh.ttc",):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    app.setFont(QFont("Microsoft YaHei", 9))

    png = make_png(os.path.join(OUT, "带标尺的图.png"))
    it = loader.probe(png)
    worker.job_calibrate([it])
    true_umpp = 50.0 / (BAR_X1 - BAR_X0)
    print("[1] 自动标定")
    print("    %s | umpp=%.5f 期望 %.5f（偏差 %.1f%%）| %s"
          % (it.calib, it.umpp, true_umpp,
             100 * abs(it.umpp - true_umpp) / true_umpp, it.calib))
    ok1 = it.detect is not None and abs(it.umpp - true_umpp) / true_umpp < 0.02

    win = MainWindow()
    win.resize(1460, 940)
    win.items = [it]
    win._regroup()
    win.set_view_mode("full")
    app.processEvents()

    info = win._detect_info(it)
    print("[2] 端点（原图归一化）")
    exp0 = (BAR_X0 / W, (BAR_Y + 3) / H)
    exp1 = (BAR_X1 / W, (BAR_Y + 3) / H)
    ok2 = bool(info) and all(abs(a - b) < 0.01 for a, b in zip(info["p0"], exp0)) \
        and all(abs(a - b) < 0.01 for a, b in zip(info["p1"], exp1))
    print("    识别 %s → %s，真值 %s → %s，标签「%s」"
          % (tuple(round(v, 3) for v in info["p0"]), tuple(round(v, 3) for v in info["p1"]),
             tuple(round(v, 3) for v in exp0), tuple(round(v, 3) for v in exp1), info["label"]))

    cv = win.canvas
    xs, ys, k = teal_pixels(cv.grab(), cv.width())
    print("[3] 画布上真的有青绿色的线")
    if xs.size:
        print("    青绿像素 %d 个，包围盒 x %d~%d / y %d~%d（截图缩放 %.2f）"
              % (xs.size, xs.min(), xs.max(), ys.min(), ys.max(), k))
    # 线本体的期望位置：把线段两端换算到画布坐标
    a = cv._pt_of(cv.norm_to_view(*info["p0"]))
    b = cv._pt_of(cv.norm_to_view(*info["p1"]))
    lay = (ys > a.y() - 6 * k)
    xs_line, ys_line = xs[lay], ys[lay]                           # 去掉右上的徽标
    if xs_line.size:
        got_cx = (xs_line.min() + xs_line.max()) / 2.0 / k
        got_cy = float(np.median(ys_line)) / k
        print("    线：画布坐标期望 x %.0f~%.0f / y %.0f，实测 x %.0f~%.0f / y %.0f"
              % (a.x(), b.x(), a.y(), xs_line.min() / k, xs_line.max() / k, got_cy))
        ok3 = (abs(got_cx - (a.x() + b.x()) / 2.0) < 8
               and abs(got_cy - (a.y() + b.y()) / 2.0) < 8
               and xs_line.min() / k < a.x() + 10 and xs_line.max() / k > b.x() - 10)
    else:
        ok3 = False
    # 徽标（右上角）
    ys_badge = ys[~lay]
    badge_ok = bool(ys_badge.size) and ys_badge.min() < 0.25 * cv.height()
    print("    右上角置信度徽标：%s" % ("有" if badge_ok else "没有"))
    cv.grab().save(os.path.join(OUT, "1_识别线_1x.png"))

    print("[4] 点「识别不对，手动框」")
    win.on_detect_fix()
    app.processEvents()
    line = cv._line
    print("    画线模式=%s，预填 %s，line_px=%.1f（真值 %d），标签「%s」"
          % (cv.line_mode(), [tuple(round(v, 3) for v in p) for p in line],
             it.line_px, BAR_X1 - BAR_X0, win.lbl_line.text()))
    ok4 = (cv.line_mode() and len(line) == 2
           and abs(it.line_px - (BAR_X1 - BAR_X0)) < 6
           and abs(float(win.field_line_um.value()) - 50.0) < 0.01)
    cv.grab().save(os.path.join(OUT, "2_手动框预填.png"))

    print("[5] 放大到 ×3 后线还贴在同一条线上")
    cv.set_line_mode(False)
    cv.set_zoom(3.0)
    win.refresh_preview()
    app.processEvents()
    xs2, ys2, k2 = teal_pixels(cv.grab(), cv.width())
    a2 = cv._pt_of(cv.norm_to_view(*info["p0"]))
    b2 = cv._pt_of(cv.norm_to_view(*info["p1"]))
    if xs2.size:
        lay2 = (ys2 > a2.y() - 6 * k2)
        xs_l2, ys_l2 = xs2[lay2], ys2[lay2]
    else:
        xs_l2, ys_l2 = xs2, ys2
    if xs_l2.size:
        cxm, cym = (xs_l2.min() + xs_l2.max()) / 2.0 / k2, float(np.median(ys_l2)) / k2
        print("    ×3 后：期望 x %.0f~%.0f / y %.0f，实测 x %.0f~%.0f / y %.0f"
              % (a2.x(), b2.x(), a2.y(), xs_l2.min() / k2, xs_l2.max() / k2, cym))
        ok5 = abs(cxm - (a2.x() + b2.x()) / 2.0) < 10 and abs(cym - (a2.y() + b2.y()) / 2.0) < 10
    else:
        print("    ×3 后没找到青绿像素（线可能被裁到窗口外）")
        ok5 = False
    cv.grab().save(os.path.join(OUT, "3_识别线_3x.png"))

    print("[6] 切到裁剪结果视图：识别线必须收起来")
    win.set_view_mode("crop")
    app.processEvents()
    xs3, _ys3, _k3 = teal_pixels(cv.grab(), cv.width())
    print("    裁剪视图里的青绿像素：%d（应为 0）" % xs3.size)
    ok6 = xs3.size == 0

    win.set_view_mode("full")
    win.refresh_preview()
    app.processEvents()
    win.grab().save(os.path.join(OUT, "4_整个界面.png"))
    print()
    print("结论:", "全部通过" if all((ok1, ok2, ok3, badge_ok, ok4, ok5, ok6)) else "有未通过项",
          "(1识别 %s / 2端点 %s / 3位置 %s / 徽标 %s / 4预填 %s / 5放大 %s / 6收起 %s)"
          % (ok1, ok2, ok3, badge_ok, ok4, ok5, ok6))
    print("截图目录:", OUT)
    return 0 if all((ok1, ok2, ok3, badge_ok, ok4, ok5, ok6)) else 1


if __name__ == "__main__":
    sys.exit(main())
