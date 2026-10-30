# -*- coding: utf-8 -*-
"""原始位深导出自检（规格书 P0-2 的 12 条验收）。

用真实 12bit 图（3164p.oib）跑，不造句：
  1 dtype=uint16 且最大值 = 4095（**不是** 65535），PhysicalSizeX = µm/px
  2 彩图与原始导出构图一致（同一 rect 的宽高）
  3 多通道栈 shape=(C,H,W) dtype=uint16
  4 大改显示区间 → 原始导出的像素**完全不变**（证明没烘焙）
  5 未标定 PNG 也能导，报告写"未标定"
  6 导出放大 4× → 彩图 4 倍，原始导出仍是原尺寸
  7 OME 单位 µm、tifffile / PIL 都打得开
  8 链后导出 + 内嵌链前数据 → 还原后与"关掉处理链导出的文件"逐像素相同
  9 私有 tag 不影响通用可读性（页数不变）
 10 处理链为空 → 一个私有 tag 都不写，文件大小与不加 tag 时一致
 11 未标定：报告里出现"未标定：已导出像素，未写 PhysicalSize"
 12 （清晰度冻结由 sharpness_baseline.py 单独把关）
"""
import os
import re
import shutil
import sys

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import paths                                                          # noqa: E402
from core import loader, raw as raw_mod, render                       # noqa: E402
from core.model import Group, ProcessStep, Settings                   # noqa: E402
from _samples import P  # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "原始导出")
SRC = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")
BOX = dict(x=0.0, y=0.0, w=20.0, h=20.0)


def st_for(**kw):
    st = Settings()
    st.out_subdir = "flat"
    st.out_suffix = "_crop"
    st.bar_enabled = False
    st.exp_raw_single = False
    st.exp_raw_stack = False
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def read_tiff(path):
    import tifffile
    with tifffile.TiffFile(path) as tf:
        arr = tf.asarray()
        ome = tf.ome_metadata or ""
        pages = len(tf.pages)
        shape = tf.pages[0].shape
        dtype = tf.pages[0].dtype
    return arr, ome, pages, shape, dtype


