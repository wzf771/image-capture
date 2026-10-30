# -*- coding: utf-8 -*-
"""Z / T 分离自检（规格书 P0-3 的 6 条验收）。

  1 Z 栈图：Z 层数与**通道数都正确**（老代码会把 Z 当帧、把通道数搞错）
  2 真实 OIB 回归：50 帧时间序列仍是 50 个时间点、2 个通道（不是 2 点 50 通道）
  3 OME-TIFF 按 DimensionOrder 重排：C=3 / Z=21 都对
  4 无元数据的多页 TIFF：默认时间序列 → 手动声明 Z 栈 → 60 层
  5 双滑条联动：Z=5、T=10 → 展平索引 = 9*z_count + 4，导出文件名能核对
  6 老 settings.json（frames_mode="all"）升级后：T=全部、Z=当前，导出数量不变
"""
import json
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
from PySide6.QtWidgets import QApplication, QMessageBox                 # noqa: E402

import paths                                                            # noqa: E402
from core import loader, render                                         # noqa: E402
from core.model import Group, Settings                                  # noqa: E402
from ui.main_window import MainWindow                                   # noqa: E402
from _samples import P  # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "ZT分离")
FRAP = P(r"E:\XY\相分离部\6.3\6.3\frap\3-6\FRAPR1.oib")
OIB3 = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")


def make_ome_stack(path, c, z, y=32, x=40, order="XYZCT"):
    """造一个 OME-TIFF：按 order 的**存储顺序**写 C/Z，元数据声明 XYZCT。"""
    rng = np.random.default_rng(11)
    a = rng.integers(0, 4095, (c, z, y, x), dtype=np.uint16)
    meta = {"axes": "CZYX", "DimensionOrder": order,
            "PhysicalSizeX": 0.5, "PhysicalSizeXUnit": "µm",
            "PhysicalSizeZ": 0.35, "PhysicalSizeZUnit": "µm",
            "Channel": {"Name": ["CH%d" % (i + 1) for i in range(c)]}}
    tifffile.imwrite(path, a, ome=True, photometric="minisblack",
                     compression="zlib", metadata=meta)
    return a


