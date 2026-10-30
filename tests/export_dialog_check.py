# -*- coding: utf-8 -*-
"""导出弹窗自检：点 Download 后"先选图片、再选导出内容"这条链路。

查这几件事：
  ① 默认全勾（未标定 / 原文件丢了的图灰掉、不能勾）
  ② 底部汇总的"几张 → 几个文件"跟 refresh_manifest 报的数字一致
  ③ 只勾一张时，真导出只出这一张的文件（走 _build_jobs 的 picked 分支）
  ④ 全不选时右栏与"开始导出"都置灰；取消时 pick() 返回 None（不导）
  ⑤ 组节点的三态：组里取消一张 → 组变半选
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtCore import QTimer, Qt                            # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase                   # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

import paths                                                     # noqa: E402
from core import loader                                          # noqa: E402
from ui.main_window import MainWindow                            # noqa: E402
from ui.worker import job_export                                 # noqa: E402
from _samples import P  # noqa: E402

FILES = [
    P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\2a-1.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\6.4\ER1.oib"),
]
OUT = os.path.join(paths.OUTPUT_DIR, "_导出自检_弹窗")


def _clean_out():
    if os.path.isdir(OUT):
        for root, _d, files in os.walk(OUT, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
    os.makedirs(OUT, exist_ok=True)


def _count_files(root):
    n = 0
    for _r, _d, fs in os.walk(root):
        n += len([f for f in fs if not f.lower().endswith(".csv")])
    return n


def main():
    _clean_out()
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1400, 900)
    win.items = [loader.probe(p) for p in FILES if os.path.exists(p)]
    # 再塞一张没标定的（BMP 不给标定），用来验"灰掉、不能导"
    bmp = P(r"E:\XY\3164p.bmp.frames\3164p_T001.bmp")
    if os.path.exists(bmp):
        bad = loader.probe(bmp)
        bad.umpp = 0.0
        bad.calib = "未标定"
        win.items.append(bad)
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.show()
    for _ in range(6):
        app.processEvents()

    dlg = win.exp_dialog
    res = {}

    # ① 默认全勾 + 未标定的灰掉
    dlg._fill_tree(win.groups)
    n_ok = len(dlg._picked_rows())
    n_all = sum(len(g.images) for g in win.groups)
    grey = [it.name for _row, it, _g in dlg._rows.values()
            if not (dlg._rows[it.path][0].flags() & Qt.ItemIsUserCheckable)]
    ok1 = (n_ok == n_all - len(grey)) and n_ok > 0
    print("[1] 默认勾选 %d 张（共 %d 张，灰掉 %d 张：%s）→ %s"
          % (n_ok, n_all, len(grey), "、".join(grey) or "无", "OK" if ok1 else "不过"))
    res["默认全勾"] = bool(ok1)

    # ② 汇总数字 == 底栏清单的数字
    dlg._refresh_summary()
    txt = dlg.lbl_sum.text()
    win.refresh_manifest()
    manifest = win.manifest.toolTip()
    import re
    m1 = re.search(r"预计 (\d+) 个文件", txt)
    m2 = re.search(r"合计 (\d+) 个文件", manifest)
    ok2 = bool(m1 and m2 and m1.group(1) == m2.group(1))
    print("[2] 弹窗汇总「%s」\n        底栏清单「%s」→ %s"
          % (txt, manifest.splitlines()[-1], "OK" if ok2 else "不过"))
    res["汇总一致"] = ok2

    # ⑤ 组三态：取消组里一张 → 组节点半选
    from core.model import Group                                 # noqa: E402
    tg = Group(gid="tmp", title="测试组")
    tg.images = list(win.items[:2])
    dlg._fill_tree([tg])
    head = dlg.tree.topLevelItem(0)
    if head is not None and head.childCount() >= 2:
        dlg._quiet = True
        head.child(0).setCheckState(0, Qt.Unchecked)
        dlg._quiet = False
        dlg._on_item_changed(head.child(0), 0)
        ok5 = head.checkState(0) == Qt.PartiallyChecked
        print("[5] 组里取消一张后，组节点 = %s → %s"
              % (("半选" if ok5 else str(head.checkState(0))), "OK" if ok5 else "不过"))
        res["组三态"] = bool(ok5)
    else:
        print("[5] 组里不足两张，跳过组三态检查")
        res["组三态"] = True

    # ④ 全不选 → 右栏与开始按钮置灰
    dlg.select_none()
    dlg._refresh_summary()
    ok4 = (not dlg.btn_go.isEnabled()) and (not dlg.right_host.isEnabled())
    print("[4] 全不选：开始导出置灰=%s，导出内容栏置灰=%s → %s"
          % (not dlg.btn_go.isEnabled(), not dlg.right_host.isEnabled(),
             "OK" if ok4 else "不过"))
    res["全不选置灰"] = bool(ok4)

    # ③ 只勾一张 → 真导出只出这一张
    dlg._fill_tree(win.groups)
    for path, (row, it, _g) in dlg._rows.items():
        if row.flags() & Qt.ItemIsUserCheckable:
            row.setCheckState(0, Qt.Checked if it is win.items[0] else Qt.Unchecked)
    dlg._refresh_summary()
    picked = dlg._picked_rows()
    st = win._sync_settings()
    st.out_dir = OUT
    jobs = win._build_jobs("picked", picked=picked)
    rows = job_export(jobs, st, OUT, report=lambda i, t, m: None)
    n_files = _count_files(OUT)
    n_rows = len(rows)
    ok3 = (n_rows == 1 and n_files >= 1 and rows[0]["name"] == win.items[0].name)
    print("[3] 只勾「%s」→ 导出 %d 张 / %d 个文件（%s）→ %s"
          % (win.items[0].name, n_rows, n_files,
             "、".join(sorted(os.listdir(os.path.join(OUT, os.listdir(OUT)[0]))))[:60]
             if os.listdir(OUT) else "",
             "OK" if ok3 else "不过"))
    res["只导勾选的"] = bool(ok3)

    # 取消：pick() 要返回 None
    dlg._fill_tree(win.groups)
    QTimer.singleShot(60, dlg.reject)
    got = dlg.pick(win.groups, focus_item=win.cur_item)
    ok6 = got is None
    print("[6] 点取消 → pick() 返回 %s → %s" % (got, "OK" if ok6 else "不过"))
    res["能取消"] = bool(ok6)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
