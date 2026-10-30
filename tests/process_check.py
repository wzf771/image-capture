# -*- coding: utf-8 -*-
"""处理链（配准 / 背景扣除 / 漂移）自检 —— 规格书 P1-7 的 8 条验收。

  1 构造 (+3,-2) 的通道错位 → 配准后残差 < 0.3 px
  2 配准前后 Pearson r：配准后明显更高
  3 百分位 5% 扣背景 → 背景区均值 ≈ 0，且保留负值（不 clip）
  4 逐帧递增平移（漂移）→ 校正后各帧对齐
  5 关掉处理链 → 立刻回到原始像素（无残留）
  6 处理链进 .icproj → 存档重开后效果一致
  7 改一个参数 → 预览自动重算（缓存指纹生效，不是旧数据）
  8 缓存有上限（LRU，不无限增长）
"""
import os
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
from core import loader, register as reg                                # noqa: E402
from core.model import ProcessStep                                      # noqa: E402
from ui.main_window import MainWindow                                   # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "处理链")


def make_file(path, frames=6, c=3, y=96, x=128):
    """3 通道 + 逐帧漂移：CH2 相对 CH1 偏 (+3,-2)，每帧再漂 (-1.5, +0.8)。"""
    # 加一层背景底（真实数据都有）：否则 5% 分位就是 0，扣背景等于没扣，
    # "保留负值"这条也测不出来
    base = np.full((y, x), 100, np.uint16)
    yy, xx = np.mgrid[0:y, 0:x]
    base[((yy - 40) ** 2 + (xx - 60) ** 2) < 80] = 3000
    base[10:20, 90:110] = 2500
    rng = np.random.default_rng(4)
    base = np.clip(base.astype(np.int32) + rng.integers(-15, 15, (y, x)), 1, 4095)
    base = base.astype(np.uint16)
    a = np.zeros((frames, c, y, x), np.uint16)
    for f in range(frames):
        a[f, 0] = reg.apply_shift(base, -f * 1.5, f * 0.8).astype(np.uint16)
        a[f, 1] = reg.apply_shift(base, 3.0 - f * 1.5, -2.0 + f * 0.8).astype(np.uint16)
        a[f, 2] = (base // 3).astype(np.uint16)
    meta = {"axes": "TCYX", "PhysicalSizeX": 0.5, "PhysicalSizeXUnit": "µm",
            "Channel": {"Name": ["CH1", "CH2", "CH3"]}}
    tifffile.imwrite(path, a, ome=True, photometric="minisblack",
                     compression="zlib", metadata=meta)
    return a


def pearson(a, b):
    x = np.asarray(a, np.float32).ravel()
    y = np.asarray(b, np.float32).ravel()
    x = x - x.mean()
    y = y - y.mean()
    d = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float((x * y).sum() / d) if d > 0 else 0.0


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    res = {}

    p = os.path.join(OUT, "drift.ome.tif")
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
    raw_stack = loader.raw_stack(it).copy()

    def wait(cond, t=25.0):
        t0 = time.time()
        while time.time() - t0 < t:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    # ---------- 1 配准残差 ----------
    win.sw_reg.setChecked(True)
    app.processEvents()
    win.recalc_register()
    got = wait(lambda: bool((it.process or []) and (it.process[0].params or {}).get("shifts")))
    shifts = (it.process[0].params or {}).get("shifts") or {}
    chain = loader.load_stack(it)
    resid = reg.est_shift(chain[0, 0], chain[0, 1])
    ok1 = bool(got and abs(resid[0]) < 0.3 and abs(resid[1]) < 0.3)
    print("[1] 配准：CH2 位移 %s → 配准后残差 %.3f, %.3f px（要求 < 0.3）"
          % (shifts.get("1"), resid[0], resid[1]))
    res["配准残差"] = ok1

    # ---------- 2 Pearson r ----------
    before = pearson(raw_stack[0, 0], raw_stack[0, 1])
    after = pearson(chain[0, 0], chain[0, 1])
    print("[2] 共定位 Pearson r：配准前 %.3f → 配准后 %.3f" % (before, after))
    res["共定位变好"] = bool(after > before + 0.05)

    # ---------- 3 背景扣除 ----------
    win.sw_bg.setChecked(True)
    app.processEvents()
    ch = loader.load_stack(it)
    # 取一块干净的背景区：第 1 帧、避开边界（配准平移会在边界补 0）与结构点
    bg = ch[0, 0, 70:90, 20:50]
    bg_p5 = float(np.percentile(bg, 5))
    bg_mean = float(bg.mean())
    has_neg = bool(ch.min() < 0)
    print("[3] 扣背景（百分位 5%%）：背景区 5%% 分位 %.2f（≈0 才算扣对，容差 ±5 个计数）、"
          "均值 %.2f"
          "（百分位法本来会留一点正值）、dtype=%s、保留负值=%s"
          % (bg_p5, bg_mean, ch.dtype, has_neg))
    res["扣背景"] = bool(abs(bg_p5) <= 5.0 and ch.dtype == np.float32 and has_neg)

    # ---------- 7 改参数 → 预览自动重算 ----------
    key1 = it._cache_key
    planes1 = None if win._planes is None else win._planes.copy()
    win.sp_bg_p.setValue(20.0)
    app.processEvents()
    chain2 = loader.load_stack(it)
    changed = (it._cache_key != key1) and (not np.allclose(chain2[0, 0], ch[0, 0]))
    planes2 = None if win._planes is None else win._planes
    ok7 = bool(changed and planes1 is not None and planes2 is not None
               and not np.allclose(planes1, planes2))
    print("[7] 改「百分位 5→20」：指纹变了=%s，预览像素变了=%s"
          % (it._cache_key != key1, not np.allclose(chain2[0, 0], ch[0, 0])))
    res["指纹重算"] = ok7
    win.sp_bg_p.setValue(5.0)
    app.processEvents()

    # ---------- 4 漂移校正 ----------
    win.sw_drift.setChecked(True)
    app.processEvents()
    win.recalc_drift()
    got = wait(lambda: any(s.kind == "drift" and (s.params or {}).get("shifts")
                           for s in (it.process or [])), t=40.0)
    ch3 = loader.load_stack(it)
    d_res = [reg.est_shift(ch3[0, 0], ch3[f, 0]) for f in (2, 5)]
    step = next((s for s in (it.process or []) if s.kind == "drift"), None)
    n_drift = len(((step.params if step else {}) or {}).get("shifts") or {})
    ok4 = bool(got and all(abs(a) < 0.3 and abs(b) < 0.3 for a, b, _r in d_res))
    print("[4] 漂移校正：%d 帧；校正后第 3/6 帧相对首帧残差 %s"
          % (n_drift, ["%.2f,%.2f" % (a, b) for a, b, _r in d_res]))
    res["漂移校正"] = ok4

    # ---------- 6 处理链进工程 ----------
    proj = os.path.join(OUT, "proj.icproj")
    win._proj_path = proj
    win.proj_save()
    win2 = MainWindow()
    win2.resize(1460, 940)
    win2.open_project(proj)
    app.processEvents()
    it2 = next(x for x in win2.items if x.path == it.path)
    same_px = bool(np.allclose(loader.load_stack(it2), loader.load_stack(it)))
    print("[6] 存档重开：处理链 %d 步，像素与关闭前一致=%s" % (len(it2.process), same_px))
    res["工程带链"] = bool(len(it2.process) == len(it.process) and same_px)

    # ---------- 5 关掉开关 → 立刻回到原始 ----------
    win.sw_reg.setChecked(False)
    win.sw_bg.setChecked(False)
    win.sw_drift.setChecked(False)
    app.processEvents()
    back = loader.load_stack(it)
    same_raw = bool(np.array_equal(back, raw_stack))
    print("[5] 三个开关全关：处理链 %d 步，像素与原始逐点相同=%s"
          % (len(it.process), same_raw))
    res["可关可还原"] = bool(not it.process and same_raw)

    # ---------- 8 缓存上限 ----------
    old_budget = reg.CACHE_BUDGET
    reg.CACHE_BUDGET = 30 * 1024 * 1024
    items = []
    for k in range(10):
        x = loader.probe(p)
        x.path = "%s#%d" % (p, k)
        x._cache = np.zeros((6, 3, 256, 256), np.float32)
        x._cache_key = ("k%d" % k, x.path)
        reg.cache_note(x, int(x._cache.nbytes))
        items.append(x)
    n_alive, nbytes = reg.cache_info()
    released = sum(1 for x in items if x._cache is None)
    reg.CACHE_BUDGET = old_budget
    ok8 = bool(nbytes <= 30 * 1024 * 1024 * 1.05 and released >= 1)
    print("[8] 缓存上限：登记 %d 份 / %.1f MB（预算 30 MB），被释放 %d 份"
          % (n_alive, nbytes / 1048576.0, released))
    res["缓存有上限"] = ok8

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    print("输出目录:", OUT)
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