def make_multipage(path, n=60, y=24, x=24):
    rng = np.random.default_rng(3)
    a = rng.integers(0, 255, (n, y, x), dtype=np.uint8)
    tifffile.imwrite(path, a, photometric="minisblack")      # 不带任何维度元数据
    return a


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
    res = {}

    # ---------- 1/3 Z 栈（OME-TIFF，按 DimensionOrder 重排）----------
    p1 = os.path.join(OUT, "zstack21x3.ome.tif")
    want = make_ome_stack(p1, c=3, z=21)
    it1 = loader.probe(p1)
    st1 = loader.load_stack(it1)
    ok1 = (it1.t_count == 1 and it1.z_count == 21 and it1.frames == 21
           and len(it1.channels) >= 1 and st1.shape == (21, 3, 32, 40)
           and abs(it1.z_step_um - 0.35) < 1e-6      # PhysicalSizeZ 要读进来
           and abs(it1.z_range_um - 7.0) < 1e-6)
    print("[1/3] OME-TIFF (C=3,Z=21,存储顺序 CZYX,DimensionOrder=XYZCT)："
          "t=%d z=%d frames=%d 通道表 %d 个 读出来 %s 步进 %.3g µm 深度 %.3g µm"
          % (it1.t_count, it1.z_count, it1.frames, len(it1.channels), st1.shape,
             it1.z_step_um, it1.z_range_um))
    res["Z栈(OME)"] = ok1

    # ---------- 2 真实 OIB 时间序列回归 ----------
    msg2 = ""
    if os.path.exists(FRAP):
        it2 = loader.probe(FRAP)
        st2 = loader.load_stack(it2)
        ok2 = (it2.t_count == 50 and it2.z_count == 1 and st2.shape[:2] == (50, 2)
               and len(it2.channels) == 2)
        msg2 = ("t=%d z=%d 通道=%d 读出 %s（老代码会读成 (2,50) → 50 个通道）"
                % (it2.t_count, it2.z_count, len(it2.channels), st2.shape))
    else:
        ok2 = True
        msg2 = "跳过（文件不在）"
    print("[2] 真实 OIB 时间序列 %s：%s" % (os.path.basename(FRAP), msg2))
    res["OIB时间序列"] = ok2

    # ---------- 4 多页 TIFF：默认时间 → 手动声明 Z 栈 ----------
    p4 = os.path.join(OUT, "multipage60.tif")
    make_multipage(p4, 60)
    it4 = loader.probe(p4)
    st4 = loader.load_stack(it4)
    default_t = (it4.t_count == 60 and it4.z_count == 1)
    it4.declare_frames("z")
    is_z = (it4.z_count == 60 and it4.t_count == 1 and it4.z_declared_manual)
    print("[4] 60 页无元数据 TIFF：默认 t=%d z=%d → 声明 Z 栈后 t=%d z=%d（%s）"
          % (60, 1, it4.t_count, it4.z_count, "OK" if (default_t and is_z) else "不过"))
    res["手动声明"] = bool(default_t and is_z and st4.shape[0] == 60)

    # ---------- 5 双滑条联动 + 导出文件名 ----------
    p5 = os.path.join(OUT, "tz.ome.tif")                     # T=12 × C=3 × Z=21 的真文件
    a5 = np.random.default_rng(21).integers(0, 4095, (12, 3, 21, 24, 32), dtype=np.uint16)
    tifffile.imwrite(p5, a5, ome=True, photometric="minisblack", compression="zlib",
                     metadata={"axes": "TCZYX"})
    it5 = loader.probe(p5)
    win = MainWindow()
    win.resize(1460, 940)
    win.items = [it5]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(it5.path)
    app.processEvents()
    win.z_slider.setValue(5)                                 # 第 5 层
    win.frame_slider.setValue(10)                            # 第 10 点
    app.processEvents()
    expect = it5.flat_index(9, 4)
    lbl_z, lbl_t = win.lbl_z.text(), win.lbl_frame.text()
    print("[5] 拖到 Z=5 / T=10：cur_z=%d cur_t=%d frame=%d（应 %d）" % (
        win.cur_z, win.cur_t, win.frame, expect))
    print("        Z 行「%s」 T 行「%s」" % (lbl_z, lbl_t))
    ok5 = (win.cur_z == 4 and win.cur_t == 9 and win.frame == expect
           and win.z_row.isVisible() or not win.z_row.isHidden())
    # 导出文件名核对
    g = Group(gid="g1", title="t")
    g.box = dict(x=0.0, y=0.0, w=10.0, h=10.0)
    st = Settings()
    st.out_subdir = "flat"
    st.bar_enabled = False
    st.exp_raw_single = False
    files, _row = render.export_item(it5, g, st, frame=expect, out_root=OUT)
    names = [os.path.basename(f) for f in files]
    name_ok = any("_z005_t010" in n for n in names)
    print("        导出文件名：%s（应含 _z005_t010）" % names)
    res["双滑条联动"] = bool(ok5 and name_ok)

    # ---------- 6 老 settings.json 升级 ----------
    old = os.path.join(OUT, "old_settings.json")
    with open(old, "w", encoding="utf-8") as fh:
        json.dump({"frames_mode": "all", "frame_pick": "", "crop_w": 300.0}, fh)
    st_old = Settings.load(old)
    mig = (st_old.frames_mode == "all" and getattr(st_old, "z_mode", "") == "current")
    # 界面照老参数摆好（T=全部、Z=当前）→ 导出数量应与升级前一致
    win.cb_frames.setCurrentIndex(["current", "all", "pick"].index(st_old.frames_mode))
    win.cb_zmode.setCurrentIndex(["current", "all", "pick"].index(st_old.z_mode))
    it6 = loader.probe(FRAP) if os.path.exists(FRAP) else it5
    win.items = [it6]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(it6.path)
    app.processEvents()
    n = len(win._frames_for(it6))
    ok6 = bool(mig and n == it6.frames and (it6.z_count or 1) == 1)
    print("[6] 老 settings（frames_mode=all）升级：T=%s、Z=%s（迁移对=%s）；"
          "T=全部 + Z=当前 → 导出 %d 帧（图里有 %d 帧）"
          % (st_old.frames_mode, st_old.z_mode, "是" if mig else "否", n, it6.frames))
    res["老参数兼容"] = bool(ok6)

    # ---------- 界面：单帧图不显示双滑条 ----------
    one = loader.probe(OIB3)
    win.items = [one]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(one.path)
    app.processEvents()
    hidden = win.frames_card.isHidden()
    print("[7] 单帧图：Z/T 两行隐藏=%s" % hidden)
    res["单帧不显示"] = bool(hidden)

    # ---------- 8 声明胶囊只在"元数据说不清"时出现 ----------
    probe_cases = []
    if os.path.exists(FRAP):
        probe_cases.append(("OIB 时间序列（元数据说了 T）", loader.probe(FRAP), False))
    probe_cases.append(("OME Z 栈（元数据说了 Z）", loader.probe(p1), False))
    probe_cases.append(("60 页无元数据 TIFF", loader.probe(p4), True))
    bad = []
    for name, it, want_show in probe_cases:
        show = bool(it.frames > 1 and not it.z_meta_declared and not it.t_meta_declared)
        mark = "显示" if show else "隐藏"
        ok = (show == want_show)
        bad.append(0 if ok else 1)
        print("[8] %-28s → %s（应%s）" % (name, mark, "显示" if want_show else "隐藏"))
    res["声明胶囊判据"] = not any(bad)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    print("输出目录:", OUT)
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
