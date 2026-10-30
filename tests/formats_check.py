# -*- coding: utf-8 -*-
"""蔡司 CZI 与徕卡 LIF 走一遍完整流程：读图 → 标定 → 裁剪 → 画标尺 → 导出。"""
import os
import sys

from PIL import Image

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import paths                                          # noqa: E402
from core import loader, render                       # noqa: E402
from core.model import Group, Settings                # noqa: E402
from _samples import P  # noqa: E402

FILES = [P(r"E:\ImageCapture\789\Snap-14700-Airyscan Processing-04.czi"),
         P(r"E:\ImageCapture\789\0.5h17.3B.lif")]
OUT = os.path.join(paths.OUTPUT_DIR, "_格式自检")


def main():
    os.makedirs(OUT, exist_ok=True)
    shots = []
    for path in FILES:
        if not os.path.exists(path):
            print("缺文件:", path)
            continue
        item = loader.probe(path)
        stack = loader.load_stack(item)
        st = Settings.load()
        st.out_subdir = "flat"
        st.out_suffix = "_fmt"
        st.crop_w = st.crop_h = 30.0
        st.export_zoom = 1
        st.bar_extra_png = False
        # 这次验证用"全自动"标尺参数，跟个人设置无关
        st.bar_thickness = 0
        st.bar_font_size = 0
        st.bar_margin = 0
        st.bar_text = True
        st.bar_show_unit = True
        st.bar_ticks = "ends6"
        st.bar_color = "auto"
        group = Group(gid="g", title="格式自检", sync=True)
        field = item.field_um()
        group.box = dict(x=(field - 30) / 2, y=(field - 30) / 2, w=30.0, h=30.0)
        files, row = render.export_item(item, group, st, frame=0, out_root=OUT)
        im = Image.open(files[0]).convert("RGB")
        print("%-46s %s %s  标尺 %s" % (item.name[:46], im.size, row["box"], row["bar"]))
        w, h = im.size
        k = max(1, int(320 / max(w, h)))
        shots.append(im.resize((w * k, h * k), Image.LANCZOS))
    if shots:
        width = sum(s.width for s in shots) + 10 * len(shots)
        height = max(s.height for s in shots)
        board = Image.new("RGB", (width, height), (10, 10, 14))
        x = 0
        for s in shots:
            board.paste(s, (x, 0))
            x += s.width + 10
        p = os.path.join(OUT, "CZI_LIF_裁剪切片对比.png")
        board.save(p)
        print("对比图:", p, board.size)


if __name__ == "__main__":
    main()
