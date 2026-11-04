# -*- coding: utf-8 -*-
"""Wake slider（Bencho，MIT — bencho.dev/licence）的 Qt 移植。

一排细竖条，没有滑块：数值之前的条是实心的，之后是淡的；数值显示在右侧（本项目的行里
已经有自己的读数标签，所以默认不重复画）。

── 每个条自己存一点能量 ──────────────────────────────────
拖动时数值跨过哪根条，哪根条就从拖动速度里拿到能量；每帧统一按 exp(-dt·6.5) 衰减，
所以越早被扫过的条落得越低 —— **最高的永远在手边，后面拖出一条尾巴**。这条尾巴不是画
出来的，是衰减本身。

── 令牌映射 ─────────────────────────────────────────────
    --fill-on  → theme.TEXT    （点亮的条 / 数字）
    --fill-slab→ theme.FIELD   （未点亮的条：32% 墨 + 68% 面）
两者都取自项目已有令牌，没有新增全局变量。

高度每帧在变，所以直接画在 paintEvent 里，不走布局。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPolygonF
from PySide6.QtWidgets import QPushButton, QWidget

from ui import theme


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(round(a.red() + (b.red() - a.red()) * t)),
                  int(round(a.green() + (b.green() - a.green()) * t)),
                  int(round(a.blue() + (b.blue() - a.blue()) * t)))


class WakeSlider(QWidget):
    """细条 + 拖尾的滑条。API 跟 QSlider 够用的一小撮：setRange / setValue / value / valueChanged。"""

    valueChanged = Signal(int)      # 需要换帧（重活）
    valuePreview = Signal(int)      # 只更新读数（轻活，拖动时每次都用它）
    dragStarted = Signal()          # 按下（进入“拖动优先”模式）
    dragEnded = Signal()            # 松开

    BAR_W = 3
    GAP = 4
    BAR_H = 20            # 静息高度
    RISE = 1.2            # 最高 1.2 倍（2026-11-03 用户要求：别弹太高）
    DECAY = 6.5           # 每帧衰减率（原组件 fall = exp(-dt*6.5)）

    def __init__(self, parent=None, bars=36, wake=60, show_value=False):
        super().__init__(parent)
        self._n = max(12, min(64, int(bars)))
        self._wake = float(wake)
        self._show_value = bool(show_value)
        self._lo, self._hi = 0, 100
        self._v = 0
        self._f = 0.0
        self._energy = [0.0] * self._n
        self._down = False
        self._last_x = 0.0
        self._last_t = 0.0
        self._speed = 0.0
        self._at = 0.0            # 当前值（0..1），不经过信号
        self._last_bar = -1
        self._raf = False
        self._last_frame = time.monotonic()
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.timeout.connect(self._flush)
        self._pending = False
        self._tick = QTimer(self)
        self._tick.setTimerType(Qt.PreciseTimer)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._loop)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.SizeHorCursor)
        self.setMinimumHeight(int(self.BAR_H * self.RISE) + 6)

    # ------------------------------------------------------------ 尺寸
    def sizeHint(self):
        return QSize(self._n * (self.BAR_W + self.GAP) - self.GAP,
                     int(self.BAR_H * self.RISE) + 6)

    def _strip(self) -> QRectF:
        h = self.BAR_H * self.RISE
        y = (self.height() - h) / 2.0
        return QRectF(2.0, y, max(10.0, self.width() - 4.0), h)

    def _pitch(self) -> float:
        """条的步距：铺满整行，而不是固定 7px 挤在中间。"""
        r = self._strip()
        return (r.width() + self.GAP) / max(1, self._n)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 条数按可用宽度重新分（12..64），能量表跟着重建
        n = int((self.width() + self.GAP) / (self.BAR_W + self.GAP))
        n = max(12, min(64, n))
        if n != self._n:
            self._n = n
            self._energy = [0.0] * n

    # ------------------------------------------------------------ API
    def setRange(self, lo, hi):                      # noqa: N802
        self._lo, self._hi = int(lo), int(hi)
        if self._hi <= self._lo:
            self._hi = self._lo + 1
        self.setValue(self._v)

    def setValue(self, v):                           # noqa: N802
        self._set_value(v, emit=True)
        self._at = self._f

    def value(self):
        return self._v

    def setEnabled(self, on):                        # noqa: N802
        super().setEnabled(on)
        self.setCursor(Qt.SizeHorCursor if on else Qt.ArrowCursor)
        self.update()

    # ------------------------------------------------------------ 数值 / 能量
    def _to(self, f, speed):
        f = max(0.0, min(1.0, f))
        self._at = f
        a = int(round(self._f * (self._n - 1)))
        b = int(round(f * (self._n - 1)))
        # 有多重：拖动速度经过一条饱和曲线，再按 wake 旋钮缩放
        push = (1.0 - math.exp(-speed / 900.0)) * (self._wake / 60.0)
        for i in range(min(a, b), max(a, b) + 1):
            self._energy[i] = max(self._energy[i], push)
        self._last_bar = b
        self._set_value(int(round(self._lo + f * (self._hi - self._lo))), emit=False)
        self._pending = True
        if not self._emit_timer.isActive():
            self._emit_timer.start(90)      # 拖动中 ~11 次/秒；换帧已在后台线程，不会卡住拖尾
        self._start()

    def _set_value(self, v, emit=True):
        v = max(self._lo, min(self._hi, int(v)))
        if v == self._v:
            return
        self._v = v
        self._f = (v - self._lo) / float(self._hi - self._lo)
        self.update()
        self.valuePreview.emit(v)
        if emit:
            self.valueChanged.emit(v)

    def _flush(self):
        if not self._pending:
            return
        self._pending = False
        self.valueChanged.emit(self._v)

    def _start(self):
        if not self._tick.isActive():
            self._last_frame = time.monotonic()
            self._tick.start()

    def _loop(self):
        now = time.monotonic()
        dt = min(0.05, max(0.001, now - self._last_frame))
        self._last_frame = now
        live = False
        fall = math.exp(-dt * self.DECAY)
        for i in range(self._n):
            e = self._energy[i] * fall
            if e < 0.002:
                e = 0.0
            else:
                live = True
            self._energy[i] = e
        self.update()
        if not live and not self._down:
            self._tick.stop()

    # ------------------------------------------------------------ 交互
    def _frac(self, x):
        r = self._strip()
        return 0.0 if r.width() <= 0 else (x - r.left()) / r.width()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self.isEnabled():
            return
        self._down = True
        self.dragStarted.emit()
        self._last_x = ev.position().x()
        self._last_t = time.monotonic()
        self._speed = 0.0
        self._to(self._frac(ev.position().x()), 0.0)

    def mouseMoveEvent(self, ev):
        if not self._down:
            return
        now = time.monotonic()
        dt = max(0.008, now - self._last_t)
        v = abs(ev.position().x() - self._last_x) / dt
        self._speed = self._speed * 0.5 + v * 0.5      # 平滑，单帧抖动不算甩
        self._last_x = ev.position().x()
        self._last_t = now
        self._to(self._frac(ev.position().x()), self._speed)

    def mouseReleaseEvent(self, ev):
        self._down = False
        self._emit_timer.stop()
        if self._pending:                    # 松手立刻补最后一帧（还在快速模式，走异步）
            self._pending = False
            self.valueChanged.emit(self._v)
        self.dragEnded.emit()
        self._start()

    def keyPressEvent(self, ev):
        step = 10 if ev.modifiers() & Qt.ShiftModifier else 1
        v = self._v
        if ev.key() in (Qt.Key_Right, Qt.Key_Up):
            v += step
        elif ev.key() in (Qt.Key_Left, Qt.Key_Down):
            v -= step
        elif ev.key() == Qt.Key_Home:
            v = self._lo
        elif ev.key() == Qt.Key_End:
            v = self._hi
        else:
            super().keyPressEvent(ev)
            return
        v = max(self._lo, min(self._hi, v))
        self._to((v - self._lo) / float(self._hi - self._lo), 600.0)

    # ------------------------------------------------------------ 画
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(0.45)
        ink = QColor(theme.TEXT)
        slab = QColor(theme.FIELD)
        r = self._strip()
        lit = int(round(self._f * (self._n - 1)))
        cy = r.center().y()
        base = self.BAR_H
        pitch = self._pitch()
        for i in range(self._n):
            x = r.left() + i * pitch
            e = self._energy[i]
            h = base * (1.0 + e * (self.RISE - 1.0))
            on = self._v > self._lo and i <= lit
            p.setPen(Qt.NoPen)
            p.setBrush(ink if on else _mix(slab, ink, 0.32))
            p.drawRoundedRect(QRectF(x, cy - h / 2.0, self.BAR_W, h),
                              self.BAR_W / 2.0, self.BAR_W / 2.0)
        if self._show_value:
            f = p.font()
            f.setPixelSize(int(theme.SIZE_BODY))
            p.setFont(f)
            p.setPen(_mix(slab, ink, 0.72))
            fm = QFontMetrics(f)
            txt = str(self._v)
            p.drawText(QRectF(r.right() + 12, 0, fm.horizontalAdvance(txt) + 4, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, txt)


class PlayButton(QPushButton):
    """时间轴播放按钮：circle-play（Lucide）↔ 暂停（两竖线 + 圆环），24×24。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("自动播放")
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        self._hover = False

    def enterEvent(self, ev):
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev):
        from ui.magnifying_dock import paint_svg
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect())
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(33, 30, 24, 16))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        ink = QColor(theme.TEXT)
        if not self.isEnabled():
            ink.setAlpha(110)
        if self.isChecked():                       # 暂停：圆环 + 两竖线
            pen = p.pen()
            pen.setColor(ink)
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(4, 4, 16, 16))
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            p.drawRoundedRect(QRectF(9.6, 8, 1.8, 8), 0.9, 0.9)
            p.drawRoundedRect(QRectF(12.8, 8, 1.8, 8), 0.9, 0.9)
        else:
            paint_svg(p, "circle_play", QRectF(4, 4, 16, 16), ink)
