# -*- coding: utf-8 -*-
"""从用户给的原图生成软件图标（assets/icon.ico / icon.png）。

用法：
    python make_icon.py                       # 源图默认读 assets/icon_source.png
    python make_icon.py D:\\某张图.png        # 也可以临时指定一张

为什么不是直接把原图缩一缩（2026-09-23 用户给了正式图标）：
原稿是 1830×1821 的"圆角深蓝外框 + 显微镜 + 底部一排文件图标"，四周留白很大
（内容只占宽度的 52%）。直接缩到 32px 时显微镜只剩十几像素，任务栏上糊成一团。
所以这里：① 先切掉原稿那圈外框；② 按"内容外扩 8%"裁紧；③ 补成正方形；
④ 用原稿里取样的颜色把圆角外框按新比例重画回去 —— 风格不变，主体大一倍多。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import paths                                          # noqa: E402

SRC_DEFAULT = os.path.join(paths.ASSETS_DIR, "icon_source.png")
SIZES = [256, 128, 64, 48, 40, 32, 24, 20, 16]       # ICO 里各尺寸各存一张
MASTER = 1024                                         # 另存一张大图给界面/文档用

FRAME_CROP = 0.022        # 先切掉原稿最外圈（蓝色描边）的比例
PAD = 0.08                # 内容四周留白（占内容长边）
RADIUS = 0.20             # 圆角半径（占成品边长）：原稿约 0.17，略圆一点更像应用图标
LINE = 0.022              # 外框线宽（占成品边长）


def _inner_content(im):
    """返回 (去掉外框的图, 内容 bbox, 背景色, 外框色)，比例算的，换图也能跑。"""
    w, h = im.size
    cut = int(min(w, h) * FRAME_CROP)
    inner = im.crop((cut, cut, w - cut, h - cut)).convert("RGB")
    a = np.asarray(inner).astype(np.int16)
    bg = np.median(a.reshape(-1, 3), axis=0)
    mask = np.abs(a - bg).sum(axis=2) > 70
    ys, xs = np.where(mask)
    corner = im.convert("RGB").getpixel((2, 2))       # 原稿外框颜色
    if len(xs) == 0 or xs.max() - xs.min() < 8:
        x0, y0, x1, y1 = 0, 0, inner.width, inner.height
    else:
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    return inner, (x0, y0, x1 + 1, y1 + 1), tuple(int(v) for v in bg), corner


def build(src):
    im = Image.open(src).convert("RGBA")
    inner, bbox, bg, frame_col = _inner_content(im)
    cut = int(max(8, min(im.size) * PAD))
    x0, y0, x1, y1 = bbox
    content = inner.crop((max(0, x0 - cut), max(0, y0 - cut),
                          min(inner.width, x1 + cut), min(inner.height, y1 + cut)))
    cw, ch = content.size
    side = max(cw, ch)
    tile = Image.new("RGBA", (side, side), bg + (255,))
    tile.paste(content, ((side - cw) // 2, (side - ch) // 2))
    # 圆角：4 倍超采样再缩回来，边缘才干净
    k = 4
    mask = Image.new("L", (side * k, side * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, side * k - 1, side * k - 1],
                                           radius=int(side * k * RADIUS), fill=255)
    mask = mask.resize((side, side), Image.LANCZOS)
    tile.putalpha(mask)
    # 把原稿那圈外框按新比例画回去
    glass = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    lw = max(2, int(side * LINE))
    ImageDraw.Draw(glass).rounded_rectangle(
        [lw // 2, lw // 2, side - 1 - lw // 2, side - 1 - lw // 2],
        radius=int(side * RADIUS), outline=frame_col + (255,), width=lw)
    return Image.alpha_composite(tile, glass).resize((MASTER, MASTER), Image.LANCZOS)


def main():
    paths.ensure_dirs()
    src = sys.argv[1] if len(sys.argv) > 1 else SRC_DEFAULT
    if not os.path.exists(src):
        raise SystemExit("找不到源图：%s\n把原图另存为 assets\\icon_source.png 再跑。" % src)
    master = build(src)
    png = os.path.join(paths.ASSETS_DIR, "icon.png")
    master.save(png)
    ico = os.path.join(paths.ASSETS_DIR, "icon.ico")
    master.save(ico, sizes=[(n, n) for n in SIZES])
    print("图标:", ico, "（%s）" % "/".join(str(n) for n in SIZES))
    print("预览:", png, "%d×%d" % master.size)


if __name__ == "__main__":
    main()
