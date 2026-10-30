# -*- coding: utf-8 -*-
"""标尺识别增强自检（规格书 P2-14 的验收部分）。

覆盖：
  1 横标尺 —— 结果必须与改动前一致（回归）
  2 竖标尺 —— 改动前完全识别不了，现在要能认
  3 千分位 1,000 µm —— 老写法会算成 1.0 µm（差 1000 倍）
  4 返回结构：orientation / confidence / score / candidates（向后兼容）
  5 纯色图快速失败（不跑 OCR）

合成图：暗底 + 白线 + 白字，字放在线旁边（横标尺字在上方、竖标尺字在左方）。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from core import bar

FONT = r"C:\Windows\Fonts\arial.ttf"


def _font(size=34):
    try:
        return ImageFont.truetype(FONT, size)
    except Exception:
        return ImageFont.load_default(size=size)


def make_image(w, h, text, orient="h", bar_len=200, thick=6, bg=20, ink=235):
    """做一张自带标尺的测试图：orient=h 横线（字在上）/ v 竖线（字在左）。"""
    a = np.full((h, w), bg, np.uint8)
    img = Image.fromarray(a).convert("RGB")
    d = ImageDraw.Draw(img)
    f = _font()
    tw = d.textbbox((0, 0), text, font=f)[2]
    th = d.textbbox((0, 0), text, font=f)[3]
    if orient == "h":
        x0 = (w - bar_len) // 2
        y = h // 2 + 40
        d.rectangle([x0, y, x0 + bar_len, y + thick], fill=(ink, ink, ink))
        d.text((x0 + (bar_len - tw) / 2, y - th - 12), text, font=f, fill=(ink, ink, ink))
    else:
        y0 = (h - bar_len) // 2
        x = w // 2 + 40
        d.rectangle([x, y0, x + thick, y0 + bar_len], fill=(ink, ink, ink))
        d.text((x - tw - 12, y0 + (bar_len - th) / 2), text, font=f, fill=(ink, ink, ink))
    return np.asarray(img)


def run_case(name, rgb, expect_umpp, expect_orient):
    res = bar.detect_umpp(rgb)
    ok = bool(res.get("ok"))
    got = res.get("umpp", 0.0)
    dev = abs(got - expect_umpp) / expect_umpp if expect_umpp else 9.9
    good = ok and dev < 0.02 and res.get("orientation") == expect_orient
    print("  %-24s ok=%-6s umpp=%.4f 期望 %.4f 偏差 %.1f%% 方向=%s 置信=%s -> %s"
          % (name, ok, got, expect_umpp, 100 * dev, res.get("orientation"),
             res.get("confidence"), "OK" if good else "不过"))
    if not good:
        print("       why =", res.get("why"))
    return good


def main():
    print("[1] 横标尺（回归：改动前也是这么用的）")
    a = run_case("横线 200px = 50µm", make_image(700, 700, "50 µm"), 50.0 / 200, "h")
    print("[2] 竖标尺（改动前完全识别不了）")
    b = run_case("竖线 200px = 50µm", make_image(700, 700, "50 µm", orient="v"),
                 50.0 / 200, "v")
    print("[3] 千分位（老写法会算成 1.0µm，差 1000 倍）")
    c = run_case("横线 2000px = 1,000µm", make_image(2200, 900, "1,000 µm", bar_len=2000),
                 1000.0 / 2000, "h")
    print("[4] 返回结构")
    res = bar.detect_umpp(make_image(700, 700, "50 µm"))
    keys = ("orientation", "confidence", "score", "candidates")
    has = [k for k in keys if k in res]
    old = all(k in res for k in ("ok", "umpp", "text", "why"))
    print("   新字段:", has)
    print("   老字段 ok/umpp/text/why 仍在:", old)
    d = len(has) == len(keys) and old
    if res.get("candidates"):
        top = res["candidates"][0]
        print("   候选打分: score=%.3f line_ratio=%.3f contrast=%.3f ocr=%.2f"
              % (top["score"], top["length_ratio"], top["contrast"], top["ocr"]))
    print("[5] 纯色图快速失败")
    import time
    blank = np.full((800, 800), 12, np.uint8)
    t0 = time.time()
    rb = bar.detect_umpp(blank)
    dt = time.time() - t0
    print("   全黑图：ok=%s why=%s 耗时 %.3fs（跑 OCR 的话要 1s 以上）"
          % (rb.get("ok"), rb.get("why"), dt))
    e = (not rb.get("ok")) and dt < 0.5
    print()
    ok = bool(a and b and c and d and e)
    print("结论:", "全部通过" if ok else "有未通过项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
