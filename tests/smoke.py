# -*- coding: utf-8 -*-
"""自检：拿真实文件走一遍 读图 → 标定 → 合成 → 裁剪 → 画标尺 → 导出。"""
from __future__ import annotations

import os
import sys
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP_DIR, "app"))

import numpy as np                                     # noqa: E402
from PIL import Image                                  # noqa: E402

import paths                                           # noqa: E402
from core import bar as bar_mod                        # noqa: E402
from core import loader, render                        # noqa: E402
from core.model import Group, Settings, nice_bar_length  # noqa: E402
from _samples import P  # noqa: E402

DATA = P(r"E:\XY\亚细胞定位部\4gegene\2")
OUT = os.path.join(paths.OUTPUT_DIR, "_自检")


def main():
    paths.ensure_dirs()
    os.makedirs(OUT, exist_ok=True)
    ok = True

    # 1) 原生读 OIB
    oib = os.path.join(DATA, "3164p.oib")
    t0 = time.time()
    item = loader.probe(oib)
    print("[1] 读 OIB 元数据 %.2fs：%s | %.3f µm/px | %d×%d | %d 帧 | 来源=%s"
          % (time.time() - t0, item.name, item.umpp, item.width, item.height,
             item.frames, item.calib))
    if abs(item.umpp - 0.621) > 0.001:
        print("    !! µm/px 不对"); ok = False
    for ch in item.channels:
        print("    通道 %d: %s %s → %s" % (ch.index, ch.name, ch.light, ch.role))

    # 2) 读导出图并靠标尺识别标定
    png = None
    for cand in (P(r"E:\XY\3164p.bmp.frames\3164p_T001.bmp"),
                 P(r"E:\XY\ER1.bmp.frames\ER1_T001.bmp")):
        if os.path.exists(cand):
            png = cand
            break
    if png is None:
        for folder, _dirs, files in os.walk(DATA):
            for f in files:
                if f.lower().endswith((".png", ".bmp", ".jpg")):
                    png = os.path.join(folder, f)
                    break
            if png:
                break
    if png:
        t0 = time.time()
        it2 = loader.probe(png)
        rgb, factor = render.quick_rgb(it2)
        res = bar_mod.detect_umpp(rgb)
        dt = time.time() - t0
        if res.get("ok"):
            umpp2 = res["umpp"] / factor
            print("[2] 标尺识别 %s %.2fs：读到 %s，标尺 %s px → %.4f µm/px"
                  % (it2.name, dt, res.get("text"), round(res["bar"]["length"], 1), umpp2))
            if abs(umpp2 - 0.621) > 0.02:
                print("    !! 与 0.621 差得有点多，需要人工确认")
        else:
            print("[2] 标尺识别未成功：", res.get("why"))
    else:
        print("[2] 没找到用于测试的 PNG 导出图")

    # 3) 裁剪 + 画标尺（两种字体各来一张）
    stack = loader.load_stack(item)
    st = Settings()
    st.crop_w = st.crop_h = 30.0
    st.bar_enabled = True
    st.bar_font_size = 0                      # 0 = 按图宽自动
    g = Group(gid="g1", title="自检组")
    field = item.field_um()
    g.box = dict(x=(field - 30) / 2, y=(field - 30) / 2, w=30.0, h=30.0)
    for font in ("Arial", "Times New Roman"):
        st.bar_font = font
        st.out_suffix = "_crop_%s" % font.split()[0]
        files, r = render.export_item(item, g, st, frame=0, out_root=OUT)
        print("[3] 字体 %-16s → %s" % (font, os.path.basename(files[0]) if files else "失败"))
        if not files:
            ok = False
            continue
        im = Image.open(files[0])
        print("     输出 %s %s 尺寸=%s dpi=%s" % (im.format, im.mode, im.size, im.info.get("dpi")))
        # 把成品拼一张大图方便肉眼检查
        big = im.resize((im.width * 6, im.height * 6), Image.NEAREST)
        big.save(os.path.join(OUT, "自检_%s_放大.png" % font.split()[0]))

    # 4) 单通道导出
    st.out_suffix = "_crop"
    st.exp_merge = True
    st.exp_ch = [True, False, True]
    files, _r = render.export_item(item, g, st, frame=0, out_root=OUT)
    print("[4] 合并 + 指定单通道 →", [os.path.basename(f) for f in files])

    # 5) 时间序列
    frap = P(r"E:\XY\相分离部\6.3\6.3\frap\3-6\FRAPR1.oib")
    if os.path.exists(frap):
        it3 = loader.probe(frap)
        stk = loader.load_stack(it3)
        print("[5] 时间序列 %s：%d 帧 %d 通道 %.3f µm/px"
              % (it3.name, stk.shape[0], stk.shape[1], it3.umpp))
        g3 = Group(gid="g3", title="自检FRAP")
        f3 = it3.field_um()
        g3.box = dict(x=(f3 - 30) / 2, y=(f3 - 30) / 2, w=30.0, h=30.0)
        st.exp_ch = [False, False, False]
        files, _r = render.export_item(it3, g3, st, frame=12, out_root=OUT)
        print("     第 13 帧导出 →", [os.path.basename(f) for f in files])

    print("\n自检输出目录：", OUT)
    print("结果：", "通过" if ok else "有项目需要人工确认")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
