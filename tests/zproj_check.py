# -*- coding: utf-8 -*-
"""Z 投影 + 正交视图自检（规格书 P1-5 的 7 条验收）。

  1 MIP 全部层：结构比单层完整、XY 尺寸不变
  2 投影后按裁剪框导出：物理视野与不投影时一致
  3 「当前层 ± 3」→ 拖 Z 滑条，投影范围跟着变
  4 正交视图比例：Z 0.35 µm、XY 0.1 µm/px → 20 层 × 0.35 : 1000 px × 0.1 = 7 : 100
  5 Z 步进 = 0 → 面板写"未按比例"，不崩
  6 导出投影图 TIFF：SizeZ == 1、DimensionOrder == XYCZT、不写 PhysicalSizeZ
  7 投影不拖慢界面：20 层的 MIP 一次 ≤ 100 ms
"""
import os
import re
import shutil
import sys
import time

import numpy as np
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                          # noqa: E402
from PySide6.QtWidgets import QApplication                              # noqa: E402

import paths                                                            # noqa: E402
from core import loader, render, zproj                                  # noqa: E402
from core.model import Group, Settings                                  # noqa: E402
from ui.main_window import MainWindow                                   # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "Z投影")


def make_zstack(path, z=20, c=2, y=160, x=1000, umpp=0.1, zstep=0.35):
    """造一个 Z 栈 OME-TIFF：每层都有同样的结构点，中间层额外加一块亮点。

    这样 MIP 一定比任何单层"更完整"（亮点只在中间层出现）。
    """
    rng = np.random.default_rng(7)
    base = np.zeros((y, x), np.uint16)
    for _ in range(40):
        cy, cx = rng.integers(20, y - 20), rng.integers(20, x - 20)
        base[cy - 1:cy + 2, cx - 1:cx + 2] = 3000
    a = np.zeros((z, c, y, x), dtype=np.uint16)
    for i in range(z):
        layer = base.copy()
        if i in (5, 10, 15):              # 每块亮点只出现在某一层 → MIP 才"更完整"
            yy, xx = 30 + i * 6, 200 + i * 40
            layer[yy:yy + 20, xx:xx + 50] = 4000
        a[i, 0] = np.clip(layer.astype(np.int32) + rng.integers(0, 40, (y, x)), 0, 4095)
        a[i, 1] = (base // 2)
    meta = {"axes": "ZCYX",       # a 的形状就是 (Z, C, Y, X)，声明要和数组一致
            "PhysicalSizeX": umpp, "PhysicalSizeXUnit": "µm",
            "PhysicalSizeY": umpp, "PhysicalSizeYUnit": "µm",
            "PhysicalSizeZ": zstep, "PhysicalSizeZUnit": "µm",
            "Channel": {"Name": ["CH1", "CH2"]}}
    tifffile.imwrite(path, a, ome=True, photometric="minisblack",
                     compression="zlib", metadata=meta)
    return a


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    res = {}

    p = os.path.join(OUT, "zstack20x2.tif")
    make_zstack(p)
    it = loader.probe(p)
    st = loader.load_stack(it)
    print("源图：%s  Z=%d 通道=%d  %d×%d  %.2f µm/px  Z 步进 %.2f µm"
          % (os.path.basename(p), it.z_count, len(it.channels), it.width, it.height,
             it.umpp, it.z_step_um))

    # ---------- 1 MIP 全部层 ----------
    it.proj_mode, it.proj_range_mode = "max", "all"
    vit = render.view_item(it, 0)
    n_mip = int((vit._cache[0][0] > 2000).sum())
    n_single = int((st[it.z_count // 2][0] > 2000).sum())
    ok1 = (vit._cache.shape[2:] == (it.height, it.width) and n_mip > n_single)
    print("[1] 亮像素：单层（中间层）%d → MIP %d；尺寸 %s（原图 %d×%d）"
          % (n_single, n_mip, vit._cache.shape[2:], it.height, it.width))
    res["MIP更完整"] = bool(ok1)

    # ---------- 2 投影后裁剪：物理视野不变 ----------
    g = Group(gid="g1", title="t")
    g.box = dict(x=10.0, y=10.0, w=30.0, h=30.0)
    st_e = Settings()
    st_e.out_subdir = "flat"
    st_e.bar_enabled = False
    st_e.exp_raw_single = False
    rect1 = render.crop_rect(it, g.box, st_e)
    it.proj_mode = "none"
    rect0 = render.crop_rect(it, g.box, st_e)
    ok2 = (rect1 == rect0 and abs(rect1[2] * it.umpp - 30.0) < 0.6)
    print("[2] 裁剪框 %s → 视野 %.1f µm（投影前后一致：%s）"
          % (rect1[:4], rect1[2] * it.umpp, rect1 == rect0))
    res["视野不变"] = bool(ok2)

    # ---------- 3 「当前层 ± 3」跟着 Z 滑条 ----------
    win = MainWindow()
    win.resize(1460, 940)
    win.items = [it]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(it.path)
    app.processEvents()
    win.cb_proj.setCurrentIndex(1)                       # MIP
    win.cb_proj_range.setCurrentIndex(1)                 # 当前层 ± n
    win.sp_proj_n.setValue(3)
    app.processEvents()
    r_first = zproj.proj_range(it)
    win.z_slider.setValue(11)
    app.processEvents()
    r_mid = zproj.proj_range(it)
    ok3 = (r_first == (0, 3) and r_mid == (7, 13) and win._planes_key is not None)
    print("[3] 当前层 ± 3：Z=1 → %s；拖到 Z=11 → %s；提示「%s」"
          % (r_first, r_mid, win.lbl_proj_hint.text()))
    res["范围跟滑条"] = bool(ok3)

    # ---------- 7 速度 ----------
    it.proj_mode, it.proj_range_mode = "max", "all"
    t0 = time.time()
    for _ in range(3):
        zproj.project_frame(st, it, t=0, mode="max")
    dt = (time.time() - t0) / 3.0
    ok7 = dt < 0.1
    print("[7] MIP 一次 %.0f ms（%d 层 %d×%d，要求 < 100 ms）"
          % (dt * 1000, it.z_count, it.height, it.width))
    res["投影够快"] = bool(ok7)

    # ---------- 6 导出投影图 ----------
    st_e.exp_proj = True
    st_e.exp_raw_single = True
    files, _row = render.export_item(it, g, st_e, frame=0, out_root=OUT)
    names = [os.path.basename(f) for f in files]
    mipraw = [f for f in files if "_MIP" in f and f.endswith(".tif") and "_raw" in f]
    ok6, detail = False, "没写出投影图"
    for f in mipraw:
        with tifffile.TiffFile(f) as tf:
            ome = tf.ome_metadata or ""
            sizez = (re.search(r'SizeZ="(\d+)"', ome) or [None, "?"])[1]
            do = (re.search(r'DimensionOrder="(\w+)"', ome) or [None, "?"])[1]
            psz = "PhysicalSizeZ" in ome
        ok6 = (sizez == "1" and do == "XYCZT" and not psz)
        detail = "%s：SizeZ=%s DimensionOrder=%s PhysicalSizeZ=%s" % (
            os.path.basename(f), sizez, do, "有" if psz else "无")
        break
    print("[6] 投影图导出：%s" % detail)
    print("        文件：%s" % names)
    res["投影导出"] = bool(ok6 and any("_MIP" in n for n in names))

    # ---------- 4/5 正交视图比例 ----------
    win.items = [it]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(it.path)
    app.processEvents()
    from ui.ortho import OrthoWindow
    w = OrthoWindow(win)
    w.sync_channels()
    w.line = (0, 80, 999, 80)                            # 一条 1000 px 的横线
    rgb, _meta = w.build_rgb()
    depth = (it.z_count - 1) * it.z_step_um
    length = 1000 * it.umpp
    phys = depth / length                                # 7 / 100 = 0.07
    got = rgb.shape[0] / float(rgb.shape[1])
    ok4 = abs(got - phys) < 0.02
    print("[4] 正交比例：%d 层 × %.2f = %.1f µm 深；1000 px × %.2f = %.0f µm 长 → "
          "物理 %.3f，画面 %.3f（%s）"
          % (it.z_count, it.z_step_um, depth, it.umpp, length, phys, got,
             "一致" if ok4 else "不对"))
    res["正交比例"] = bool(ok4)

    it.z_step_um = 0.0                                   # 清空 Z 步进
    w.line = (0, 80, 999, 80)
    w.refresh()
    note = w.canvas.aspect_note
    ok5 = ("未按比例" in note) and w.canvas._rgb is not None
    print("[5] Z 步进清空：画面提示「%s」，没崩" % note)
    res["未知步进不崩"] = bool(ok5)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    print("输出目录:", OUT)
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
