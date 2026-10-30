# -*- coding: utf-8 -*-
"""真实图上的标尺识别自检（规格书 5.4 验收第 2、8 条）。

用户实拍的四张 3164p 导出帧（BMP，自带 140 µm 标尺）：
  · 每张都要读到 140 µm、算出 ≈0.6185 µm/px（与改动前的实测值完全一致）
  · 逐张报耗时，算平均；这是"批量识别不能变慢"的证据
  · 全黑空帧要秒退（时间序列里空帧很常见）
"""
import os
import sys
import time

import numpy as np
from PIL import Image

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from core import bar                                                  # noqa: E402
from _samples import P  # noqa: E402

DIR = P(r"E:\XY\3164p.bmp.frames")
EXPECT = 0.6185          # 改动前用同一张图实测的值（smoke.py 里也有这条）


def main():
    files = sorted(os.path.join(DIR, f) for f in os.listdir(DIR)
                   if f.lower().endswith(".bmp"))
    if not files:
        print("跳过：%s 里没有 BMP" % DIR)
        return 0
    print("真实图标尺识别（期望 %.4f µm/px，容差 2%%）" % EXPECT)
    times, bad = [], []
    for p in files:
        rgb = np.asarray(Image.open(p).convert("RGB"))
        t0 = time.time()
        res = bar.detect_umpp(rgb)
        dt = time.time() - t0
        times.append(dt)
        dev = abs(res.get("umpp", 0) - EXPECT) / EXPECT
        if not res.get("ok") or dev > 0.02:
            bad.append((os.path.basename(p), res))
        print("  %-18s %s  读到 %-8s umpp=%.4f（偏差 %.1f%%）方向=%s 置信=%-4s %.2fs"
              % (os.path.basename(p), "OK " if (res.get("ok") and dev <= 0.02) else "不过",
                 res.get("text"), res.get("umpp", 0.0), 100 * dev, res.get("orientation"),
                 res.get("confidence"), dt))
    print("  平均 %.2fs/张（共 %d 张）" % (sum(times) / len(times), len(times)))
    # 空帧：时间序列里常见，必须秒退
    t0 = time.time()
    rb = bar.detect_umpp(np.zeros((1024, 1024), np.uint8))
    dtb = time.time() - t0
    print("  全黑 1024² 空帧：%.3fs，why=%s" % (dtb, rb.get("why")))
    print()
    ok = not bad and dtb < 0.5
    print("结论:", "全部通过" if ok else "有未通过项 %s" % bad)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
