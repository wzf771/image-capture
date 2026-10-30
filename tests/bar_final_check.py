# -*- coding: utf-8 -*-
"""用当前保存的参数，导出 1× 和 4× 各一张，看看标尺是不是够锐。"""
import os
import sys

from PIL import Image

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import paths                                          # noqa: E402
from core import loader, render                       # noqa: E402
from core.model import Group, Settings                # noqa: E402
from _samples import P  # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检")


def main():
    os.makedirs(OUT, exist_ok=True)
    st = Settings.load()
    st.out_subdir = "flat"
    item = loader.probe(P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib"))
    f = item.field_um()
    # 裁剪视野是用户随时会改的参数，可能比这张图的视野还大；这里按图夹一下，
    # 否则 too_small="pad" 会把 1024 的图补成 8000+，导出一张 3 GB 的图。
    st.crop_w = min(float(st.crop_w), f)
    st.crop_h = min(float(st.crop_h), f)
    g = Group(gid="g1", title="t", sync=True)
    g.box = dict(x=(f - st.crop_w) / 2, y=(f - st.crop_h) / 2, w=st.crop_w, h=st.crop_h)
    shots = []
    for zoom in (1, 4):
        st.export_zoom = zoom
        st.bar_extra_png = (zoom == 4)
        st.out_suffix = "_final%d" % zoom
        files, row = render.export_item(item, g, st, frame=0, out_root=OUT)
        im = Image.open(files[0]).convert("RGB")
        print("放大 %d× → %s %s  标尺 %s" % (zoom, os.path.basename(files[0]), im.size, row["bar"]))
        w, h = im.size
        k = max(1, int(300 / max(w, h)))
        shots.append(im.resize((w * k, h * k), Image.NEAREST))
    w = max(s.width for s in shots)
    h = sum(s.height for s in shots) + 10
    board = Image.new("RGB", (w, h), (10, 10, 14))
    y = 0
    for s in shots:
        board.paste(s, (0, y))
        y += s.height + 10
    p = os.path.join(OUT, "标尺_按你的参数.png")
    board.save(p)
    print("对比图:", p, board.size)


if __name__ == "__main__":
    main()
