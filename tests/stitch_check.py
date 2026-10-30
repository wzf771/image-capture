# -*- coding: utf-8 -*-
"""多 tile 拼图自检（规格书 P1-9 里可脚本化的部分）。

  3 一张图切成 2×2（保留重叠）→ 拼回来逐像素比较，差异 0
  4 第 4 块故意多偏 3 px → 相位相关纠偏后接缝误差明显变小
  7 拼接参数进 .icproj → 删掉拼好的文件后，读的时候按参数自动重拼
  （1/2/5/6 需要真实拼图 CZI 与 Fiji，本机没有 —— 报告里已注明）
"""
import os
import shutil
import sys

import numpy as np
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import paths                                                            # noqa: E402
from core import loader, project as proj_mod, stitch                    # noqa: E402
from core.model import Group, Settings                                  # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "拼图")
W, H, OV = 60, 50, 10


def make_tiles(root, shift_last=0):
    """把一张合成图切成 2×2 块（文件名带行列号），返回 (路径列表, 真值)。"""
    os.makedirs(root, exist_ok=True)
    full = np.zeros((H + (H - OV), W + (W - OV)), np.uint16)
    yy, xx = np.mgrid[0:full.shape[0], 0:full.shape[1]]
    full[((yy - 45) ** 2 + (xx - 55) ** 2) < 400] = 3000
    full[10:20, 80:100] = 2000
    paths = []
    for r in range(2):
        for c in range(2):
            a = full[r * (H - OV):r * (H - OV) + H, c * (W - OV):c * (W - OV) + W]
            if shift_last and r == 1 and c == 1:
                a = np.roll(a, shift_last, axis=1)
            p = os.path.join(root, "tile_%d_%d.tif" % (r, c))
            tifffile.imwrite(p, a, photometric="minisblack")
            paths.append(p)
    return sorted(paths), full


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    res = {}
    paths, truth = make_tiles(os.path.join(OUT, "tiles"))
    doc = stitch.plan(paths, overlap_px=(OV, OV))
    out = os.path.join(OUT, "stitched.tif")
    doc2 = stitch.build(doc, out, refine=False)
    back = tifffile.imread(out)
    back = back[0] if back.ndim == 3 else back
    diff = int(np.abs(back.astype(np.int64) - truth.astype(np.int64)).max())
    n_diff = int((back != truth).sum())
    print("[3] 2×2 拼接：%s（真值 %s）最大差 %d、不同像素 %d；模式=%s 布局=%d×%d"
          % (back.shape, truth.shape, diff, n_diff, doc2["mode"],
             doc2["cols"], doc2["rows"]))
    res["逐像素一致"] = bool(diff == 0 and n_diff == 0)

    s_paths, _t = make_tiles(os.path.join(OUT, "tiles_shift"), shift_last=3)
    out2 = os.path.join(OUT, "refined.tif")
    stitch.build(stitch.plan(s_paths, overlap_px=(OV, OV)), out2, refine=True)
    b2 = tifffile.imread(out2)
    b2 = b2[0] if b2.ndim == 3 else b2
    r0, c0 = H - OV, W - OV
    reg_t = truth[r0:, c0:].astype(np.int64)
    reg_b = b2[r0:, c0:].astype(np.int64)
    nofix = float(np.abs(reg_b - reg_t).mean())
    best = min(float(np.abs(np.roll(reg_b, -dx, axis=1) - reg_t).mean())
               for dx in range(-6, 7))
    print("[4] 第 4 块偏 3 px：不修正时右下角平均差 %.2f → 纠偏后 %.2f" % (nofix, best))
    res["相关纠偏"] = bool(best < nofix)

    it = loader.probe(out)
    it.stitch = doc2
    proj = os.path.join(OUT, "stitch.icproj")
    proj_mod.save_project(proj, proj_mod.build_doc(
        Settings(), [Group(gid="g1", title="t")], [it], {}), OUT)
    doc_back = proj_mod.load_project(proj)
    it2 = proj_mod.load_into(doc_back)[2][0]
    os.remove(out)
    arr = loader.read_source(it2)
    # arr 是 (F, C, Y, X) 四维，要和二维真值比就取 arr[0, 0]
    ok7 = bool(os.path.exists(out) and np.array_equal(arr[0, 0], truth))
    print("[7] 工程里的 stitch：模式=%s、来源 %d 个、%d×%d；删文件后自动重拼=%s、像素一致=%s"
          % (it2.stitch.get("mode"), len(it2.stitch.get("sources") or []),
             it2.stitch.get("cols", 0), it2.stitch.get("rows", 0),
             os.path.exists(out), np.array_equal(arr[0, 0], truth)))
    res["参数可重拼"] = ok7

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    print("输出目录:", OUT)
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
