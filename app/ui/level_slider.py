# -*- coding: utf-8 -*-
"""通道色阶轨道（照 WorkBuddy 的 channel-slider-handoff.md 移植到 Qt）。

一条 38px 高的轨道：
  · 底：主题的输入框底色 + 内描边
  · 直方图：当前通道**真实像素分布**（对数归一化，92 个 bin，颜色 = 通道色、透明度 .42）
  · 选中区间：通道色 13% 填充
  · 区间外：白色蒙版压暗
  · 两个手柄：11×24 白底、1.5px 通道色边；悬停变宽 + 光环

交互照原文档：拖手柄、点轨道就近吸附、方向键 ±1 / Shift ±20、Home/End。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui import theme


def _as_color(spec):
    """接受 '#rrggbb' / 'rgb(r,g,b)' / QColor / (r,g,b)。"""
    if isinstance(spec, QColor):
        return QColor(spec)
    if isinstance(spec, (tuple, list)) and len(spec) >= 3:
        return QColor(int(spec[0]), int(spec[1]), int(spec[2]))
    txt = str(spec).strip()
    if txt.lower().startswith("rgb"):
        nums = [int(v) for v in txt[txt.find("(") + 1: txt.rfind(")")].replace(";", ",").split(",")[:3]]
        if len(nums) == 3:
            return QColor(nums[0], nums[1], nums[2])
    return QColor(txt)

PAD = 7
TRACK_H = 38
HANDLE_W, HANDLE_H = 11.0, 24.0
HANDLE_W_HOT = 13.0


class LevelSlider(QWidget):
    valuesChanged = Signal(int, int)

    def __init__(self, parent=None, color="#6d7982"):
        super().__init__(parent)
        self._min, self._max = 0, 255
        self._lo, self._hi = 0, 255
        self._color = _as_color(color)
        self._hist = None            # list[float] 0..1，长度 92
        self._hot = None             # "lo" / "hi"
        self._drag = None
        self.setFixedHeight(TRACK_H + 2)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    # ------------------------------------------------------------ API
    def setColor(self, color):                       # noqa: N802
        self._color = _as_color(color)
        self.update()

    def setHistogram(self, bins):                    # noqa: N802
        """bins：长度任意、已归一化到 0..1 的序列；None = 不画直方图。"""
        self._hist = list(bins) if bins else None
        self.update()

    def setRange(self, lo, hi):                      # noqa: N802
        self._min, self._max = int(lo), max(int(lo) + 1, int(hi))
        self.update()

    def setValues(self, lo, hi):                     # noqa: N802
        self._lo = max(self._min, min(int(lo), self._max - 1))
        self._hi = min(self._max, max(int(hi), self._lo + 1))
        self.update()

    def values(self):
        return self._lo, self._hi

    def _emit(self):
        self.valuesChanged.emit(self._lo, self._hi)

    # ------------------------------------------------------------ 几何
    def _track(self) -> QRectF:
        return QRectF(0, 0, self.width(), TRACK_H)

    def _x(self, v):
        t = self._track()
        span = max(1.0, t.width() - 2 * PAD)
        return PAD + (v - self._min) / float(self._max - self._min) * span

    def _v(self, x):
        t = self._track()
        span = max(1.0, t.width() - 2 * PAD)
        p = (x - PAD) / span
        p = max(0.0, min(1.0, p))
        return int(round(self._min + p * (self._max - self._min)))

    # ------------------------------------------------------------ 交互
    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        x = ev.position().x()
        d_lo, d_hi = abs(x - self._x(self._lo)), abs(x - self._x(self._hi))
        if min(d_lo, d_hi) <= 14:
            self._drag = "lo" if d_lo <= d_hi else "hi"
        else:
            v = self._v(x)
            self._drag = "lo" if abs(v - self._lo) <= abs(v - self._hi) else "hi"
        self._apply(x)
        try:
            self.grabMouse()
        except Exception:                             # noqa: BLE001
            pass

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        if self._drag:
            self._apply(x)
            return
        d_lo, d_hi = abs(x - self._x(self._lo)), abs(x - self._x(self._hi))
        hot = ("lo" if d_lo <= d_hi else "hi") if min(d_lo, d_hi) <= 14 else None
        if hot != self._hot:
            self._hot = hot
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag:
            self._drag = None
            try:
                self.releaseMouse()
            except Exception:                         # noqa: BLE001
                pass
            self._emit()

    def leaveEvent(self, ev):
        self._hot = None
        self.update()
        super().leaveEvent(ev)

    def _apply(self, x):
        v = self._v(x)
        if self._drag == "lo":
            self._lo = max(self._min, min(v, self._hi - 1))
        else:
            self._hi = min(self._max, max(v, self._lo + 1))
        self.update()

    def keyPressEvent(self, ev):
        step = 20 if ev.modifiers() & Qt.ShiftModifier else 1
        which = self._hot or "lo"
        if ev.key() == Qt.Key_Left:
            if which == "lo":
                self._lo = max(self._min, self._lo - step)
            else:
                self._hi = max(self._lo + 1, self._hi - step)
        elif ev.key() == Qt.Key_Right:
            if which == "lo":
                self._lo = min(self._hi - 1, self._lo + step)
            else:
                self._hi = min(self._max, self._hi + step)
        elif ev.key() == Qt.Key_Home:
            self._lo, self._hi = self._min, max(self._min + 1, self._hi)
        elif ev.key() == Qt.Key_End:
            self._hi = self._max
        else:
            super().keyPressEvent(ev)
            return
        self.update()
        self._emit()

    # ------------------------------------------------------------ 画
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        t = self._track()
        rad = 8.0

        # 轨道底
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.FIELD))
        p.drawRoundedRect(t, rad, rad)

        # 直方图（裁到圆角内）
        if self._hist:
            p.save()
            clip = QRectF(t)
            p.setClipRect(clip)
            n = len(self._hist)
            gap = 1.0
            bw = max(1.0, (t.width() - gap * (n - 1)) / n)
            h = t.height()
            col = QColor(self._color)
            col.setAlphaF(0.42)
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            for i, v in enumerate(self._hist):
                bh = max(1.5, float(v) * (h - 5))
                p.drawRect(QRectF(t.left() + i * (bw + gap), h - bh, bw, bh))
            p.restore()

        # 选中区间填充
        xl, xr = self._x(self._lo), self._x(self._hi)
        fill = QColor(self._color)
        fill.setAlphaF(0.13)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRect(QRectF(xl, 0, max(0.0, xr - xl), t.height()))

        # 区间外白色蒙版
        mask = QColor(255, 255, 255, 158)
        p.setBrush(mask)
        if xl > 0:
            p.drawRect(QRectF(0, 0, xl, t.height()))
        if xr < t.width():
            p.drawRect(QRectF(xr, 0, t.width() - xr, t.height()))

        # 轨道内描边
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 14), 1.0))
        p.drawRoundedRect(t.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

        # 手柄
        for which, x in (("lo", xl), ("hi", xr)):
            hot = (self._hot == which) or (self._drag == which)
            w = HANDLE_W_HOT if hot else HANDLE_W
            hr = QRectF(x - w / 2.0, t.center().y() - HANDLE_H / 2.0, w, HANDLE_H)
            if hot:
                ring = QColor(self._color)
                ring.setAlphaF(0.20)
                p.setPen(Qt.NoPen)
                p.setBrush(ring)
                p.drawRoundedRect(hr.adjusted(-3, -3, 3, 3), 6, 6)
            p.setBrush(QColor("#FFFFFF"))
            p.setPen(QPen(self._color, 1.5))
            p.drawRoundedRect(hr.adjusted(0.75, 0.75, -0.75, -0.75), 4, 4)

    def sizeHint(self):
        return QSize(260, TRACK_H + 2)
