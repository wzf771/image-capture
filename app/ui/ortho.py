# -*- coding: utf-8 -*-
"""正交视图（XZ / YZ 剖面）浮动窗口 —— 规格书 P1-5 4.3.2。

为什么是独立浮动窗口而不是右栏卡片：剖面要的是**正方形区域**，
挤在右栏里看不出物理比例（Z 步进 0.35 µm 对 XY 0.1 µm/px，长宽比可能差几十倍）。

显示规则（规格书 4.3.2）：
  · L 方向（沿线）用 umpp，Z 方向用 z_step_um，换算成 µm 后再定缩放
  · **Z 步进未知（0）时不做物理比例**，改成等距拉伸，并在图下方写明"未按比例"
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from core import loader, render, zproj
from ui.widgets import BrutalButton


class OrthoCanvas(QWidget):
    """画 (Z, L) 剖面：滚轮放大，双击复位。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._rgb = None
        self.zoom = 1.0
        self.aspect_note = ""

    def set_slab_rgb(self, rgb, aspect_note=""):
        self._rgb = None if rgb is None else np.ascontiguousarray(rgb)
        self.aspect_note = aspect_note
        self.update()

    def wheelEvent(self, ev):
        k = 1.15 if ev.angleDelta().y() > 0 else 0.87
        self.zoom = min(8.0, max(0.2, self.zoom * k))
        self.update()

    def mouseDoubleClickEvent(self, _ev):
        self.zoom = 1.0
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        if self._rgb is None:
            p.end()
            return
        h, w = self._rgb.shape[:2]
        img = QImage(self._rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        pm = QPixmap.fromImage(img)
        scale = min(self.width() / float(w), self.height() / float(h)) * self.zoom
        tw, th = max(8, int(w * scale)), max(8, int(h * scale))
        p.drawPixmap((self.width() - tw) // 2, (self.height() - th) // 2, tw, th, pm)
        if self.aspect_note:
            p.fillRect(0, self.height() - 22, self.width(), 22, Qt.black)
            p.setPen(Qt.yellow)
            p.drawText(6, self.height() - 6, self.aspect_note)
        p.end()


class OrthoWindow(QWidget):
    """独立浮动窗口：显示当前取样线的 (Z, L) 剖面。"""

    def __init__(self, win):
        super().__init__(None, Qt.Window)
        self.win = win
        self.setWindowTitle("正交视图 · XZ / YZ 剖面")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.btn_line = BrutalButton("在主图上画取样线", compact=True)
        self.btn_line.setToolTip("点一下，然后在主图里拉一条直线（横线 = XZ，竖线 = YZ）")
        self.btn_line.clicked.connect(self.pick_line)
        self.cb_ch = QComboBox()
        self.cb_ch.currentIndexChanged.connect(lambda _i: self.refresh())
        self.btn_save = BrutalButton("导出 PNG", compact=True)
        self.btn_save.clicked.connect(self.save_png)
        top.addWidget(self.btn_line)
        top.addWidget(self.cb_ch, 1)
        top.addWidget(self.btn_save)
        lay.addLayout(top)
        self.lbl_info = QLabel("还没有取样线")
        self.lbl_info.setObjectName("muted")
        self.lbl_info.setWordWrap(True)
        lay.addWidget(self.lbl_info)
        self.canvas = OrthoCanvas()
        lay.addWidget(self.canvas, 1)
        self.line = None                     # (x0, y0, x1, y1) 原图像素坐标
        self.meta = {}

    # ---- 取样线
    def set_line_px(self, x0, y0, x1, y1):
        self.line = (int(x0), int(y0), int(x1), int(y1))
        self.refresh()

    def pick_line(self):
        self.win.start_ortho_pick(self)

    def default_line(self):
        """没画线时给一条过中心的横线：打开就能看到东西。"""
        it = self.win.cur_item
        if it is None:
            return None
        y = it.height // 2
        return (0, y, it.width - 1, y)

    def _channels(self):
        return list(getattr(self.win.cur_item, "channels", []) or [])

    def build_rgb(self):
        it = self.win.cur_item
        if it is None:
            return None, {}
        line = self.line or self.default_line()
        if line is None:
            return None, {}
        ch = None
        if self.cb_ch.currentIndex() > 0:
            ch = self.cb_ch.currentIndex() - 1
        slab, meta = zproj.ortho_slab(loader.load_stack(it), it,
                                      line[0], line[1], line[2], line[3],
                                      ch=ch, t=self.win.cur_t)
        if ch is not None:
            slab = slab[None]                # 单通道也当 (1, Z, L) 交给 compose
        rgb = render.compose(slab, self._channels())
        # 物理比例：每层 z_step µm、每像素 umpp µm → 一层该显示成几行 = z_step / umpp
        # （反过来写会把长宽比整个翻过来：100 µm 宽 × 7 µm 深会被画成又高又窄）
        if meta.get("scaled") and meta.get("step_xy") and meta.get("step_z"):
            k = float(meta["step_z"]) / float(meta["step_xy"])
            rows = max(1, int(round(rgb.shape[0] * k)))
            rgb = np.asarray(Image.fromarray(rgb).resize((rgb.shape[1], rows),
                                                         Image.NEAREST))
            meta["display_ratio"] = k
        return rgb, meta

    def refresh(self):
        rgb, meta = self.build_rgb()
        self.meta = meta or {}
        if rgb is None:
            self.lbl_info.setText("还没有可显示的图（先导入一张有多层 Z 的图）")
            self.canvas.set_slab_rgb(None)
            return
        note = "" if meta.get("scaled") else "Z 步进未知，未按比例显示"
        self.canvas.set_slab_rgb(rgb, note)
        line = self.line or self.default_line() or (0, 0, 0, 0)
        kind = "XZ" if abs(line[2] - line[0]) >= abs(line[3] - line[1]) else "YZ"
        if meta.get("scaled"):
            tail = (" · 深度 %.2f µm（每层显示成 %.2f 行）"
                    % (meta.get("depth_um", 0.0), meta.get("display_ratio", 1.0)))
        else:
            tail = " · " + note
        self.lbl_info.setText(
            "%s 剖面 · 取样线 (%d,%d)→(%d,%d) px · 沿线 %.1f µm · %d 层%s"
            % (kind, line[0], line[1], line[2], line[3], meta.get("length_um", 0.0),
               meta.get("n_z", 0), tail))

    def sync_channels(self):
        self.cb_ch.blockSignals(True)
        self.cb_ch.clear()
        self.cb_ch.addItem("全部可见通道")
        for c in self._channels():
            self.cb_ch.addItem(c.name or ("CH%d" % (c.index + 1)))
        self.cb_ch.blockSignals(False)

    # ---- 导出
    def save_png(self):
        rgb, meta = self.build_rgb()
        if rgb is None:
            return
        base = self.win.settings.out_dir or (
            os.path.dirname(self.win.items[0].path) if self.win.items else os.getcwd())
        p, _f = QFileDialog.getSaveFileName(self, "导出正交视图",
                                            os.path.join(base, "ortho.png"),
                                            "PNG (*.png)")
        if not p:
            return
        im = Image.fromarray(rgb)
        d = ImageDraw.Draw(im)
        try:
            f = ImageFont.truetype(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "assets", "arial.ttf"), 14)
        except Exception:                              # noqa: BLE001
            f = ImageFont.load_default()
        # 两根标尺：横的按沿线 µm，竖的按深度 µm（规格书 4.3.2 的"带两轴标尺"）
        umpp = float(meta.get("step_xy") or 0.0)
        zs = float(meta.get("step_z") or 0.0)
        if umpp > 0:
            bar = max(1.0, float(round(meta.get("length_um", 0.0) / 4.0, 1)))
            px = max(4, int(round(bar / umpp)))
            y = im.height - 14
            d.line([(8, y), (8 + px, y)], fill=(255, 255, 255), width=3)
            d.text((8, y - 18), "%g µm" % bar, fill=(255, 255, 255), font=f)
        if zs > 0:
            bar_z = max(zs, float(round(meta.get("depth_um", 0.0) / 2.0, 2)))
            pxz = max(4, int(round(bar_z / zs * float(meta.get("display_ratio") or 1.0))))
            x = im.width - 14
            d.line([(x, im.height - 8), (x, max(2, im.height - 8 - pxz))],
                   fill=(255, 255, 255), width=3)
            d.text((max(2, x - 52), max(2, im.height - 26 - pxz)), "%g µm" % bar_z,
                   fill=(255, 255, 255), font=f)
        im.save(p)
        self.win.lbl_status.setText("正交视图已导出：%s" % p)
