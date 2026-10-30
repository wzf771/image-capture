# -*- coding: utf-8 -*-
"""走一遍界面里"一键导出全部"用的同一条链路，看输出对不对。"""
import csv
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import paths                                          # noqa: E402
from core import loader                                # noqa: E402
from core.model import Group, Settings                  # noqa: E402
from ui.worker import job_export                        # noqa: E402
from _samples import P  # noqa: E402

FILES = [
    P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\2a-1.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\2a-2.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\kongzai.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\6.4\ER1.oib"),
    P(r"E:\XY\相分离部\6.3\6.3\frap\3-6\FRAPR1.oib"),
]
OUT = os.path.join(paths.OUTPUT_DIR, "_导出自检")


def main():
    if os.path.isdir(OUT):
        for root, _dirs, files in os.walk(OUT, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
    os.makedirs(OUT, exist_ok=True)
    items = [loader.probe(p) for p in FILES if os.path.exists(p)]
    buckets = {}
    for it in items:
        buckets.setdefault((it.width, it.height, round(it.umpp, 4)), []).append(it)
    groups = []
    for n, (key, its) in enumerate(sorted(buckets.items(), key=lambda kv: (-kv[0][2], -kv[0][0])), 1):
        g = Group(gid="g%d" % n, title="组%d_%s" % (n, ("%g" % key[2]) if key[2] else "未标定"))
        g.images = its
        field = its[0].field_um() or 100.0
        g.box = dict(x=(field - 30) / 2, y=(field - 30) / 2, w=30.0, h=30.0)
        groups.append(g)

    st = Settings()
    st.exp_merge = True
    st.exp_ch = [True, False, True]
    st.out_suffix = "_crop"
    st.bar_font = "Arial"
    jobs = []
    for g in groups:
        for it in g.images:
            frames = [12] if it.frames > 1 else [0]
            jobs.append((it, g, frames))
    rows = job_export(jobs, st, OUT, report=lambda i, t, m: None)

    print("导出的文件：")
    for root, _dirs, files in os.walk(OUT):
        for f in sorted(files):
            full = os.path.join(root, f)
            print("   %-58s %6.1f KB" % (os.path.relpath(full, OUT), os.path.getsize(full) / 1024))
    csv_path = os.path.join(OUT, "处理报告.csv")
    keys = ["group", "name", "frame", "frames", "umpp", "calib", "box", "field", "bar", "files", "out"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\n报告:", csv_path)
    print("共 %d 张 → %d 个文件" % (len(rows), sum(int(r.get("files") or 0) for r in rows)))
    for r in rows[:4]:
        print("   %-12s %s  %s" % (r.get("name"), r.get("umpp"), r.get("bar")))


if __name__ == "__main__":
    main()
