# -*- coding: utf-8 -*-
"""ROI 与测量自检 —— 规格书 P1-6 的验收（可脚本化的部分）。

  1 矩形 ROI 的 Mean 与手工（numpy）一致（Fiji 同口径）→ 证明没读错数据源
  2 大改显示区间 → Mean 不变（统计没经过显示区间/配色）
  3 背景 ROI → IntDen_bg_corr 等于手工算的值
  4 线剖面：横轴 µm、长度与 ROI 一致、横轴单调
  5 共定位：故意错开 5 px → 配准后 Pearson r 明显更高；未配准带提示
  6 粒子计数：已知 37 个点的合成图 → 计数 ±1
  7 导出 CSV：utf-8-sig、注释行含 µm/px 与处理链
  8 换帧 → ROI 位置不变
  9 ROI 进 .icproj → 重开工程后完整恢复
"""
import os
import shutil
import sys

import numpy as np
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                          # noqa: E402
from PySide6.QtWidgets import QApplication                              # noqa: E402

import paths                                                            # noqa: E402
from core import analysis, loader                                       # noqa: E402
from core import register as reg                                        # noqa: E402
from core import roi as roi_mod                                         # noqa: E402
from core.analysis import rows_to_csv                                   # noqa: E402
from core.model import ProcessStep                                      # noqa: E402
from ui.main_window import MainWindow                                   # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "定量")


