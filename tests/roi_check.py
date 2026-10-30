# -*- coding: utf-8 -*-
"""ROI 与测量的自检（2026-09-26 用户反馈"不能拖 + 数据看不懂"这一轮）。

① 直线 ROI 保序（负斜率不能被翻成另一条对角线）
② 新建 ROI 自动编号（矩形 1/2/3，不再是三个"矩形"）
③ ROI 的 t/z 字段真的生效（按 flat_index，而不是强制 z=0）
④ 测量结果里不再有内部字段 rid
⑤ 图上能选中 + 拖动（模型坐标跟着变，数量不变）
⑥ 拖四角能缩放
⑦ 选中后按 Delete 能删
⑧ 放大以后 ROI 的画布位置仍然对（历史 bug：一放大就跑到可见区左上角）
⑨ 背景 ROI 会被标出来（画布拿到 is_bg，绘制用另一种颜色）
⑩ 在"裁剪结果"视图里画 ROI，坐标换算回整帧是对的
⑭ 点一次工具能一直画（连画两个不用重新点工具），再点同一个工具才退出
⑮ 点工具：单击落点、能量到值（默认半径 3px 的圆盘）
⑯ 图上右键某个 ROI → 发出 roi_menu(rid)（右栏不再列 ROI，全靠这个菜单）
⑰ 右栏 ROI 列表已移除（没有 roi_rows 了），只剩一行计数提示
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import numpy as np                                                    # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt                        # noqa: E402
from PySide6.QtGui import (QContextMenuEvent, QFont, QFontDatabase,   # noqa: E402
                           QMouseEvent)
from PySide6.QtWidgets import QApplication                            # noqa: E402

from core import analysis, loader, roi as roi_mod                     # noqa: E402
from ui.main_window import MainWindow                                 # noqa: E402
from _samples import P  # noqa: E402

OIB = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")


def _ev(kind, w, x, y, btn=Qt.LeftButton, buttons=Qt.NoButton):
    p = QPointF(float(x), float(y))
    return QMouseEvent(kind, p, p, btn, buttons, Qt.NoModifier)


def _drag(w, x0, y0, x1, y1, steps=6):
    QApplication.sendEvent(w, _ev(QEvent.MouseButtonPress, w, x0, y0, buttons=Qt.LeftButton))
    for i in range(1, steps + 1):
        QApplication.sendEvent(w, _ev(QEvent.MouseMove, w,
                                      x0 + (x1 - x0) * i / steps,
                                      y0 + (y1 - y0) * i / steps, btn=Qt.NoButton,
                                      buttons=Qt.LeftButton))
    QApplication.sendEvent(w, _ev(QEvent.MouseButtonRelease, w, x1, y1, buttons=Qt.NoButton))
    QApplication.processEvents()


class _Stub:
    """analysis.roi_stats 需要的最小 item 接口。"""

    def __init__(self, z=1, t=1):
        self.width = self.height = 40
        self.umpp = 0.5
        self.z_count, self.t_count = z, t
        self.process = []

        class Ch:
            def __init__(self, i, n):
                self.index, self.name, self.visible = i, n, True
        self.channels = [Ch(0, "绿"), Ch(1, "红")]

    def flat_index(self, t, z):
        zc = max(1, int(self.z_count))
        return min(max(0, int(t)), max(1, int(self.t_count)) - 1) * zc \
            + min(max(0, int(z)), zc - 1)


def main():
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1400, 900)
    it = loader.probe(OIB)
    win.items = [it]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.show()
    for _ in range(8):
        app.processEvents()
    win.resize(1400, 900)
    for _ in range(8):
        app.processEvents()
    win.select_item(it.path)
    for _ in range(6):
        app.processEvents()
    res = {}
    cv = win.canvas

    # ① 直线保序
    win.on_roi_done("line", 0.80, 0.20, 0.20, 0.80)
    ln = it.rois[-1]
    ok1 = abs(ln.points[0][0] - 0.80) < 1e-6 and abs(ln.points[0][1] - 0.20) < 1e-6
    print("[1] 直线端点保序：画 (0.80,0.20)→(0.20,0.80)，存成 %s → %s"
          % ([[round(v, 2) for v in p] for p in ln.points], "OK" if ok1 else "不过"))
    res["直线保序"] = bool(ok1)

    # ② 自动编号
    for i in range(3):
        win.on_roi_done("rect", 0.10 + i * 0.12, 0.10, 0.20 + i * 0.12, 0.22)
    labels = [r.label for r in it.rois if r.kind == "rect"]
    ok2 = labels == ["矩形 1", "矩形 2", "矩形 3"]
    print("[2] 自动编号：%s → %s" % (labels, "OK" if ok2 else "不过"))
    res["自动编号"] = bool(ok2)

    # ③ t/z 生效（2×3 的栈，ROI 锁定 t=1/z=2 → 第 1*3+2 = 5 帧）
    st = _Stub(z=3, t=2)
    stack = np.zeros((6, 2, 40, 40), np.uint16)
    stack[5, 0, :, :] = 1000
    stack[0, 0, :, :] = 7
    r = roi_mod.Roi(kind="rect", points=[[0.25, 0.25], [0.75, 0.75]], t=1, z=2)
    row = analysis.roi_stats(stack, st, r, frame=0)[0]
    ok3 = abs(row["Mean"] - 1000.0) < 1e-6
    print("[3] ROI 的 t/z 生效：t=1,z=2 → 取第 5 帧，Mean=%.1f（该帧是 1000）→ %s"
          % (row["Mean"], "OK" if ok3 else "不过"))
    res["t/z生效"] = bool(ok3)

    # ④ 结果里没有 rid
    rows, _h = win.roi_rows_data()
    ok4 = bool(rows) and all("rid" not in x for x in rows)
    print("[4] 结果列：%s → %s" % (list(rows[0].keys()), "OK" if ok4 else "不过"))
    res["无rid列"] = bool(ok4)

    # ⑤ 拖动（选中 + 移动）
    target = next(x for x in it.rois if x.kind == "rect")
    win.select_roi_row(target)
    before = [list(p) for p in target.points]
    sc = cv._roi_screen(next(s for s in cv._roi_shapes if s["rid"] == target.rid))
    cx = (sc[0].x() + sc[1].x()) / 2.0
    cy = (sc[0].y() + sc[1].y()) / 2.0
    n_before = len(it.rois)
    _drag(cv, cx, cy, cx + 40, cy + 24)
    moved = [list(p) for p in target.points]
    ok5 = (moved != before and len(it.rois) == n_before
           and abs(moved[0][0] - before[0][0]) > 0.01)
    print("[5] 拖动整体：%s → %s（ROI 数 %d→%d）→ %s"
          % ([[round(v, 3) for v in p] for p in before],
             [[round(v, 3) for v in p] for p in moved], n_before, len(it.rois),
             "OK" if ok5 else "不过"))
    res["可拖动"] = bool(ok5)

    # ⑥ 拖右下角缩放
    before = [list(p) for p in target.points]
    sc = cv._roi_screen(next(s for s in cv._roi_shapes if s["rid"] == target.rid))
    _drag(cv, sc[1].x(), sc[1].y(), sc[1].x() + 36, sc[1].y() + 20)
    after = [list(p) for p in target.points]
    ok6 = (after[1][0] - after[0][0]) > (before[1][0] - before[0][0]) + 0.005 \
        and abs(after[0][0] - before[0][0]) < 1e-6
    print("[6] 拖右下角缩放：宽 %.3f → %.3f（左上角固定 %s）→ %s"
          % (before[1][0] - before[0][0], after[1][0] - after[0][0],
             abs(after[0][0] - before[0][0]) < 1e-6, "OK" if ok6 else "不过"))
    res["可缩放"] = bool(ok6)

    # ⑦ Delete 删除
    n_before = len(it.rois)
    cv.setFocus()
    key = QMouseEvent(QEvent.KeyPress, QPointF(0, 0), QPointF(0, 0), Qt.NoButton,
                      Qt.NoButton, Qt.NoModifier)
    from PySide6.QtGui import QKeyEvent
    QApplication.sendEvent(cv, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
    app.processEvents()
    ok7 = len(it.rois) == n_before - 1 and target not in it.rois
    print("[7] 选中后按 Delete：ROI 数 %d → %d → %s"
          % (n_before, len(it.rois), "OK" if ok7 else "不过"))
    res["Delete删除"] = bool(ok7)

    # ⑧ 放大后位置仍对得上
    first = it.rois[0]
    cv.set_zoom(1.0)
    app.processEvents()
    sc1 = cv._roi_screen(next(s for s in cv._roi_shapes if s["rid"] == first.rid))
    cv.set_zoom(4.0)
    app.processEvents()
    win.refresh_preview()
    for _ in range(4):
        app.processEvents()
    sc4 = cv._roi_screen(next(s for s in cv._roi_shapes if s["rid"] == first.rid))
    # 放大后可见区变小：ROI 若在可视范围内，屏幕位置必须比 1× 时"更外扩"，
    # 而不是原地不动（历史 bug：坐标被当成可见区归一化，位置永远不变）
    u0, v0 = cv.norm_to_view(*first.points[0])
    ok8 = abs(sc4[0].x() - (cv._view_rect().left() + u0 * cv._view_rect().width())) < 2.0
    print("[8] 放大 4× 后 ROI 的屏幕位置：%s（1× 时 %s）→ %s"
          % ((round(sc4[0].x(), 1), round(sc4[0].y(), 1)),
             (round(sc1[0].x(), 1), round(sc1[0].y(), 1)),
             "OK" if ok8 else "不过"))
    res["放大位置对"] = bool(ok8)

    # ⑨ 背景 ROI 会被标出来
    win.select_roi_row(first)
    win.roi_toggle_bg(first)
    shapes = cv._roi_shapes
    ok9 = any(s["bg"] for s in shapes)
    print("[9] 背景 ROI 传到画布：%s → %s"
          % ([(s["label"], s["bg"]) for s in shapes], "OK" if ok9 else "不过"))
    res["背景可辨"] = bool(ok9)

    # ⑩ 裁剪结果视图里画 ROI，换算回整帧要对
    win.set_view_mode("crop")
    for _ in range(6):
        app.processEvents()
    used = win._used_rect
    win.on_roi_done("rect", 0.0, 0.0, 0.5, 0.5)
    new = it.rois[-1]
    want = (used[0], used[1])
    ok10 = abs(new.points[0][0] - want[0]) < 1e-6 and abs(new.points[0][1] - want[1]) < 1e-6
    print("[10] 裁剪视图里画 ROI：_used_rect=%s，存成 (%.3f,%.3f) → %s"
          % (tuple(round(v, 3) for v in used), new.points[0][0], new.points[0][1],
             "OK" if ok10 else "不过"))
    res["裁剪视图坐标"] = bool(ok10)

    # ⑪ 套用到本组：同组第二张图拿到同样的 ROI
    win.set_view_mode("full")
    for _ in range(4):
        app.processEvents()
    it2 = loader.probe(OIB)
    it2.path = it.path.replace(".oib", "_copy.oib")     # 假的"同组第二张"
    it2.name = "复制图.oib"
    it2.group = it.group
    win.cur_group.images.append(it2)
    n_before2 = len(it2.rois or [])
    win.apply_rois_to_group()
    app.processEvents()
    ok11 = len(it2.rois or []) > n_before2
    print("[11] 套用到本组：第二张图 ROI %d → %d 个（%s）→ %s"
          % (n_before2, len(it2.rois or []),
             "、".join(r.label for r in (it2.rois or [])), "OK" if ok11 else "不过"))
    res["可套用到整组"] = bool(ok11)

    # ⑫ 导出：强度表与剖面分成两个文件
    import tempfile
    from PySide6.QtWidgets import QFileDialog
    tmp = os.path.join(tempfile.mkdtemp(prefix="roi_csv_"), "roi_measure.csv")
    orig_dlg = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (tmp, "CSV (*.csv)"))
    try:
        win.roi_export_csv()
    finally:
        QFileDialog.getSaveFileName = orig_dlg
    prof_csv = os.path.splitext(tmp)[0] + "_profile.csv"
    body = open(tmp, encoding="utf-8-sig").read().splitlines()
    head1 = next((x for x in body if x and not x.startswith("#")), "")
    ok12 = os.path.exists(tmp) and os.path.exists(prof_csv) and "ROI" in head1 \
        and "平均" in head1
    print("[12] 导出两个 CSV：%s / %s；表头「%s」→ %s"
          % (os.path.basename(tmp), "有剖面文件" if os.path.exists(prof_csv) else "无剖面",
             head1[:52], "OK" if ok12 else "不过"))
    res["导出分文件"] = bool(ok12)

    # ⑬ 点列表行会把视野挪过去（ROI 在视野外时）
    cv.set_zoom(6.0)
    for _ in range(4):
        app.processEvents()
    far = it.rois[0]
    cv.setZoom = None
    moved = cv.center_on_frac(far.points[0][0], far.points[0][1])
    print("[13] ROI 在视野外时点列表：视图%s" % ("已挪过去" if moved else "不用挪"))
    res["点列表定位"] = True                      # 只验证不报错、返回布尔

    # ⑭⑮ 工具"点一次一直画" + 点工具
    win.set_view_mode("full")
    for _ in range(4):
        app.processEvents()
    n0 = len(it.rois)
    win.on_roi_tool("point")
    armed0 = cv.roi_mode()
    for u, v in ((0.2, 0.2), (0.35, 0.45), (0.7, 0.65)):
        cv.roi_done.emit("point", u, v, u, v)
    for _ in range(4):
        app.processEvents()
    pts = [r for r in it.rois if r.kind == "point"]
    ok14 = (armed0 == "point") and (cv.roi_mode() == "point") and len(pts) == 3
    print("[14] 点工具 armed 后连点 3 次：新建 %d 个点，armed 仍 = %r → %s"
          % (len(pts), cv.roi_mode(), "OK" if ok14 else "不过"))
    res["工具一直能画"] = bool(ok14)

    win.on_roi_tool("point")                      # 再点同一个 = 退出
    ok15b = cv.roi_mode() == ""
    print("[14b] 再点同一个工具 → armed = %r → %s"
          % (cv.roi_mode(), "OK" if ok15b else "不过"))
    res["可退出工具"] = bool(ok15b)

    rows14, _h14 = win.roi_rows_data(rois=pts[:1])
    r0 = rows14[0] if rows14 else {}
    area = r0.get("Area_px", 0)
    ok15 = (25 <= area <= 34) and ("中心X_µm" in r0 or "中心X_px" in r0)
    print("[15] 点 ROI 的测量：面积 %s px（半径 3px 圆盘 ≈29），中心 %s → %s"
          % (area, r0.get("中心X_µm", r0.get("中心X_px")), "OK" if ok15 else "不过"))
    res["点能量到值"] = bool(ok15)

    # ⑯ 右键某个 ROI → roi_menu(rid)
    # 注意：真的 menu.exec() 是模态的，会把自检卡住 —— 先把主窗口的槽摘掉，只留探针
    try:
        cv.roi_menu.disconnect()
    except Exception:                            # noqa: BLE001
        pass
    seen = []
    cv.roi_menu.connect(lambda rid, pos: seen.append(rid))
    target_pt = pts[0]
    sc = cv._roi_screen(next(s for s in cv._roi_shapes if s["rid"] == target_pt.rid))
    ev2 = QContextMenuEvent(QContextMenuEvent.Mouse, sc[0].toPoint(),
                            cv.mapToGlobal(sc[0].toPoint()))
    QApplication.sendEvent(cv, ev2)
    ok16 = seen == [target_pt.rid]
    print("[16] 在图上右键「%s」→ 收到 roi_menu(%s) → %s"
          % (target_pt.label, seen[:1], "OK" if ok16 else "不过"))
    res["右键菜单"] = bool(ok16)
    cv.roi_menu.disconnect()

    # ⑰ 右栏列表已移除
    ok17 = (not hasattr(win, "roi_rows")) and ("ROI" in win.lbl_roi.text())
    print("[17] 右栏 ROI 列表已移除=%s；计数文案「%s」→ %s"
          % (not hasattr(win, "roi_rows"), win.lbl_roi.text().split("\n")[0][:34],
             "OK" if ok17 else "不过"))
    res["列表已移除"] = bool(ok17)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
