# -*- coding: utf-8 -*-
"""把界面截图排成小红书（3:4）与抖音（9:16）用的竖版图。

输入：E:\ImageCapture\dist\press\shot_*.png
输出：同目录 xhs_*.png / dy_*.png
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = r"E:\ImageCapture\dist\press"
BG = (244, 242, 237)
INK = (31, 30, 28)
INK2 = (111, 109, 102)
ACCENT = (168, 100, 42)
CARD = (255, 255, 255)

F_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
F_REG = r"C:\Windows\Fonts\msyh.ttc"


def font(size, bold=False):
    return ImageFont.truetype(F_BOLD if bold else F_REG, size)


def text(d, xy, s, size=40, bold=False, fill=INK, anchor="la"):
    d.text(xy, s, font=font(size, bold), fill=fill, anchor=anchor)


def rounded(img, radius):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0], img.size[1]], radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def paste_card(base, shot_path, box_w, top, pad=28, radius=26):
    shot = Image.open(shot_path).convert("RGB")
    scale = box_w / shot.width
    shot = shot.resize((box_w, int(shot.height * scale)), Image.LANCZOS)
    card_w, card_h = shot.width + pad * 2, shot.height + pad * 2
    x = (base.width - card_w) // 2
    # 投影
    shadow = Image.new("RGBA", (card_w + 60, card_h + 60), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i in range(18, 0, -2):
        a = 5
        sd.rounded_rectangle([30 - i, 34 - i, 30 + card_w + i, 34 + card_h + i],
                             radius + i, fill=(33, 30, 24, a))
    base.alpha_composite(shadow, (x - 30, top - 30))
    card = Image.new("RGBA", (card_w, card_h), CARD + (255,))
    card = rounded(card, radius)
    base.alpha_composite(card, (x, top))
    base.alpha_composite(rounded(shot, radius - 6), (x + pad, top + pad))
    return top + card_h


def cover(path, size, kicker, title_lines, sub, shot, badge=None, dy=False):
    W, H = size
    base = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(base)

    top = 96 if not dy else 150
    text(d, (72, top), kicker, 34, True, ACCENT)
    y = top + 62
    for line in title_lines:
        text(d, (72, y), line, 76 if not dy else 84, True, INK)
        y += 100 if not dy else 112
    y += 8
    for line in sub:
        text(d, (72, y), line, 34, False, INK2)
        y += 50
    y += 34
    bottom = paste_card(base, shot, W - 150, y)
    if badge:
        bw = 0
        pad = 20
        for s in badge:
            bw = max(bw, d.textlength(s, font=font(30)))
        bx, by = 72, min(bottom + 48, H - 150)
        for s in badge:
            tw = d.textlength(s, font=font(30))
            d.rounded_rectangle([bx, by, bx + tw + pad * 2, by + 62], 31,
                                fill=(232, 226, 214, 255))
            text(d, (bx + pad, by + 15), s, 30, False, INK)
            bx += tw + pad * 2 + 14
    text(d, (72, H - 96), "Image capture · 显微图像统一视野裁剪", 30, True, INK2)
    base.convert("RGB").save(path, quality=95)
    print("写出", path, size)


def main():
    cover(os.path.join(OUT, "xhs_1_cover.png"), (1080, 1440),
          "显微图像 · 统一视野",
          ["不同倍数拍的图", "一键裁成一模一样"],
          ["20×、40×、100× 混着拍？", "裁出来的视野和尺寸，全组统一。"],
          os.path.join(OUT, "shot_main.png"),
          badge=["组内裁剪框一致", "实时直方图", "批量导出"])

    cover(os.path.join(OUT, "xhs_2_crop.png"), (1080, 1440),
          "01 · 裁剪",
          ["框一次，全组跟着走"],
          ["拖框、滚轮缩放、双击复位；", "组内所有图共用同一个裁剪框。"],
          os.path.join(OUT, "shot_crop.png"),
          badge=["1:1 锁定", "±0.1 µm 精度"])

    cover(os.path.join(OUT, "xhs_3_channel.png"), (1080, 1440),
          "02 · 通道与色阶",
          ["每一路都有真实直方图"],
          ["绿、红、灰阶三路各拖各的黑白场；", "直方图就是这张图真实像素的分布。"],
          os.path.join(OUT, "shot_channel_real.png"),
          badge=["对数归一化直方图", "按通道调色"])

    cover(os.path.join(OUT, "xhs_4_export.png"), (1080, 1440),
          "03 · 标尺与导出",
          ["标尺、色彩、命名一次搞定"],
          ["µm 标尺自动换算，长短、粗细、字号都能调；", "PNG / TIFF 任选，导完直接给你一份清单。"],
          os.path.join(OUT, "shot_ruler.png"),
          badge=["批量导出", "标尺可调"])

    cover(os.path.join(OUT, "xhs_5_timeseries.png"), (1080, 1440),
          "04 · 时间序列",
          ["拍一小时的片子", "漂移也给你掰正"],
          ["逐帧估 XY 漂移、自动平移对齐；", "参考帧随便换，播放时 50 个时间点顺滑翻。"],
          os.path.join(OUT, "shot_timeseries.png"),
          badge=["逐帧漂移校正", "参考帧可换", "1/4×–3× 播放"])

    cover(os.path.join(OUT, "dy_1_cover.png"), (1080, 1920),
          "显微图像 · 统一视野",
          ["不同倍数拍的图", "一键裁成一模一样"],
          ["20×、40×、100× 混着拍也同样处理，", "裁剪视野、输出尺寸、标尺全部统一。"],
          os.path.join(OUT, "shot_main.png"),
          badge=["组内裁剪框一致", "实时直方图", "批量导出"], dy=True)


if __name__ == "__main__":
    main()
