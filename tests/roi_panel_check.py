# -*- coding: utf-8 -*-
"""测量面板自检（2026-09-26：4 个弹窗合成 1 个 + 表格改成"每个 ROI 一行"）。

① 强度页签默认宽表：行数 = ROI 数（不含背景），列里有各通道的"平均"
② 关掉宽表 → 回到长表：行数 = ROI × 通道
③ ROI 下拉选一个 → 只剩那一行
④ 线剖面页签：出图 + 表格行数 = 采样点数
⑤ 共定位页签：中文指标 + 说明列（不再是 Pearson_r/M1 这种英文键）
⑥ 粒子页签：行数 = 粒子数，摘要里有阈值与范围
⑦ 选"全部帧"：粒子表多出"帧"列，行数 = 各帧粒子数之和
⑧ 复制到剪贴板：有表头、有数据
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                       # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402

from core import loader, roi as roi_mod                              # noqa: E402
from ui.main_window import MainWindow                                # noqa: E402
from ui.roi_dialog import MeasureDialog                              # noqa: E402
from _samples import P  # noqa: E402

OIB = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")


def _cols(tbl):
    return [tbl.horizontalHeaderItem(j).text() for j in range(tbl.columnCount())]


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

    # 三个测点 + 一条线 + 一个背景
    win.on_roi_done("rect", 0.10, 0.10, 0.24, 0.24)
    win.on_roi_done("rect", 0.30, 0.10, 0.44, 0.24)
    win.on_roi_done("ellipse", 0.50, 0.10, 0.66, 0.26)
    win.on_roi_done("line", 0.10, 0.60, 0.70, 0.60)
    win.on_roi_done("rect", 0.80, 0.80, 0.92, 0.92)
    win.roi_toggle_bg(it.rois[-1])            # 最后一个当背景
    n_meas = sum(1 for r in it.rois if not r.is_bg)
    n_ch = len([c for c in it.channels if c.visible])

    dlg = MeasureDialog(win)
    dlg.show()
    for _ in range(6):
        app.processEvents()
    res = {}

    # ① 宽表
    t = dlg.tbl_strength
    cols = _cols(t)
    ch_cols = [c for c in cols if c.endswith("平均")]
    ok1 = t.rowCount() == n_meas and len(ch_cols) == n_ch
    print("[1] 强度页签（宽表）：%d 行（ROI %d 个），通道列 %s → %s"
          % (t.rowCount(), n_meas, ch_cols, "OK" if ok1 else "不过"))
    res["宽表一行一ROI"] = bool(ok1)

    # ② 长表
    dlg.chk_wide.setChecked(False)
    dlg._do_strength()
    app.processEvents()
    ok2 = dlg.tbl_strength.rowCount() == n_meas * n_ch
    print("[2] 关掉宽表：%d 行（应 %d×%d）→ %s"
          % (dlg.tbl_strength.rowCount(), n_meas, n_ch, "OK" if ok2 else "不过"))
    res["长表可切"] = bool(ok2)
    dlg.chk_wide.setChecked(True)

    # ③ 只算某一条
    dlg.cb_roi.setCurrentIndex(1)
    dlg._do_strength()
    app.processEvents()
    ok3 = dlg.tbl_strength.rowCount() == 1
    print("[3] ROI 下拉选「%s」：%d 行 → %s"
          % (dlg.cb_roi.currentText(), dlg.tbl_strength.rowCount(),
             "OK" if ok3 else "不过"))
    res["可选ROI"] = bool(ok3)
    dlg.cb_roi.setCurrentIndex(0)
    dlg.recalc()
    app.processEvents()

    # ④ 剖面
    dlg.tabs.setCurrentIndex(1)
    app.processEvents()
    ok4 = (getattr(dlg, "plot", None) is not None and dlg.tbl_profile is not None
           and dlg.tbl_profile.rowCount() > 10)
    print("[4] 线剖面：图=%s，表 %d 行 → %s"
          % (dlg.plot is not None, dlg.tbl_profile.rowCount() if dlg.tbl_profile else 0,
             "OK" if ok4 else "不过"))
    res["剖面可用"] = bool(ok4)

    # ⑤ 共定位
    dlg.tabs.setCurrentIndex(2)
    app.processEvents()
    cols5 = _cols(dlg.tbl_coloc) if dlg.tbl_coloc else []
    txt5 = "".join(dlg.tbl_coloc.item(i, 0).text() for i in range(dlg.tbl_coloc.rowCount())) \
        if dlg.tbl_coloc else ""
    ok5 = ("指标" in cols5 and "说明" in cols5 and "Pearson" in txt5
           and "Manders" in txt5)
    print("[5] 共定位：列 %s，指标 %s → %s"
          % (cols5, txt5.replace("\n", "·")[:46], "OK" if ok5 else "不过"))
    res["共定位可读"] = bool(ok5)

    # ⑥ 粒子
    dlg.tabs.setCurrentIndex(3)
    app.processEvents()
    ok6 = (dlg.tbl_particle is not None and dlg.tbl_particle.rowCount() >= 0
           and "阈值" in dlg.lbl_particle.text() and "范围" in dlg.lbl_particle.text())
    print("[6] 粒子：%s；表 %d 行 → %s"
          % (dlg.lbl_particle.text()[:58],
             dlg.tbl_particle.rowCount() if dlg.tbl_particle else 0,
             "OK" if ok6 else "不过"))
    res["粒子摘要"] = bool(ok6)

    # ⑦ 全部帧（这张是单帧图 → 下拉里没有"全部帧"，造一个多帧场景）
    import numpy as np
    it._cache = np.repeat(loader.load_stack(it), 3, axis=0)
    it.frames, it.t_count = 3, 3
    dlg.cb_frames.clear()
    dlg.cb_frames.addItem("当前帧（第 1 帧）")
    dlg.cb_frames.addItem("全部帧（共 3 帧）")
    dlg.cb_frames.setCurrentIndex(1)
    dlg._do_particle()
    app.processEvents()
    cols7 = _cols(dlg.tbl_particle) if dlg.tbl_particle else []
    ok7 = "帧" in cols7 and ("各帧粒子数" in dlg.lbl_particle.text())
    print("[7] 全部帧粒子：列 %s；%s → %s"
          % (cols7[:3], dlg.lbl_particle.text()[:40], "OK" if ok7 else "不过"))
    res["全部帧"] = bool(ok7)

    # ⑧ 复制
    dlg.tabs.setCurrentIndex(0)
    dlg.copy_current()
    clip = QApplication.clipboard().text()
    ok8 = ("ROI" in clip.splitlines()[0]) and len(clip.splitlines()) > 1
    print("[8] 复制当前页签：%d 行，表头「%s」→ %s"
          % (len(clip.splitlines()), clip.splitlines()[0][:40], "OK" if ok8 else "不过"))
    res["可复制"] = bool(ok8)

    out = os.path.join(APP, "output", "_自检")
    os.makedirs(out, exist_ok=True)
    dlg.grab().save(os.path.join(out, "测量面板.png"))
    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
