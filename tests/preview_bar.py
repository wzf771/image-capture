# -*- coding: utf-8 -*-
"""生成标尺样式对比图，方便肉眼确认字号/粗细/字体。"""
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
OIB = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")


def main():
    os.makedirs(OUT, exist_ok=True)
    item = loader.probe(OIB)
    st = Settings()
    st.crop_w = st.crop_h = 150.0
    g = Group(gid="g1", title="t")
    f = item.field_um()
    g.box = dict(x=(f - 150) / 2, y=(f - 150) / 2, w=150.0, h=150.0)
    crops = []
    for font in ("Arial", "Times New Roman", "微软雅黑"):
        st.bar_font = font
        st.out_suffix = "_" + font.split()[0]
        files, row = render.export_item(item, g, st, frame=0, out_root=OUT)
        im = Image.open(files[0]).convert("RGB")
        w, h = im.size
        crops.append(im.crop((w - 150, h - 70, w, h)).resize((600, 280), Image.NEAREST))
        print("%-16s %s  %s" % (font, os.path.basename(files[0]), row["bar"]))
    board = Image.new("RGB", (600, 280 * len(crops)), (0, 0, 0))
    for i, im in enumerate(crops):
        board.paste(im, (0, i * 280))
    path = os.path.join(OUT, "标尺局部_三种字体.png")
    board.save(path)
    print("对比图:", path)


if __name__ == "__main__":
    main()
