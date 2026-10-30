# -*- coding: utf-8 -*-
"""导入后清晰度基线（规格书 §2.7 冻结条款用）。

用法：
    python sharpness_baseline.py save     # 改造前跑一次，存基线
    python sharpness_baseline.py check    # 每次改造后跑，与基线比

测的是画布上真正显示出来的图（先摘掉裁剪框与标尺叠加层，只留图像本身），
指标用拉普拉斯方差，越大越锐。基线存在 output/_自检/清晰度基线/。

**重录记录**（改的必须是"渲染口径"，不是"锐化管线"）：
  · 2026-09-23 改 CZI 通道合并：Snap-14700 里"原始版 + 处理版"两层合并成一层，
    预览不再叠加那层暗的原始版 → 指标上升（旧基线备份为
    `基线_改CZI通道前_20260923.json`）。
  · 2026-09-23 改 CZI 染料配色：FITC-T1 / EGFP-T2 是同一路绿色，老写法因为
    "绿色已用过"把第二路涂成红色，合并后用户看到红图；改回绿色后灰度图变亮，
    拉普拉斯方差跟着变大（rgb→L 的加权不同）。oib 两项 0.0% 未动，说明
    锐化管线本身没碰。旧基线备份为 `基线_改CZI配色前_20260923.json`。
  · 2026-09-23 换按钮 / 开关样式：中间那行"组内裁剪框位置一致"的开关
    从 46×24 缩到 40×20，中栏底部的固定高度少了 4px，**正方形的画布因此
    从 475² 变成 479²** —— 图是按画布尺寸重新采样的，指标跟着变 1~3%
    （画布尺寸就记在基线 JSON 里，可核对）。旧基线备份为
    `基线_换按钮开关前_20260923.json`。
  · 2026-09-26 黑白点默认改成"数据实际最小/最大"、配色换成纯色、叠加改加法：
    这三条都直接改**渲染口径**，拉普拉斯方差必然大动（旧的分位拉伸把图像拉得
    更"跳"，新默认更接近原始）。oib-full 4424 → 1662、czi-full 1244 → 11。
    锐化管线（preview_for_view / sharpen_display）本身没动 —— 想核对就把
    4 个 case 的图导出来肉眼比一下（`output\_自检\叠加方式_三版对比.png`）。
    旧基线备份为 `基线_改黑白点前_20260926.json`。
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import numpy as np
import cv2
from PIL import Image as PILImage
from PySide6.QtCore import QElapsedTimer
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtWidgets import QApplication

import paths
from core import loader
from ui.main_window import MainWindow
from _samples import P  # noqa: E402

CASES = [
    ("oib", P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")),
    ("czi", P(r"E:\ImageCapture\789\Snap-14700-Airyscan Processing-04.czi")),
]
BASE_DIR = os.path.join(paths.OUTPUT_DIR, "_自检", "清晰度基线")
WIN_W, WIN_H = 1460, 940
TOL = 0.05
# 裁剪视野固定成这个值再测。
# 为什么必须固定：裁剪视野是用户随时会改的参数（存在 config/settings.json 里），
# 而"裁剪结果"视图显示的是一块被放大/缩小的区域 —— 换个裁剪尺寸，清晰度指标
# 自然就变了。基线是在 300 µm 下录的，所以这里钉死 300，测的才是"管线有没有变糊"。
CROP_UM = 300.0


def lap_var(pil) -> float:
    g = np.asarray(pil.convert("L")).astype(np.float64)
    if g.size == 0:
        return 0.0
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def grab_image_only(app, win):
    """只要画布上的图像，不要裁剪框和标尺叠加层。"""
    cv = win.canvas
    keep_box, keep_ov = cv._show_box, cv._overlay
    cv._show_box = False
    cv._overlay = None
    for _ in range(3):
        app.processEvents()
    shot = cv.grab().toImage()
    cv._show_box, cv._overlay = keep_box, keep_ov
    a = shot.convertToFormat(QImage.Format_RGB888)
    w, h, stride = a.width(), a.height(), a.bytesPerLine()
    raw = np.frombuffer(a.constBits(), np.uint8)
    buf = raw[: stride * h].reshape(h, stride)[:, : w * 3].reshape(h, w, 3)
    return PILImage.fromarray(buf[:, :, ::-1].copy())


def measure():
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    out = {}
    for tag, path in CASES:
        if not os.path.exists(path):
            print("跳过（文件不在）:", path)
            continue
        win = MainWindow()
        win.resize(WIN_W, WIN_H)
        win.settings.crop_w = win.settings.crop_h = CROP_UM     # 见 CROP_UM 的注释
        it = loader.probe(path)
        win.items = [it]
        win._regroup()
        win.refresh_groups()
        win.refresh_strip()
        win.show()
        c = QElapsedTimer()
        c.start()
        while c.elapsed() < 900:
            app.processEvents()
        # 离屏环境屏幕很小，程序会自己把窗口缩小；这里强制开到固定尺寸，
        # 保证"画布像素尺寸"每次一致，指标才有可比性。
        for _ in range(6):
            win.resize(WIN_W, WIN_H)
            app.processEvents()
        if win.canvas.width() < 400:
            print("  警告：画布只有 %d px，偏小（离屏屏幕限制）" % win.canvas.width())
        for mode in ("full", "crop"):
            win.set_view_mode(mode)
            c.start()
            while c.elapsed() < 400:
                app.processEvents()
            pil = grab_image_only(app, win)
            key = tag + "-" + mode
            out[key] = dict(lap_var=round(lap_var(pil), 2),
                            canvas=[pil.width, pil.height],
                            src=os.path.basename(path), crop_um=CROP_UM)
            os.makedirs(BASE_DIR, exist_ok=True)
            pil.save(os.path.join(BASE_DIR, key + ".png"))
            print("  %-10s 画布 %dx%d  清晰度 %.2f"
                  % (key, pil.width, pil.height, out[key]["lap_var"]))
        win.close()
    if out:
        out["_crop_um"] = CROP_UM        # 基线是在这个裁剪尺寸下录的（自描述）
    return out


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "check").lower()
    os.makedirs(BASE_DIR, exist_ok=True)
    path = os.path.join(BASE_DIR, "基线.json")
    got = measure()
    if mode == "save":
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(got, fh, ensure_ascii=False, indent=2)
        print("\n基线已保存:", path)
        return 0
    if not os.path.exists(path):
        print("\n没有基线文件，先跑 save:", path)
        return 1
    with open(path, encoding="utf-8") as fh:
        base = json.load(fh)
    base_crop = base.pop("_crop_um", CROP_UM)
    if abs(base_crop - CROP_UM) > 1e-6:
        print("\n注意：基线是 %.0f µm 裁剪下录的，本次用 %.0f µm（不可比！）"
              % (base_crop, CROP_UM))
    print("\n与基线对比（裁剪视野钉在 %g µm，允许偏差 %.0f%%）:" % (CROP_UM, TOL * 100))
    bad = 0
    for k, v in base.items():
        if k not in got:
            print("  %-10s 本次没测到（文件缺失?）" % k)
            continue
        a, b = v["lap_var"], got[k]["lap_var"]
        dev = abs(b - a) / max(1e-6, a)
        ok = dev < TOL
        bad += 0 if ok else 1
        print("  %-10s 基线 %.2f -> 现在 %.2f  偏差 %.1f%%  %s"
              % (k, a, b, 100 * dev, "OK" if ok else "**超了**"))
    print("\n结论:", "清晰度冻结未破坏" if bad == 0 else "有 %d 项超差，需查因" % bad)
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
