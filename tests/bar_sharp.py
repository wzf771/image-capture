# -*- coding: utf-8 -*-
"""检查"标尺高清"这件事：糊的图放大后标尺依然锐利，并出透明标尺 PNG。"""
import os
import sys

from PIL import Image

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import paths                                          # noqa: E402
from core import bar as bar_mod                       # noqa: E402
from core import loader, render                       # noqa: E402
from core.model import Group, Settings                # noqa: E402
from _samples import P  # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检")
OIB = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")


def main():
    os.makedirs(OUT, exist_ok=True)
    item = loader.probe(OIB)
    g = Group(gid="g1", title="t")
    f = item.field_um()
    g.box = dict(x=(f - 30) / 2, y=(f - 30) / 2, w=30.0, h=30.0)
    shots = []
    written = {}
    for zoom in (1, 2, 4):
        st = Settings()
        st.crop_w = st.crop_h = 30.0
        st.bar_font = "Arial"
        st.bar_font_size = 0
        st.export_zoom = zoom
        st.bar_extra_png = (zoom == 4)
        st.out_suffix = "_zoom%d" % zoom
        files, row = render.export_item(item, g, st, frame=0, out_root=OUT)
        written[zoom] = files[0]
        im = Image.open(files[0]).convert("RGB")
        print("放大 %d× → %-22s %s  标尺 %s" % (zoom, os.path.basename(files[0]), im.size, row["bar"]))
        for extra in files[1:]:
            print("        另有", os.path.basename(extra))
        w, h = im.size
        k = max(1, int(240 / max(w, h)))
        shots.append(im.crop((max(0, w - int(w * 0.75)), max(0, h - int(h * 0.45)), w, h))
                      .resize((int(w * 0.75) * k, int(h * 0.45) * k), Image.NEAREST))
    board = Image.new("RGB", (sum(s.width for s in shots) + 20, max(s.height for s in shots)),
                      (10, 10, 14))
    x = 0
    for s in shots:
        board.paste(s, (x, 0))
        x += s.width + 10
    path = os.path.join(OUT, "标尺清晰度对比.png")
    board.save(path)
    print("对比图:", path, board.size)
    # 再做一张"放大看边角"的图，方便直接看标尺锐不锐
    big = []
    for zoom in (1, 2, 4):
        im = Image.open(written[zoom]).convert("RGB")
        w, h = im.size
        c = im.crop((0, int(h * 0.55), w, h))
        k = max(1, int(430 / max(c.size)))
        big.append(c.resize((c.width * k, c.height * k), Image.NEAREST))
    w = max(b.width for b in big)
    h = sum(b.height for b in big) + 16
    board2 = Image.new("RGB", (w, h), (10, 10, 14))
    y = 0
    for b2 in big:
        board2.paste(b2, (0, y))
        y += b2.height + 8
    p2 = os.path.join(OUT, "标尺放大看.png")
    board2.save(p2)
    print("放大看:", p2, board2.size)


if __name__ == "__main__":
    main()