def make_file(path, frames=3, c=2, y=160, x=200):
    """双通道 + 3 帧：CH1 有 37 个亮点；CH2 是 CH1 平移 5 px（测共定位用）。"""
    rng = np.random.default_rng(5)
    plane = np.full((y, x), 120, np.uint16)
    spots = []
    while len(spots) < 37:
        cy, cx = int(rng.integers(12, y - 12)), int(rng.integers(12, x - 12))
        if all((cy - b[0]) ** 2 + (cx - b[1]) ** 2 > 144 for b in spots):
            spots.append((cy, cx))
            plane[cy - 2:cy + 3, cx - 2:cx + 3] = 3000
    a = np.zeros((frames, c, y, x), np.uint16)
    for f in range(frames):
        a[f, 0] = reg.apply_shift(plane, f * 2.0, 0.0).astype(np.uint16)
        a[f, 1] = reg.apply_shift(plane, 5.0, 0.0).astype(np.uint16)
    tifffile.imwrite(path, a, ome=True, photometric="minisblack", compression="zlib",
                     metadata={"axes": "TCYX", "PhysicalSizeX": 0.25,
                               "PhysicalSizeXUnit": "µm",
                               "Channel": {"Name": ["CH1", "CH2"]}})
    return a


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    res = {}

    p = os.path.join(OUT, "roi.ome.tif")
    make_file(p)
    it = loader.probe(p)
    win = MainWindow()
    win.resize(1460, 940)
    win.items = [it]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(it.path)
    app.processEvents()
    stack = loader.load_stack(it)
    print("源图：%s  %d×%d  %.2f µm/px  %d 帧 %d 通道"
          % (it.name, it.width, it.height, it.umpp, it.frames, len(it.channels)))

    # ---------- 1 矩形 ROI 的 Mean ----------
    r = roi_mod.Roi(kind="rect", points=[[0.10, 0.10], [0.40, 0.40]], label="信号")
    it.rois = [r]
    rows, head = win.roi_rows_data()
    box = roi_mod.roi_px(r, it.width, it.height)
    sub = np.asarray(stack[0, 0], np.float32)[box[1]:box[3], box[0]:box[2]]
    print("[1] 矩形 ROI %s：程序 Mean=%.4f / 手工 %.4f，Area=%d（手工 %d）"
          % (box, rows[0]["Mean"], sub.mean(), rows[0]["Area_px"], sub.size))
    res["Mean一致"] = bool(abs(rows[0]["Mean"] - round(float(sub.mean()), 4)) < 1e-3
                           and rows[0]["Area_px"] == sub.size)

    # ---------- 2 改显示区间，Mean 不变 ----------
    for c in it.channels:
        c.black, c.white = 2500.0, 2600.0
    win.refresh_preview()
    app.processEvents()
    rows2, _h = win.roi_rows_data()
    print("[2] 显示区间改成 2500~2600 后：Mean=%.4f（原来 %.4f）"
          % (rows2[0]["Mean"], rows[0]["Mean"]))
    res["不吃显示区间"] = bool(abs(rows2[0]["Mean"] - rows[0]["Mean"]) < 1e-9)
    for c in it.channels:
        c.black, c.white = 0.0, 4095.0

    # ---------- 3 背景 ROI ----------
    bg = roi_mod.Roi(kind="rect", points=[[0.02, 0.80], [0.10, 0.95]], label="背景",
                     is_bg=True)
    it.rois = [r, bg]
    rows3, _h = win.roi_rows_data()
    bm = analysis.bg_means(loader.load_stack(it), it, frame=0)
    hand = (float(sub.mean()) - bm[0]) * sub.size
    print("[3] 背景均值 %.3f；IntDen_bg_corr=%.3f（手工 %.3f）"
          % (bm[0], rows3[0]["IntDen_bg_corr"], hand))
    res["背景校正"] = bool(abs(rows3[0]["IntDen_bg_corr"] - round(hand, 3)) < 0.01)

    # ---------- 4 线剖面 ----------
    line = roi_mod.Roi(kind="line", points=[[0.05, 0.5], [0.75, 0.5]], label="剖面")
    it.rois = [r, bg, line]
    prof, _h = win.roi_profile_data()
    n_expect = int(round(0.7 * it.width)) + 1
    mono = all(b >= a for a, b in zip(prof["um"], prof["um"][1:]))
    print("[4] 线剖面：%d 点、%.2f µm（应 %d 点 / %.2f µm），横轴单调=%s"
          % (prof["n"], prof["length_um"], n_expect, n_expect * it.umpp, mono))
    res["线剖面"] = bool(prof["n"] == n_expect and mono
                         and abs(prof["um"][-1] - (n_expect - 1) * it.umpp) < 1e-6)

    # ---------- 5 共定位 ----------
    co_bad, _h = win.roi_coloc_data()
    it.process = [ProcessStep("register", {"ref_ch": 0, "shifts": {"1": [-5.0, 0.0]}})]
    it._cache_key = None
    co_good, _h2 = win.roi_coloc_data()
    print("[5] Pearson r：未配准 %.3f（提示：%s）→ 配准后 %.3f"
          % (co_bad["Pearson_r"], "有" if co_bad.get("note") else "无",
             co_good["Pearson_r"]))
    res["共定位"] = bool(co_good["Pearson_r"] > co_bad["Pearson_r"] + 0.1
                         and not co_bad["registered"] and co_good["registered"])
    it.process = []
    it._cache_key = None

    # ---------- 6 粒子计数（整帧：真值 37；再验 ROI 内计数）----------
    it.rois = []
    pc, _h3 = win.roi_particles_data()
    it.rois = [r]
    pc_roi, _h4 = win.roi_particles_data()
    print("[6] 粒子计数：整帧 %d 个（真值 37）、ROI 内 %d 个；阈值 %.1f"
          % (pc["count"], pc_roi["count"], pc.get("thr", 0)))
    res["粒子计数"] = bool(abs(pc["count"] - 37) <= 1 and pc_roi["count"] < pc["count"])

    # ---------- 8 换帧 → ROI 不动 ----------
    before = [q[:] for q in r.points]
    win.frame_slider.setValue(2)
    app.processEvents()
    after = [q[:] for q in r.points]
    print("[8] 切到第 2 帧后 ROI 坐标 %s（原来 %s）"
          % ([[round(v, 4) for v in q] for q in after],
             [[round(v, 4) for v in q] for q in before]))
    res["换帧不动"] = bool(before == after)

    # ---------- 7 CSV 规范 ----------
    it.rois = [r, bg, line]                  # 三个 ROI 都留着（下面工程恢复要核对）
    rows7, head7 = win.roi_rows_data()
    csv_path = os.path.join(OUT, "roi.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(rows_to_csv(rows7, head7))
    raw = open(csv_path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    has_meta = ("µm/px" in text) and ("处理链" in text)
    print("[7] CSV：BOM=%s、含 µm/px 与处理链=%s" % (bom, has_meta))
    res["CSV规范"] = bool(bom and has_meta)

    # ---------- 9 ROI 进工程 ----------
    proj = os.path.join(OUT, "roi.icproj")
    win._proj_path = proj
    win.proj_save()
    win2 = MainWindow()
    win2.resize(1460, 940)
    win2.open_project(proj)
    app.processEvents()
    it2 = next(x for x in win2.items if x.path == it.path)
    same = (len(it2.rois) == 3
            and [q for q in it2.rois[0].points] == [q for q in r.points]
            and any(x.is_bg for x in it2.rois))
    print("[9] 工程恢复 %d 个 ROI（含背景=%s）"
          % (len(it2.rois), any(x.is_bg for x in it2.rois)))
    res["ROI进工程"] = bool(same)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    print("输出目录:", OUT)
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
