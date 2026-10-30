# -*- coding: utf-8 -*-
"""工程文件 + 撤销自检（规格书 P0-1 的九条验收）。

覆盖：
  1 存 → 关 → 重开，分组 / 裁剪框 / 标定 / 标尺位置 / 当前视图 全部原样恢复
  2 工程和图片一起换个根目录（模拟换盘符）→ 靠 rel 还能打开
  3 两张图改名 → 打开时不报错，只标成"原文件不存在"，导出自动跳过
  4 打开工程后新建组 → key 不撞车（_regroup 后图不串组）
  5 拖裁剪框 → 撤销回到原位 → 重做回到新位
  6 撤销栈：限 50 步、限体积
  7 工程文件大小：50 张 < 1 MB
  8 自动保存 + 崩溃恢复（autosave 比"正常退出"新才提示）
  9 自动保存不覆盖正式工程文件
"""
import os
import shutil
import sys

import numpy as np
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtCore import QPoint, Qt as QtNS                            # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase                          # noqa: E402
from PySide6.QtTest import QTest                                        # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox                 # noqa: E402

import paths                                                            # noqa: E402
from core import loader                                                 # noqa: E402
from core import project as proj_mod                                    # noqa: E402
from ui.main_window import MainWindow                                   # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "工程自检")
N = 10


def _silence_dialogs():
    """离屏跑测试不能弹模态框。"""
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)


