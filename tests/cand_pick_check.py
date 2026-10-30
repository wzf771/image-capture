# -*- coding: utf-8 -*-
"""多候选标尺交互自检（规格书 5.4.5 + 验收第 6 条）。

造一张有两条标尺的图（5 µm/100 px + 50 µm/300 px，两条算出的 µm/px 差 233%）：
  · 识别后 item 上要标成"待确认"（bar.ambiguous = True）
  · 缩略图右上角出现橙点
  · 画布上除最高分那条，其它候选也要画出来（琥珀色）
  · 标定卡片里列出候选，点第 2 条 → ¥m/px 按第 2 条生效、橙点消失
  · 只有一条候选的图（上一个测试那张）不能被打扰
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                            # noqa: E402
from PySide6.QtWidgets import QApplication                                # noqa: E402

import paths                                                              # noqa: E402
from core import bar as bar_mod, loader                                   # noqa: E402
from ui.main_window import MainWindow                                     # noqa: E402
from ui import worker                                                     # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "多候选")
W, H = 900, 900


def make_png(path):
    a = np.full((H, W), 20, np.uint8)
    img = Image.fromarray(a).convert("RGB")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 30)
    except Exception:                                                     # noqa: BLE001
        f = ImageFont.load_default(size=30)
    for text, x0, x1, y in (("5 µm", 380, 480, 300), ("50 µm", 300, 600, 640)):
        d.rectangle([x0, y, x1, y + 6], fill=(240, 240, 240))
        tw = d.textbbox((0, 0), text, font=f)[2]
        d.text((x0 + (x1 - x0 - tw) / 2.0, y - 46), text, font=f, fill=(240, 240, 240))
    img.save(path)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))

    png = make_png(os.path.join(OUT, "两条标尺的图.png"))
    it = loader.probe(png)
    worker.job_calibrate([it])
    det = it.detect or {}
    cands = det.get("candidates") or []
    print("[1] 识别到 %d 条候选：" % len(cands))
    for i, c in enumerate(cands):
        print("    %d) %s 长 %.0f px → %.4f µm/px（置信 %.2f）"
              % (i + 1, c.get("text"), (c.get("bar") or {}).get("length", 0), c["umpp"],
                 c.get("score", 0)))
    ok1 = len(cands) >= 2 and bar_mod.ambiguous(det)
    print("    待确认（bar.ambiguous）=%s  → %s" % (bar_mod.ambiguous(det), ok1))

    win = MainWindow()
    win.resize(1460, 940)
    win.items = [it]
    win._regroup()
    win.refresh_groups()
    win.select_item(it.path)                 # 走一遍真实选中流程（会刷新标定卡片）
    win.refresh_strip()
    win.set_view_mode("full")
    app.processEvents()

    tb = win._thumb_buttons.get(it.path)
    # 注意：离屏窗口没 show()，isVisible() 恒为 False，要看控件自己的 hidden 标记
    print("[2] 缩略图橙点：%s" % ("有" if tb and not tb.dot.isHidden() else "没有"))
    ok2 = bool(tb and not tb.dot.isHidden())
    print("[3] 画布上的候选：%d 条（琥珀色）"
          % len((win.canvas._detect or {}).get("alts") or []))
    ok3 = len((win.canvas._detect or {}).get("alts") or []) >= 1
    print("[4] 候选面板：%s，%d 个候选项"
          % ("显示" if not win.cand_box.isHidden() else "隐藏",
             max(0, win.cand_lay.count() - 1)))
    ok4 = (not win.cand_box.isHidden()) and win.cand_lay.count() >= 3
    win.grab().save(os.path.join(OUT, "1_多候选界面.png"))

    # 点第 2 条候选（面板顺序 = candidates 顺序）
    b2 = win.cand_lay.itemAt(2).widget()
    exp_umpp = float(cands[1]["umpp"])
    print("[5] 点选候选项：「%s」" % b2.text())
    b2.click()
    app.processEvents()
    tb = win._thumb_buttons.get(it.path)     # refresh_strip 会重建缩略图，要重新取
    print("    选后 umpp=%.4f（该候选 %.4f），calib=%s，橙点=%s，面板=%s"
          % (it.umpp, exp_umpp, it.calib,
             "还在" if not tb.dot.isHidden() else "已消失",
             "还在" if not win.cand_box.isHidden() else "已收起"))
    ok5 = (abs(it.umpp - exp_umpp) < 1e-9 and tb.dot.isHidden()
           and win.cand_box.isHidden())
    win.grab().save(os.path.join(OUT, "2_选完候选.png"))

    print("[6] 只有一条候选的图不该被打扰")
    one = loader.probe(os.path.join(paths.OUTPUT_DIR, "_自检", "识别可视化", "带标尺的图.png"))
    if os.path.exists(one.path):
        worker.job_calibrate([one])
        print("    bar.ambiguous = %s（应为 False）" % bar_mod.ambiguous(one.detect))
        ok6 = not bar_mod.ambiguous(one.detect)
    else:
        print("    跳过：单候选样图不在（先跑 detect_overlay_check.py）")
        ok6 = True

    print()
    print("结论:", "全部通过" if all((ok1, ok2, ok3, ok4, ok5, ok6)) else "有未通过项",
          "(1识别 %s / 2橙点 %s / 3候选线 %s / 4面板 %s / 5点选 %s / 6不打扰 %s)"
          % (ok1, ok2, ok3, ok4, ok5, ok6))
    return 0 if all((ok1, ok2, ok3, ok4, ok5, ok6)) else 1


if __name__ == "__main__":
    sys.exit(main())
