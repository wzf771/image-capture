# -*- coding: utf-8 -*-
"""ROI 结果表 / 线剖面对话框（规格书 4.8.5、4.8.8）。

线剖面**必须 QPainter 自绘**：开发机装了 matplotlib，但发布包构建时会删掉它
（附录 A），用 matplotlib 会"开发机正常、发出去就崩"。
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QLabel, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core import roi as roi_mod
from ui.widgets import BrutalButton


class PlotWidget(QWidget):
    """线剖面折线图：横轴 µm，多条曲线各自配色。"""

    def __init__(self, prof, colors, parent=None):
        super().__init__(parent)
        self.prof = prof
        self.colors = colors
        self.setMinimumHeight(220)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#141418"))
        prof = self.prof or {}
        um = prof.get("um") or []
        series = prof.get("series") or {}
        if not um or not series:
            p.end()
            return
        pad_l, pad_r, pad_t, pad_b = 46, 12, 14, 30
        w = max(10, self.width() - pad_l - pad_r)
        h = max(10, self.height() - pad_t - pad_b)
        vals = np.concatenate([np.asarray(v, np.float32) for v in series.values()])
        lo, hi = float(np.min(vals)), float(np.max(vals))
        if hi <= lo:
            hi = lo + 1.0
        x0, x1 = float(um[0]), float(um[-1])
        p.setPen(QPen(QColor("#3a3a44"), 1))
        for k in range(5):                       # 网格 + 纵轴刻度
            y = pad_t + h * k / 4.0
            p.drawLine(pad_l, int(y), pad_l + w, int(y))
            p.setPen(QColor("#9a96a8"))
            p.drawText(4, int(y) + 4, "%.0f" % (hi - (hi - lo) * k / 4.0))
            p.setPen(QPen(QColor("#3a3a44"), 1))
        p.setPen(QColor("#9a96a8"))
        p.drawText(pad_l, self.height() - 8, "0 µm")
        p.drawText(pad_l + w - 60, self.height() - 8, "%.1f µm" % x1)
        for name, ys in series.items():
            col = QColor(*self.colors.get(name, (255, 255, 255)))
            p.setPen(QPen(col, 1.6))
            pts = [QPointF(pad_l + w * (float(um[i]) - x0) / max(1e-9, (x1 - x0)),
                           pad_t + h * (1.0 - (float(ys[i]) - lo) / (hi - lo)))
                   for i in range(min(len(um), len(ys)))]
            for a, b in zip(pts[:-1], pts[1:]):
                p.drawLine(a, b)
        # 图例
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, self.font().pointSizeF() - 0.5))
        p.setFont(f)
        for i, name in enumerate(series):
            col = QColor(*self.colors.get(name, (255, 255, 255)))
            y = pad_t + 6 + i * 16
            p.setPen(QPen(col, 3))
            p.drawLine(pad_l + 8, y, pad_l + 26, y)
            p.setPen(QColor("#e8e6f0"))
            p.drawText(pad_l + 32, y + 4, name)
        p.end()


class ResultDialog(QDialog):
    """通用结果窗口：表格 + 可选曲线图；支持复制 TSV / 导出 CSV。"""

    def __init__(self, parent, title, rows, header_lines=(), prof=None, colors=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 620)
        self.rows = list(rows or [])
        self.header_lines = list(header_lines or [])
        self.prof = prof
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        if prof:
            lay.addWidget(PlotWidget(prof, colors or {}), 1)
        if self.rows:
            cols = []
            for r in self.rows:
                for k in r:
                    if k not in cols:
                        cols.append(k)
            t = QTableWidget(len(self.rows), len(cols))
            t.setHorizontalHeaderLabels(cols)
            for i, r in enumerate(self.rows):
                for j, c in enumerate(cols):
                    t.setItem(i, j, QTableWidgetItem(str(r.get(c, ""))))
            t.resizeColumnsToContents()
            lay.addWidget(t, 1)
        else:
            lab = QLabel("（没有数据）")
            lab.setObjectName("muted")
            lay.addWidget(lab)
        row = QHBoxLayout()
        row.addStretch(1)
        b_copy = BrutalButton("复制到剪贴板", compact=True)
        b_copy.clicked.connect(self.copy_tsv)
        b_csv = BrutalButton("导出 CSV", compact=True)
        b_csv.clicked.connect(self.save_csv)
        row.addWidget(b_copy)
        row.addWidget(b_csv)
        lay.addLayout(row)
        self.header_lines.append("# 显示：%d 行" % len(self.rows))

    def _text(self):
        from core.analysis import rows_to_csv
        return rows_to_csv(self.rows, self.header_lines[:-1])

    def copy_tsv(self):
        from PySide6.QtWidgets import QApplication
        cols = []
        for r in self.rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        lines = ["\t".join(cols)]
        for r in self.rows:
            lines.append("\t".join(str(r.get(c, "")) for c in cols))
        QApplication.clipboard().setText("\n".join(lines))

    def save_csv(self):
        p, _f = QFileDialog.getSaveFileName(self, "导出 CSV", "measure.csv",
                                            "CSV (*.csv)")
        if not p:
            return
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(self._text())
        self.setWindowTitle(self.windowTitle() + "  ·  已导出 " + os.path.basename(p))


def save_png_rgb(rgb, path):
    Image.fromarray(np.asarray(rgb, np.uint8)).save(path)


# ======================================================================
# 测量面板（2026-09-26：把原来"测量表/剖面/共定位/粒子"4 个弹窗合成一个，
# 并把结果表从"每个 ROI×通道一行"改成"每个 ROI 一行、通道展开成列"）
# ======================================================================
PLACEHOLDER = "—"          # 缺值统一显示这个，别让空格看起来像 0


def _fmt(v):
    """数字显示：整数不带小数点，浮点最多 4 位，空值显示 —。"""
    if v is None or v == "":
        return PLACEHOLDER
    if isinstance(v, float):
        return ("%.4f" % v).rstrip("0").rstrip(".") if abs(v) < 1e5 else "%.3g" % v
    return str(v)


def make_table(rows, parent=None):
    """list[dict] → 可排序、可多选复制的表格；列顺序按出现顺序。"""
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    t = QTableWidget(len(rows), len(cols), parent)
    t.setHorizontalHeaderLabels(cols)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(False)
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            it = QTableWidgetItem(_fmt(r.get(c)))
            it.setData(Qt.UserRole, r.get(c))
            t.setItem(i, j, it)
    # 排序必须在**填完之后**再开：一边填一边排序，Qt 会把行搬来搬去，
    # 后面 setItem 就落到别的行上，表格看着"有空行"（2026-09-26 截图抓到）
    t.setSortingEnabled(True)
    t.resizeColumnsToContents()
    t.verticalHeader().setDefaultSectionSize(22)
    return t


def to_wide(rows):
    """长表（ROI×通道×帧）→ 宽表：每个 ROI（×帧）一行，通道展开成列。"""
    out, order = {}, []
    for r in rows:
        key = (r.get("frame"), r.get("roi"))
        cur = out.get(key)
        if cur is None:
            cur = {}
            if "frame" in r:
                cur["帧"] = r["frame"]
            cur["ROI"] = r.get("roi")
            cur["面积 (px)"] = r.get("Area_px")
            cur["面积 (µm²)"] = r.get("Area_um2")
            for k in ("中心X_µm", "中心Y_µm", "中心X_px", "中心Y_px"):
                if k in r:
                    cur[k.replace("_µm", " (µm)").replace("_px", " (px)")] = r[k]
            out[key] = cur
            order.append(key)
        ch = r.get("channel") or "?"
        cur["%s 平均" % ch] = r.get("Mean")
        cur["%s SD" % ch] = r.get("SD")
        cur["%s 最大" % ch] = r.get("Max")
        if "Mean_bg_corr" in r:
            cur["%s 扣背景后" % ch] = r.get("Mean_bg_corr")
    return [out[k] for k in order]


class MeasureDialog(QDialog):
    """一个面板管完：强度 / 剖面 / 共定位 / 粒子。

    顶部固定"看哪个 ROI、哪几帧"，各页签自己再选需要的通道；
    所有数字仍然读原始位深数据（口径没变，只是换了呈现）。
    """

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("测量")
        self.setModal(True)
        self.resize(1000, 680)
        self._build()
        self.recalc()

    # -------------------------------------------------- 搭界面
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        self.lbl_ctx = QLabel("")
        self.lbl_ctx.setObjectName("muted")
        self.lbl_ctx.setWordWrap(True)
        lay.addWidget(self.lbl_ctx)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.cb_roi = QComboBox()
        self.cb_roi.setObjectName("field")
        self.cb_roi.setMinimumWidth(190)
        self.cb_frames = QComboBox()
        self.cb_frames.setObjectName("field")
        head.addWidget(QLabel("ROI"))
        head.addWidget(self.cb_roi)
        head.addSpacing(6)
        head.addWidget(QLabel("帧"))
        head.addWidget(self.cb_frames)
        head.addStretch(1)
        self.chk_wide = QCheckBox("每个 ROI 一行（通道展开成列）")
        self.chk_wide.setChecked(True)
        self.chk_wide.setToolTip("关掉就是老的长表：每个 ROI × 通道一行")
        head.addWidget(self.chk_wide)
        b = BrutalButton("重新计算", compact=True)
        b.clicked.connect(self.recalc)
        head.addWidget(b)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tab_strength = QWidget()
        self.tab_profile = QWidget()
        self.tab_coloc = QWidget()
        self.tab_particle = QWidget()
        for w, name in ((self.tab_strength, "强度"), (self.tab_profile, "线剖面"),
                        (self.tab_coloc, "共定位"), (self.tab_particle, "粒子计数")):
            self.tabs.addTab(w, name)
        v0 = QVBoxLayout(self.tab_strength)
        v0.setContentsMargins(0, 6, 0, 0)
        v0.setSpacing(6)
        self._build_profile_tab()
        self._build_coloc_tab()
        self._build_particle_tab()

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_copy = BrutalButton("复制当前页签", compact=True)
        self.btn_copy.clicked.connect(self.copy_current)
        self.btn_csv = BrutalButton("导出 CSV", compact=True)
        self.btn_csv.clicked.connect(self.save_csv)
        row.addWidget(self.btn_copy)
        row.addWidget(self.btn_csv)
        lay.addLayout(row)

    def _build_profile_tab(self):
        v = QVBoxLayout(self.tab_profile)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        self.lbl_profile = QLabel("")
        self.lbl_profile.setObjectName("muted")
        v.addWidget(self.lbl_profile)
        self.plot_host = QVBoxLayout()
        v.addLayout(self.plot_host, 1)
        self.tbl_profile = None

    def _build_coloc_tab(self):
        v = QVBoxLayout(self.tab_coloc)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel("通道 A"))
        self.cb_col_a = QComboBox()
        self.cb_col_a.setObjectName("field")
        self.cb_col_b = QComboBox()
        self.cb_col_b.setObjectName("field")
        row.addWidget(self.cb_col_a)
        row.addSpacing(8)
        row.addWidget(QLabel("通道 B"))
        row.addWidget(self.cb_col_b)
        row.addStretch(1)
        v.addLayout(row)
        self.lbl_coloc = QLabel("")
        self.lbl_coloc.setObjectName("muted")
        self.lbl_coloc.setWordWrap(True)
        v.addWidget(self.lbl_coloc)
        self.tbl_coloc = None
        v.addStretch(1)

    def _build_particle_tab(self):
        v = QVBoxLayout(self.tab_particle)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel("通道"))
        self.cb_par_ch = QComboBox()
        self.cb_par_ch.setObjectName("field")
        row.addWidget(self.cb_par_ch)
        row.addStretch(1)
        v.addLayout(row)
        self.lbl_particle = QLabel("")
        self.lbl_particle.setObjectName("muted")
        self.lbl_particle.setWordWrap(True)
        v.addWidget(self.lbl_particle)
        self.tbl_particle = None
        v.addStretch(1)

    # -------------------------------------------------- 数据
    def _fill_combos(self):
        win, it = self.win, self.win.cur_item
        chans = analysis_visible(win)
        for cb in (self.cb_col_a, self.cb_col_b, self.cb_par_ch):
            keep = cb.currentIndex()
            cb.blockSignals(True)
            cb.clear()
            for c in chans:
                cb.addItem(c.name or ("CH%d" % (c.index + 1)))
            cb.blockSignals(False)
            cb.setCurrentIndex(min(max(0, keep), max(0, len(chans) - 1)))
        if len(chans) > 1 and self.cb_col_b.currentIndex() == self.cb_col_a.currentIndex():
            self.cb_col_b.setCurrentIndex(1 if self.cb_col_a.currentIndex() == 0 else 0)
        rois = roi_mod.rois_of(it) if it else []
        keep = self.cb_roi.currentIndex()
        self.cb_roi.blockSignals(True)
        self.cb_roi.clear()
        self.cb_roi.addItem("整帧（不套 ROI）")
        for r in rois:
            self.cb_roi.addItem("%s%s" % (r.label, "（背景）" if r.is_bg else ""))
        self.cb_roi.blockSignals(False)
        self.cb_roi.setCurrentIndex(min(max(0, keep), max(0, len(rois))))
        n = int(getattr(it, "frames", 1) or 1) if it else 1
        keep2 = self.cb_frames.currentIndex()
        self.cb_frames.blockSignals(True)
        self.cb_frames.clear()
        self.cb_frames.addItem("当前帧（第 %d 帧）" % (int(self.win.frame) + 1))
        if n > 1:
            self.cb_frames.addItem("全部帧（共 %d 帧）" % n)
        self.cb_frames.blockSignals(False)
        self.cb_frames.setCurrentIndex(min(max(0, keep2), self.cb_frames.count() - 1))

    def _picked_roi(self):
        """ROI 下拉当前选的是哪个（None = 整帧）。"""
        it = self.win.cur_item
        rois = roi_mod.rois_of(it) if it else []
        i = self.cb_roi.currentIndex() - 1
        return rois[i] if 0 <= i < len(rois) else None

    def _frames(self):
        return "all" if self.cb_frames.currentIndex() == 1 else "current"

    def _context_text(self):
        it = self.win.cur_item
        if it is None:
            return "没有选中的图片"
        steps = "、".join({"register": "配准", "bg": "扣背景",
                           "drift": "漂移校正"}.get(s.kind, s.kind)
                          for s in (it.process or [])) or "无"
        bg = roi_mod.bg_roi(it)
        umpp = ("%.4g µm/px" % it.umpp) if it.umpp > 0 else "未标定"
        return ("%s · %s · %d 通道 · 处理链：%s · 背景 ROI：%s\n"
                "所有数字都读原始位深数据，显示区间/屏幕锐化不参与"
                % (it.name, umpp, len(it.channels or []), steps,
                   bg.label if bg is not None else "无"))

    def recalc(self):
        self._fill_combos()
        self.lbl_ctx.setText(self._context_text())
        self._do_strength()
        self._do_profile()
        self._do_coloc()
        self._do_particle()

    def _put(self, layout, attr, widget):
        """把页签里的旧控件换掉（Qt 里换内容要显式删，不然越堆越多）。"""
        old = getattr(self, attr, None)
        if old is not None:
            try:
                layout.removeWidget(old)
            except Exception:                                # noqa: BLE001
                pass
            old.setParent(None)
            old.deleteLater()
        setattr(self, attr, widget)
        if widget is not None:
            layout.addWidget(widget)
        return widget

    def _do_strength(self):
        roi = self._picked_roi()
        rows, _head = self.win.roi_rows_data(
            rois=None if roi is None else [roi],
            frames=self.win.measure_frames(self._frames()))
        self._rows_strength = list(rows)
        data = to_wide(rows) if self.chk_wide.isChecked() else rows
        self._put(self.tab_strength.layout(), "tbl_strength",
                  make_table(data, self.tab_strength))

    def _do_profile(self):
        it = self.win.cur_item
        lines = [r for r in (roi_mod.rois_of(it) if it else []) if r.kind == "line"]
        pick = self._picked_roi()
        line = pick if (pick is not None and pick.kind == "line") else (lines[0] if lines else None)
        if line is None:
            self.lbl_profile.setText("还没有直线 ROI：先用右栏的「直线」拖一条。")
            self._put(self.plot_host, "plot", None)
            self._put(self.tab_profile.layout(), "tbl_profile", None)
            return
        # 剖面按当前帧画（全部帧会变成一堆曲线，反而看不清）
        prof, _head = self.win.measure_profile(line, frame=self.win.frame)
        if not prof:
            self.lbl_profile.setText("取不到剖面数据。")
            return
        colors = {}
        for c in analysis_visible(self.win):
            colors[c.name or ("CH%d" % (c.index + 1))] = tuple(c.color)
        extra = "（按当前帧画）" if self._frames() == "all" else ""
        self.lbl_profile.setText("沿线「%s」共 %d 点 · 长 %.2f µm · 横轴是沿线的距离%s"
                                 % (line.label, prof.get("n", 0),
                                    prof.get("length_um", 0), extra))
        self._put(self.plot_host, "plot", PlotWidget(prof, colors, self.tab_profile))
        rows = [dict(位置_µm=_fmt(u), **{k: _fmt(v[i]) for k, v in prof["series"].items()})
                for i, u in enumerate(prof["um"])]
        self._put(self.tab_profile.layout(), "tbl_profile",
                  make_table(rows, self.tab_profile))

    def _do_coloc(self):
        roi = self._picked_roi()
        if roi is not None and roi.is_bg:
            roi = None
        res, _head = self.win.measure_coloc(roi, self.cb_col_a.currentIndex(),
                                            self.cb_col_b.currentIndex(),
                                            frame=self.win.frame)
        lay = self.tab_coloc.layout()
        if not res:
            self.lbl_coloc.setText("共定位需要两个不同的可见通道。")
            self._put(lay, "tbl_coloc", None)
            return
        a = self.cb_col_a.currentText()
        b = self.cb_col_b.currentText()
        rows = [
            dict(指标="Pearson 相关系数 r", 数值=res.get("Pearson_r"),
                 说明="两通道整体线性相关，-1~1；只看像不像，不看强度比例"),
            dict(指标="重叠系数 Overlap", 数值=res.get("Overlap"),
                 说明="归一化点积，对强信号更敏感"),
            dict(指标="Manders M1", 数值=res.get("M1"),
                 说明="%s 的强度里落在 %s 信号上的比例" % (a, b)),
            dict(指标="Manders M2", 数值=res.get("M2"),
                 说明="%s 的强度里落在 %s 信号上的比例" % (b, a)),
            dict(指标="阈值 A / B", 数值="%.1f / %.1f" % (res.get("thr_a", 0), res.get("thr_b", 0)),
                 说明="Otsu 自动阈值（原始计数），在 ROI 内算"),
            dict(指标="范围", 数值=("整帧" if roi is None else ("ROI " + roi.label)),
                 说明="共定位算在哪个范围里"),
            dict(指标="是否已配准", 数值=("是" if res.get("registered") else "否"),
                 说明=res.get("note") or "两通道已配准"),
        ]
        self.lbl_coloc.setText("没配准就先在「处理」卡片里做通道配准，否则这组数不可靠。"
                               if not res.get("registered") else "")
        self._put(lay, "tbl_coloc", make_table(rows, self.tab_coloc))

    def _do_particle(self):
        it = self.win.cur_item
        roi = self._picked_roi()
        if roi is not None and (roi.is_bg or roi.kind == "line"):
            roi = None
        lay = self.tab_particle.layout()
        got = []
        for fr in self.win.measure_frames(self._frames()):
            res, _head = self.win.measure_particles(roi, self.cb_par_ch.currentIndex(),
                                                   frame=fr)
            if res:
                got.append((fr, res))
        res = got[0][1] if got else {}
        if not res:
            self.lbl_particle.setText("没有可用的通道。")
            self._put(lay, "tbl_particle", None)
            return
        umpp = float(getattr(it, "umpp", 0.0) or 0.0)
        area_min = int(self.win.sp_particle_min.value())
        where = "整帧" if roi is None else ("ROI " + roi.label)
        if len(got) > 1:
            self.lbl_particle.setText(
                "各帧粒子数：%s · 面积下限 %d px · 范围 %s（阈值每帧各自按 Otsu 算）"
                % ("、".join(str(r.get("count", 0)) for _f, r in got), area_min, where))
        else:
            self.lbl_particle.setText(
                "共 %d 个粒子 · 阈值 %.1f（Otsu，原始计数）· 面积下限 %d px · 范围 %s"
                % (res.get("count", 0), res.get("thr", 0), area_min, where))
        rows = []
        for fr, r in got:
            for i, p in enumerate(r.get("particles") or []):
                rows.append(dict(
                    粒子=i + 1,
                    **({"帧": fr + 1} if len(got) > 1 else {}),
                    面积_px=p.get("area_px"),
                    面积_µm2=(round(p.get("area_px", 0) * umpp * umpp, 4) if umpp > 0 else ""),
                    中心X_µm=(round(p.get("cx", 0) * umpp, 3) if umpp > 0 else ""),
                    中心Y_µm=(round(p.get("cy", 0) * umpp, 3) if umpp > 0 else ""),
                    平均强度=p.get("mean")))
        self._put(lay, "tbl_particle", make_table(rows, self.tab_particle))

    # -------------------------------------------------- 导出
    def _current_rows(self):
        i = self.tabs.currentIndex()
        if i == 0:
            rows = getattr(self, "_rows_strength", [])
            return (to_wide(rows) if self.chk_wide.isChecked() else rows), "强度"
        if i == 1:
            rows, head = self.win.roi_rows_data()
            prof, _h = self.win.roi_profile_data()
            extra = [dict(位置_µm=u, **{k: v[i] for k, v in (prof.get("series") or {}).items()})
                     for i, u in enumerate(prof.get("um") or [])]
            return extra, "线剖面"
        if i == 2:
            t = getattr(self, "tbl_coloc", None)
            return _table_rows(t), "共定位"
        t = getattr(self, "tbl_particle", None)
        return _table_rows(t), "粒子计数"

    def copy_current(self):
        from PySide6.QtWidgets import QApplication
        rows, name = self._current_rows()
        cols = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        txt = "\n".join(["\t".join(cols)] +
                        ["\t".join(str(r.get(c, "")) for c in cols) for r in rows])
        QApplication.clipboard().setText(txt)
        self.win.lbl_status.setText("已复制「%s」的 %d 行到剪贴板" % (name, len(rows)))

    def save_csv(self):
        from core import analysis as ana
        import paths
        rows, name = self._current_rows()
        base = self.win.settings.out_dir or paths.OUTPUT_DIR
        p, _f = QFileDialog.getSaveFileName(
            self, "导出 %s" % name,
            os.path.join(base, "roi_%s.csv" % name),
            "CSV (*.csv)")
        if not p:
            return
        head = ana.csv_header(self.win.cur_item,
                              extra=["导出页签：%s" % name,
                                     "ROI 下拉：%s" % self.cb_roi.currentText(),
                                     "帧：%s" % self.cb_frames.currentText()])
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(ana.rows_to_csv(rows, head))
        self.win.lbl_status.setText("已导出：%s（utf-8-sig，Excel 直接打开）" % p)


def analysis_visible(win):
    from core import analysis as ana
    return ana.visible_channels(win.cur_item) if win.cur_item else []


def _table_rows(tbl):
    """QTableWidget → list[dict]（导出/复制用）。"""
    if tbl is None:
        return []
    cols = [tbl.horizontalHeaderItem(j).text() for j in range(tbl.columnCount())]
    out = []
    for i in range(tbl.rowCount()):
        out.append({c: (tbl.item(i, j).text() if tbl.item(i, j) is not None else "")
                    for j, c in enumerate(cols)})
    return out