def make_images(root, n=N, size=220):
    """造 n 张图：后 3 张尺寸不同，好让自动分桶分出不止一组。"""
    os.makedirs(root, exist_ok=True)
    out = []
    rng = np.random.default_rng(7)
    for i in range(n):
        side = size + (60 if i >= n - 3 else 0)
        a = rng.integers(10, 60, (side, side, 3), dtype=np.uint8)
        a[side // 3:side // 3 + 14, 30:side - 30] = 235
        p = os.path.join(root, "img%02d.png" % i)
        Image.fromarray(a).save(p)
        out.append(p)
    return out


def fresh_window(app):
    win = MainWindow()
    win.resize(1460, 940)
    app.processEvents()
    return win


def load_items(paths_in):
    return [loader.probe(p) for p in paths_in]


def unlock(win):
    """等缩略图线程跑完并放掉像素缓存 —— Windows 上文件被占用就没法改名。"""
    try:
        if win._thumb_worker and win._thumb_worker.isRunning():
            win._thumb_worker.stop()
            win._thumb_worker.wait(2000)
    except Exception:                            # noqa: BLE001
        pass
    for it in win.items:
        try:
            loader.release(it)
        except Exception:                        # noqa: BLE001
            pass
    QApplication.processEvents()


def check_restored(tag, win, want_box, want_umpp, want_view):
    """核对"打开工程后该恢复的都恢复了"。返回 (是否全对, 差异清单)。"""
    bad = []
    if len(win.items) != N:
        bad.append("图片数 %d≠%d" % (len(win.items), N))
    if len(win.groups) != len(want_box):
        bad.append("组数 %d≠%d" % (len(win.groups), len(want_box)))
    for g in win.groups:
        exp = want_box.get(g.key)
        if exp is None:
            bad.append("多出一组 %s(key %s)" % (g.title, g.key))
        else:
            for k in ("x", "y", "w", "h"):
                if abs(float(g.box.get(k, 0)) - float(exp[k])) > 1e-6:
                    bad.append("%s 的裁剪框 %s %g≠%g"
                               % (g.title, k, g.box.get(k, 0), exp[k]))
    for it in win.items:
        exp = want_umpp.get(it.path)
        if exp is None:
            bad.append("多出一张 %s" % it.path)
        elif abs(it.umpp - exp) > 1e-9:
            bad.append("%s 的 µm/px %g≠%g" % (it.name, it.umpp, exp))
    g0 = next((g for g in win.groups if g.bar_anchor), None)
    if g0 is None or abs(g0.bar_anchor[0] - 0.31) > 1e-6:
        bad.append("标尺自定义位置没恢复")
    if win.view_mode != want_view["mode"]:
        bad.append("视图 %s≠%s" % (win.view_mode, want_view["mode"]))
    print("    %s：%s%s" % (tag, "全部一致" if not bad else "有差异",
                           "" if not bad else "\n      " + "\n      ".join(bad[:6])))
    return (not bad), bad


def main():
    _silence_dialogs()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    # 缺文件面板是模态框，离屏测试会卡死：全类替换成记录器（缺文件的数据照样算）
    seen_missing = []
    MainWindow._ask_missing = lambda self, miss: seen_missing.append(list(miss))

    # 自动保存 / 最近打开 指到自检目录，别碰用户的 config
    paths.AUTOSAVE_FILE = os.path.join(OUT, "autosave.icproj")
    paths.RECENT_FILE = os.path.join(OUT, "recent.json")
    paths.LAST_EXIT_FILE = os.path.join(OUT, "last_exit.txt")

    src = os.path.join(OUT, "原图")
    files = make_images(src)
    proj_dir = os.path.join(OUT, "工作")
    os.makedirs(proj_dir, exist_ok=True)
    proj_path = os.path.join(proj_dir, "实验一.icproj")

    # ---------- 造一个"干了半天活"的工作区 ----------
    win = fresh_window(app)
    win.items = load_items(files)
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_group(win.groups[0].gid)
    app.processEvents()
    want_box, want_umpp = {}, {}
    for k, g in enumerate(win.groups):
        field = g.images[0].field_um() or 200.0
        g.box = dict(x=3.0 + 7 * k, y=5.0 + 5 * k, w=min(30.0, field), h=min(30.0, field))
        g.title = "样品 %s" % chr(ord("A") + k)
        g.title_manual = True
        if k == 0:
            g.bar_anchor = (0.31, 0.42)
            g.bar_text_anchor = (0.33, 0.55)
        want_box[g.key] = dict(g.box)
        for it in g.images:
            it.umpp = 0.5 + 0.1 * k              # 假装标定过
            it.calib = "手动画线标定"
            want_umpp[it.path] = it.umpp
    win.cur_item = win.groups[0].images[0]
    win.view_mode = "crop"
    win._proj_path = proj_path
    ok_save = win.proj_save()
    size_kb = os.path.getsize(proj_path) / 1024.0
    print("[1] 保存工程：%s（%.1f KB · %d 张 · %d 组）"
          % (os.path.basename(proj_path), size_kb, len(win.items), len(win.groups)))
    ok1 = bool(ok_save)

    # ---------- 2 重开一次，逐项核对 ----------
    win2 = fresh_window(app)
    ok_open = win2.open_project(proj_path)
    app.processEvents()
    ok2, _ = check_restored("重开核对", win2, want_box, want_umpp, {"mode": "crop"})
    ok2 = bool(ok_open) and ok2
    print("        标题栏：%s" % win2.windowTitle())
    ok2 = ok2 and ("实验一.icproj" in win2.windowTitle())

    # ---------- 3 工程 + 图片一起搬到另一个根目录（模拟换盘符）----------
    moved_root = os.path.join(OUT, "搬到别处")
    os.makedirs(moved_root, exist_ok=True)
    shutil.copytree(proj_dir, os.path.join(moved_root, "工作"))
    shutil.copytree(src, os.path.join(moved_root, "原图"))
    shutil.rmtree(src, ignore_errors=True)       # 原位置删掉：只能靠 rel 找回
    shutil.rmtree(proj_dir, ignore_errors=True)
    moved_proj = os.path.join(moved_root, "工作", "实验一.icproj")
    win3 = fresh_window(app)
    win3.open_project(moved_proj)
    app.processEvents()
    n_missing = sum(1 for x in win3.items if x.missing)
    print("[2] 换个根目录打开：%d 张，找不到的 %d 张（应为 0）" % (len(win3.items), n_missing))
    ok3 = len(win3.items) == N and n_missing == 0
    unlock(win3)

    # ---------- 4 两张图改名 → 只标缺，不报错，导出跳过 ----------
    os.rename(os.path.join(moved_root, "原图", "img00.png"),
              os.path.join(moved_root, "原图", "img00_改名了.png"))
    os.rename(os.path.join(moved_root, "原图", "img01.png"),
              os.path.join(moved_root, "原图", "img01_改名了.png"))
    win4 = fresh_window(app)
    seen = seen_missing
    win4.open_project(moved_proj)
    app.processEvents()
    miss = [x for x in win4.items if x.missing]
    jobs = win4._build_jobs("all")
    print("[3] 改名 2 张：缺 %d 张，面板收到 %d 张；导出任务 %d 张（应为 %d）"
          % (len(miss), len(seen[0]) if seen else 0, len(jobs), N - 2))
    ok4 = (len(miss) == 2 and bool(seen) and len(seen[0]) == 2 and len(jobs) == N - 2)
    win4.relocate_item(miss[0], os.path.join(moved_root, "原图", "img00_改名了.png"))
    ok4 = ok4 and not miss[0].missing

    # ---------- 5 新建组不撞 key ----------
    keys_before = {g.key for g in win4.groups}
    win4.new_group()
    new_key = win4.groups[-1].key
    dup = [g.key for g in win4.groups if g.key == new_key]
    print("[4] 打开后新建组：key=%s，原有 key=%s，撞车=%s"
          % (new_key, sorted(keys_before), len(dup) > 1))
    ok5 = new_key not in keys_before and len(dup) == 1

    # ---------- 6 拖裁剪框 → 撤销 / 重做 ----------
    win5 = fresh_window(app)
    win5.open_project(moved_proj)
    win5.set_view_mode("full")
    app.processEvents()
    cv = win5.canvas
    cv.set_box(dict(win5.cur_group.box))
    before = dict(win5.cur_group.box)
    r = cv._box_rect()
    start = QPoint(r.center().x(), r.center().y())
    QTest.mousePress(cv, QtNS.LeftButton, QtNS.NoModifier, start)
    QTest.mouseMove(cv, QPoint(start.x() + 40, start.y() + 30))
    QTest.mouseRelease(cv, QtNS.LeftButton, QtNS.NoModifier,
                       QPoint(start.x() + 40, start.y() + 30))
    app.processEvents()
    moved = dict(win5.cur_group.box)
    win5.do_undo()
    app.processEvents()
    undone = dict(win5.cur_group.box)
    win5.do_redo()
    app.processEvents()
    redone = dict(win5.cur_group.box)

    def same(a, b):
        return all(abs(float(a[k]) - float(b[k])) < 1e-6 for k in ("x", "y", "w", "h"))

    print("[5] 拖前 %s → 拖后 %s" % (tuple(round(v, 2) for v in before.values()),
                                     tuple(round(v, 2) for v in moved.values())))
    print("        撤销后 %s（=拖前），重做后 %s（=拖后）"
          % (tuple(round(v, 2) for v in undone.values()),
             tuple(round(v, 2) for v in redone.values())))
    ok6 = same(undone, before) and same(redone, moved) and not same(before, moved)

    # ---------- 6b 拖标尺 → 撤销也要回到原位 ----------
    win5.cb_pos.blockSignals(True)
    win5.cb_pos.setCurrentIndex(4)          # 自定义位置：图上可拖
    win5.cb_pos.blockSignals(False)
    win5.set_view_mode("crop")
    app.processEvents()
    zone = (win5.canvas._bar_zones or {}).get("bar")
    if zone is not None:
        anchor0 = tuple(win5.cur_group.bar_anchor or (0.0, 0.0))
        s0 = QPoint(zone.center().x(), zone.center().y())
        QTest.mousePress(cv, QtNS.LeftButton, QtNS.NoModifier, s0)
        QTest.mouseMove(cv, QPoint(s0.x() - 30, s0.y() - 20))
        QTest.mouseRelease(cv, QtNS.LeftButton, QtNS.NoModifier,
                           QPoint(s0.x() - 30, s0.y() - 20))
        app.processEvents()
        anchor1 = tuple(win5.cur_group.bar_anchor or (0.0, 0.0))
        win5.do_undo()
        app.processEvents()
        anchor2 = tuple(win5.cur_group.bar_anchor or (0.0, 0.0))
        close = lambda a, b: abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
        print("        标尺 %s → %s → 撤销后 %s"
              % (tuple(round(v, 3) for v in anchor0), tuple(round(v, 3) for v in anchor1),
                 tuple(round(v, 3) for v in anchor2)))
        ok6 = ok6 and (not close(anchor0, anchor1)) and close(anchor0, anchor2)
    else:
        print("        没找到标尺命中区，跳过标尺拖动检查")

    # ---------- 7 撤销栈的步数与体积上限 ----------
    us = proj_mod.UndoStack(max_steps=50)
    for i in range(70):
        us.push("第 %d 次" % i, {"i": i})
    step_ok = us.depth()[0] == 50
    us2 = proj_mod.UndoStack(max_steps=50, max_bytes=200 * 1024)
    for i in range(30):
        us2.push("大块 %d" % i, {"blob": "x" * 40000})
    vol_ok = us2.sizes()[0] <= 200 * 1024 and us2.depth()[0] < 30
    print("[6] 撤销栈：70 次后深度 %d（上限 50，%s）；超体积后深度 %d、占用 %d KB（≤200，%s）"
          % (us.depth()[0], "OK" if step_ok else "不过", us2.depth()[0],
             us2.sizes()[0] / 1024, "OK" if vol_ok else "不过"))
    ok7 = step_ok and vol_ok

    # ---------- 8 50 张的工程文件大小 ----------
    many = os.path.join(OUT, "五十张")
    big_files = make_images(many, n=50)
    win6 = fresh_window(app)
    win6.items = load_items(big_files)
    win6._regroup()
    big_proj = os.path.join(OUT, "五十张.icproj")
    proj_mod.save_project(big_proj, win6._snapshot(), OUT)
    mb = os.path.getsize(big_proj) / 1024.0
    print("[7] 50 张的工程文件：%.1f KB（验收要求 < 1024 KB）" % mb)
    ok8 = mb < 1024.0

    # ---------- 9 自动保存 + 崩溃恢复 ----------
    win6._no_save = staticmethod(lambda: False)     # 临时允许写盘（路径已指向自检目录）
    win6._dirty = True
    wrote = win6.write_autosave()
    doc_auto = proj_mod.load_project(paths.AUTOSAVE_FILE)
    asked = []
    asked_count = []
    QMessageBox.question = staticmethod(
        lambda *a, **k: (asked_count.append(1) and 0) or QMessageBox.Discard)
    win6.restore_autosave = lambda: asked.append("restore")     # 别真的换工作区
    if os.path.exists(paths.LAST_EXIT_FILE):
        os.remove(paths.LAST_EXIT_FILE)
    win6._check_autosave()                          # 没有"正常退出"记录 → 该问
    first = len(asked)
    n_ask1 = len(asked_count)
    with open(paths.LAST_EXIT_FILE, "w", encoding="utf-8") as fh:
        fh.write("9999999999")                      # 假装刚正常退出过
    win6._check_autosave()                          # 这次不该问
    second = len(asked)
    n_ask2 = len(asked_count)
    same_items = len(doc_auto.get("items") or []) == 50
    print("[8] 自动保存 %s：%d 张；无退出记录时提示=%s，正常退出后提示=%s"
          % (os.path.basename(paths.AUTOSAVE_FILE), len(doc_auto.get("items") or []),
             "是" if n_ask1 else "否", "是" if n_ask2 > n_ask1 else "否"))
    ok9 = bool(wrote) and same_items and n_ask1 == 1 and n_ask2 == n_ask1

    # ---------- 10 自动保存不覆盖正式工程 ----------
    keep = open(moved_proj, "rb").read()
    win6.write_autosave()
    unchanged = open(moved_proj, "rb").read() == keep
    print("[9] 自动保存只写 autosave.icproj，正式工程没被碰：%s" % ("是" if unchanged else "否"))
    ok10 = unchanged

    print()
    flags = (ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9, ok10)
    names = ("保存", "重开恢复", "换目录", "缺文件", "新组key", "撤销重做",
             "栈上限", "文件大小", "自动保存", "不覆盖")
    print("结论:", "全部通过" if all(flags) else "有未通过项",
          "(" + " / ".join("%s %s" % (n, "OK" if f else "不过")
                           for n, f in zip(names, flags)) + ")")
    return 0 if all(flags) else 1


if __name__ == "__main__":
    sys.exit(main())