def ome_field(ome, key):
    m = re.search(r'%s="([^"]*)"' % key, ome or "")
    return m.group(1) if m else ""


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    res = {}

    item = loader.probe(SRC)
    group = Group(gid="g1", title="原始导出")
    group.box = dict(BOX)
    stack = loader.load_stack(item)
    rect = render.crop_rect(item, group.box, st_for())
    print("源图：%s  %d×%d  %.4f µm/px  %d 通道  dtype=%s  裁剪 %dx%d px"
          % (item.name, item.width, item.height, item.umpp, len(item.channels),
             stack.dtype, rect[2], rect[3]))

    # ---------- 1 位深不拉伸 + OME 物理尺寸 ----------
    d1 = os.path.join(OUT, "1_单通道")
    st = st_for(exp_raw_single=True, exp_raw_ome=True)
    files, notes, dt = render.export_raw(item, st, stack, 0, rect, d1, "s")
    arrs = []
    for f in files:
        a, ome, pages, shape, dtype = read_tiff(f)
        arrs.append((os.path.basename(f), a, ome))
    biggest = max(int(a.max()) for _n, a, _o in arrs)
    psx = ome_field(arrs[0][2], "PhysicalSizeX")
    ok1 = (str(dt) == "uint16" and biggest == 4095 and abs(float(psx) - item.umpp) < 1e-6)
    print("[1] 单通道原始：%d 个文件，dtype=%s，最大像素 %d（应 4095，不是 65535），"
          "PhysicalSizeX=%s" % (len(files), dt, biggest, psx))
    res["位深不拉伸"] = ok1

    # ---------- 2 与彩图构图一致 ----------
    d2 = os.path.join(OUT, "2_构图")
    st2 = st_for(exp_raw_single=True)
    st2.exp_merge = True
    cw, crow = render.export_item(item, group, st2, frame=0, out_root=d2)
    raws = [p for p in cw if "_raw16" in os.path.basename(p)]
    color = [p for p in cw if p not in raws and p.endswith(".tif")]
    ca = read_tiff(color[0])[0]
    ra = read_tiff(raws[0])[0]
    ok2 = (ca.shape[:2] == ra.shape[:2])
    print("[2] 彩图 %s vs 原始 %s（构图一致：%s）"
          % (ca.shape, ra.shape, ok2))
    res["构图一致"] = ok2

    # ---------- 3 多通道栈 ----------
    d3 = os.path.join(OUT, "3_栈")
    files3, _n, _d = render.export_raw(item, st_for(exp_raw_stack=True), stack, 0, rect, d3, "s")
    a3, ome3, _p, _sh, dt3 = read_tiff(files3[0])
    ok3 = (a3.shape == (len(item.channels), rect[3], rect[2]) and str(dt3) == "uint16"
           and ome_field(ome3, "SizeC") == str(len(item.channels))
           and ome_field(ome3, "DimensionOrder") == "XYCZT")
    print("[3] 多通道栈 %s %s（应 (%d,%d,%d)）DimensionOrder=%s"
          % (a3.shape, dt3, len(item.channels), rect[3], rect[2],
             ome_field(ome3, "DimensionOrder")))
    res["多通道栈"] = ok3

    # ---------- 4 改显示区间，原始导出像素不变 ----------
    for ch in item.channels:
        ch.black, ch.white = 0.0, 4095.0
    d4a = os.path.join(OUT, "4a_区间宽")
    fa, _n, _d = render.export_raw(item, st_for(exp_raw_single=True), stack, 0, rect, d4a, "s")
    for ch in item.channels:
        ch.black, ch.white = 1500.0, 1800.0        # 大幅调窄
    d4b = os.path.join(OUT, "4b_区间窄")
    fb, _n, _d = render.export_raw(item, st_for(exp_raw_single=True), stack, 0, rect, d4b, "s")
    same = True
    for pa, pb in zip(sorted(fa), sorted(fb)):
        same = same and np.array_equal(read_tiff(pa)[0], read_tiff(pb)[0])
    print("[4] 显示区间 0~4095 vs 1500~1800 两次原始导出：像素%s"
          % ("完全相同" if same else "**不一样**"))
    res["不烘焙区间"] = same
    for ch in item.channels:
        ch.black, ch.white = 0.0, 4095.0

    # ---------- 5/11 未标定的 PNG ----------
    d5 = os.path.join(OUT, "5_未标定")
    os.makedirs(d5, exist_ok=True)
    from PIL import Image
    png = os.path.join(d5, "未标定.png")
    rng = np.random.default_rng(3)
    Image.fromarray(rng.integers(0, 255, (400, 400, 3), dtype=np.uint8)).save(png)
    it5 = loader.probe(png)
    g5 = Group(gid="g5", title="未标定组")
    g5.box = dict(x=0.0, y=0.0, w=100.0, h=100.0)
    files5, row5 = render.export_item(it5, g5, st_for(exp_raw_single=True),
                                      frame=0, out_root=d5)
    note5 = row5.get("note") or ""
    ok5 = bool(files5) and "未标定" in note5
    print("[5] 未标定 PNG：umpp=%.1f，导出 %d 个文件，报告「%s」"
          % (it5.umpp, len(files5), note5))
    t5 = [f for f in files5 if f.endswith(".tif")]
    if t5:
        ome5 = read_tiff(t5[0])[1]
        print("        OME 里有 PhysicalSizeX 吗：%s（未标定应为无）"
              % ("有" if ome_field(ome5, "PhysicalSizeX") else "无"))
    res["未标定能导"] = ok5

    # ---------- 6 放大 4× 时原始导出仍是原尺寸 ----------
    d6 = os.path.join(OUT, "6_放大")
    st6 = st_for(exp_raw_single=True)
    st6.exp_merge = True
    st6.export_zoom = 4
    f6, row6 = render.export_item(item, group, st6, frame=0, out_root=d6)
    raw6 = [p for p in f6 if "_raw16" in os.path.basename(p)]
    color6 = [p for p in f6 if p not in raw6 and p.endswith(".tif")]
    c6 = read_tiff(color6[0])[3]
    r6 = read_tiff(raw6[0])[3]
    ok6 = (c6[0] == rect[3] * 4 and r6[0] == rect[3] and r6[1] == rect[2])
    print("[6] 放大 4×：彩图 %s（应 %d），原始 %s（应 %d）"
          % (c6, rect[3] * 4, r6, rect[3]))
    res["原始不放大"] = ok6

    # ---------- 7 OME 单位 / 可读性 ----------
    ome7 = read_tiff(files[0])[1]
    unit_ok = (ome_field(ome7, "PhysicalSizeXUnit") in ("µm", "um")
               and ome_field(ome7, "DimensionOrder") == "XYCZT")
    try:
        from PIL import Image as _I
        with _I.open(files[0]) as im:
            im.load()
        pil_ok = True
    except Exception:                            # noqa: BLE001
        pil_ok = False
    print("[7] OME：单位=%s，DimensionOrder=%s；PIL 打开=%s"
          % (ome_field(ome7, "PhysicalSizeXUnit"), ome_field(ome7, "DimensionOrder"),
             "OK" if pil_ok else "失败"))
    res["OME元数据"] = bool(unit_ok and pil_ok)

    # ---------- 8 链后导出 + 精确还原（N2 + N3）----------
    d8 = os.path.join(OUT, "8_链后")
    true_stack = stack.copy()
    fake_chain = (stack.astype(np.uint32) + 100).astype(stack.dtype)   # 假装链改过像素
    item.process = [ProcessStep(kind="bg", params={"p": 5.0})]
    old_raw_stack = loader.raw_stack
    loader.raw_stack = lambda it: true_stack              # 链前 = 真原始
    try:
        f8, n8, _d = render.export_raw(item, st_for(exp_raw_single=True, exp_raw_embed=True),
                                       fake_chain, 0, rect, d8, "s")
    finally:
        loader.raw_stack = old_raw_stack
    d8b = os.path.join(OUT, "8b_无链")
    item.process = []                                     # 链为空 = 关掉处理链
    f8b, _n, _d = render.export_raw(item, st_for(exp_raw_single=True), true_stack, 0, rect,
                                    d8b, "s")
    chain_page = read_tiff(f8[0])[0]
    plain_page = read_tiff(f8b[0])[0]
    back = raw_mod.restore_planes(f8[0])
    # 内嵌的是"整个裁剪区域的链前像素"（所有通道），跟单通道主页面比要取对应的那一层
    truth = render.crop_planes(true_stack[0], rect)
    page_diff = not np.array_equal(chain_page, plain_page)
    back_same = (back is not None and np.array_equal(back[0], truth)
                 and np.array_equal(np.squeeze(plain_page), truth[0]))
    ok8 = back_same and page_diff
    print("[8] 链后主页面 vs 无链主页面：%s；内嵌还原后 vs 无链：%s"
          % ("不同（链确实改过像素）" if page_diff else "**相同，链没生效**",
             "逐像素相同" if back_same else "**不一致**"))
    res["精确还原"] = ok8

    # ---------- 9 私有 tag 不影响页数 ----------
    p8, p8b = read_tiff(f8[0])[2], read_tiff(f8b[0])[2]
    print("[9] 带 tag 的文件页数=%d，不带 tag 的页数=%d（都不能被当成额外的图像页）"
          % (p8, p8b))
    res["可读性"] = (p8 == p8b == 1)

    # ---------- 10 无链一个 tag 都不写、体积不变 ----------
    plain = os.path.join(OUT, "10_对照.tif")
    stem_ref = os.path.splitext(os.path.basename(f8b[0]))[0]
    ome_ref = render.build_ome(item, stem_ref, item.umpp, [item.channels[0]], axes="YX")
    raw_mod.save_raw_tiff(plain, plain_page, umpp=item.umpp, ome=ome_ref, proc=None)
    ids_plain = raw_mod.tag_ids(f8b[0])
    sz_with = os.path.getsize(f8b[0])
    sz_ref = os.path.getsize(plain)
    ok10 = (raw_mod.TAG_PROC not in ids_plain and raw_mod.TAG_BLOB0 not in ids_plain
            and abs(sz_with - sz_ref) <= max(1, sz_ref * 0.01))
    print("[10] 无链导出的私有 tag：%s；文件 %d B vs 不加 tag 的 %d B"
          % (sorted(t for t in ids_plain if t >= 65000) or "无", sz_with, sz_ref))
    res["无链不增量"] = ok10

    # ---------- 12 界面接线：开关 + 放大置灰 + 清单 ----------
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1460, 940)
    win.items = [loader.probe(SRC)]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(win.items[0].path)
    win.chk_raw.setChecked(True)
    win.chk_raw_stack.setChecked(False)
    app.processEvents()
    st_ui = win._sync_settings()
    zoom_grey = not win.cb_zoom.isEnabled()
    manifest = win.manifest.text()
    print("[12] 界面：exp_raw_single=%s，放大下拉置灰=%s，清单「%s」"
          % (st_ui.exp_raw_single, zoom_grey, manifest))
    res["界面接线"] = bool(st_ui.exp_raw_single and zoom_grey and "原始位深" in manifest)
    win.item = None

    # ---------- 11 重新导入 → 认得出处理记录 → 点「还原」回到链前 ----------
    it11 = loader.probe(f8[0])
    calib_before = it11.calib
    tagged = ("带处理记录" in (calib_before or "")) and bool(getattr(it11, "has_proc", False))
    embed_ok = bool(getattr(it11, "embed_ok", False))
    win.items = [it11]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(it11.path)
    app.processEvents()
    win.restore_item(it11)
    app.processEvents()
    got = getattr(it11, "_cache", None)
    back_ok = (got is not None and got.ndim == 4 and np.array_equal(got[0], truth)
               and not it11.process and "带处理记录" not in (it11.calib or ""))
    print("[11] 重新导入：calib=「%s」，可还原=%s；点还原后像素 %s、处理链已清空=%s"
          % (calib_before, embed_ok,
             "与链前逐像素相同" if (got is not None and np.array_equal(got[0], truth))
             else "**不一致**", not it11.process))
    res["导入认tag"] = bool(tagged and embed_ok and back_ok)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    print("输出目录:", OUT)
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
