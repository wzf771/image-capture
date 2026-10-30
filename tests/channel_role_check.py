# -*- coding: utf-8 -*-
"""通道配色自检（用户反馈的 bug：单通道荧光被显示成灰度）。

规则（core/loader.py `_assign_roles`）：
  · 名字/照明类型认出明场（TD1 / Transmitted Light / BF / T PMT…）→ 灰底
  · 荧光通道 → 按染料给色（GFP 绿、YFP 黄、mCherry 红…），认不出就按顺序给
  · "把第一路当灰底"这条只对**不像荧光**的第一路生效 ——
    单通道 GFP（CHS1 + LightType=Fluorescence）以前会被无条件改成灰度
"""
import glob
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from core import loader                                                # noqa: E402
from core.model import GRAY, GREEN, RED                                # noqa: E402

res = {}
ok1 = True
found = 0
for p in sorted(glob.glob(P(r"E:\XY\**\FRAP*.oib"), recursive=True))[:6]:
    it = loader.probe(p)
    if len(it.channels) != 1:
        continue
    c = it.channels[0]
    found += 1
    ok1 = ok1 and c.role == "green" and tuple(c.color) == tuple(GREEN)
    print("  %-26s %s light=%s → role=%s color=%s"
          % (os.path.basename(p), c.name, c.light, c.role, c.color))
print("[1] 单通道荧光 → 彩色（查了 %d 个）：%s" % (found, "OK" if (ok1 and found) else "不过"))
res["单通道荧光"] = bool(ok1 and found)

p2 = P(r"E:\XY\亚细胞定位部\3.31构载体两个\6.4\ER1.oib")
it2 = loader.probe(p2)
roles = [(c.name, c.role) for c in it2.channels]
ok2 = any(r == "gray" for _n, r in roles) and any(r == "green" for _n, r in roles)
print("[2] 明场+荧光 %s：%s" % (roles, "OK" if ok2 else "不过"))
res["明场仍为灰"] = bool(ok2)

ch3 = loader._assign_roles([dict(name="CH1", light="", ex=0, em=0)], 12)
ok3 = ch3[0].role == "gray" and tuple(ch3[0].color) == tuple(GRAY)
print("[3] 无线索单通道（'CH1'、无照明类型、无波长）→ %s（保守起见仍当灰底）" % ch3[0].role)
res["无线索仍灰"] = bool(ok3)

ch4 = loader._assign_roles([dict(name="GFP", light="", ex=488, em=510)], 12)
ch5 = loader._assign_roles([dict(name="mCherry", light="", ex=561, em=610)], 12)
ok4 = tuple(ch4[0].color) == tuple(GREEN) and tuple(ch5[0].color) == tuple(RED)
print("[4] 名字带染料：GFP→%s，mCherry→%s" % (ch4[0].color, ch5[0].color))
res["染料给色"] = bool(ok4)

# 5 图片格式（BMP/PNG/JPG/TIFF）必须"原样进、原样出"：不许再套颜色
import numpy as np                                                 # noqa: E402
from PIL import Image                                              # noqa: E402
from core import render                                            # noqa: E402
from _samples import P  # noqa: E402
imgs = (sorted(glob.glob(P(r"E:\XY\3164p.bmp.frames\*.bmp")))
        + sorted(glob.glob(r"E:\ImageCapture\output\_自检\*.tif"))[:2])
ok5 = True
n5 = 0
for p in imgs:
    if not os.path.exists(p):
        continue
    it = loader.probe(p)
    rgb = render.compose(loader.load_stack(it)[0], it.channels)
    with Image.open(p) as im:
        orig = np.asarray(im.convert("RGB"))
    good = rgb.shape == orig.shape and np.array_equal(rgb, orig)
    ok5 = ok5 and good
    n5 += 1
    if n5 <= 4:
        print("  %-26s 通道 %-28s 与文件逐像素一致=%s"
              % (os.path.basename(p), [(c.name, c.role) for c in it.channels][:1], good))
print("[5] 图片格式原样进原样出（查了 %d 个）：%s" % (n5, "OK" if (ok5 and n5) else "不过"))
res["图片原样进出"] = bool(ok5 and n5)

# 6 蔡司 CZI：通道数必须等于数据里的通道轴，名字不许带 raw 变体的 '#'
CZI = P(r"E:\ImageCapture\789\Snap-14700-Airyscan Processing-04.czi")
if os.path.exists(CZI):
    itc = loader.probe(CZI)
    stc = loader.load_stack(itc)
    names = [c.name for c in itc.channels]
    # 通道数**不超过**数据里的通道轴（重复的"原始版+处理版"会被合并，所以可以少于）
    ok6 = (1 <= len(itc.channels) <= stc.shape[1]
           and not any("#" in n for n in names))
    print("[6] CZI %s：数据 %d 通道，界面 %d 路 %s（不能出现 EGFP#/CH5 这种多余的）"
          % (os.path.basename(CZI), stc.shape[1], len(itc.channels), names))
    res["CZI通道数对"] = bool(ok6)
else:
    print("[6] CZI 不在，跳过")
    res["CZI通道数对"] = True

print()
print("结论:", "全部通过" if all(res.values()) else "有未通过项",
      "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
sys.exit(0 if all(res.values()) else 1)
