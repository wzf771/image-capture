# -*- coding: utf-8 -*-
"""液体开关（Bencho「Liquid toggle」的 Qt 移植，MIT — bencho.dev/licence）。

原组件是 React + framer-motion；这里是同一套**行为**的 QPainter 重写：

  · 拖动：拇指跟着指针走，**跨过中线就切换**（不用等松手）
  · 松手：弹簧回位（stiffness 170 / damping 21.5 / mass 0.9，原组件的 settling）
  · 行进中：沿运动方向**拉长、横向压薄**，面积守恒（scaleY = 1/scaleX），
    所以它是一滴被拉长的液体，而不是掉在后面的影子
  · 悬停：整体膨胀 1.035，位置不动
  · 单击（没移动）= 切换；键盘 空格 / 回车 也能切

── 令牌映射（原 CSS 读 --fill-on / --fill-slab / --ink / --board / --pane-edge）──
    --fill-on   → theme.TEXT      开 = 墨色轨（本项目文字已全黑）
    --fill-slab → theme.FIELD     关 = 浅面轨 / 开态的拇指
    --ink       → theme.TEXT
    --board     → theme.BG
    --card      → theme.CARD（本组件不铺白卡，未使用）
    --pane-edge → theme.LINE（未使用：原版明确不给开关描边）
原版注释里关于“为什么不加 goo 滤镜”的结论保留：单个圆做模糊再阈值只会让边缘变糊，
所以这里直接用抗锯齿画椭圆。

尺寸：原版 92×46 / 拇指 36 / 内边距 5；本项目工具栏一行放不下那么大，
按同一比例缩到 40×20 / 拇指 16 / 内边距 2。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ui import theme


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(round(a.red() + (b.red() - a.red()) * t)),
                  int(round(a.green() + (b.green() - a.green()) * t)),
                  int(round(a.blue() + (b.blue() - a.blue()) * t)))


class LiquidSwitch(QWidget):
    """液体开关。API 跟 QCheckBox 够用的一小撮：setChecked / isChecked / toggle / toggled。"""

    toggled = Signal(bool)

    W, H = 40, 20
    THUMB = 16.0
    PAD = (20 - 16) / 2.0
    SHUT_X = PAD
    OPEN_X = 40 - THUMB - PAD
    MID_X = (SHUT_X + OPEN_X) / 2.0

    STIFF, DAMP, MASS = 170.0, 21.5, 0.9
    STRETCH = 0.36                      # 原组件 stretch=36 / 100
    VEL_DIV = 600.0 * ((OPEN_X - SHUT_X) / 44.0)   # 44px 是原组件的行程
    SWELL = 0.035

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.W, self.H)
        self.setToolTip("点一下开 / 关；也可以直接拖动")
        self._on = False
        self._x = self.SHUT_X
        self._vx = 0.0            # 拇指速度 px/s（弹簧那一侧）
        self._sv = 0.0            # 平滑后的速度，用来算拉长
        self._hot = 0.0           # 悬停膨胀 0..1
        self._drag_at = None      # 拖动中：指针在控件里的 x
        self._grab = None         # 指针与拇指左缘的偏移（首次移动时取）
        self._moved = False
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self._timer.start()

    def _wake(self):
        """有活动才跑 60Hz；静止后自己停表。"""
        if not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()

    # ------------------------------------------------------------ 接口
    def sizeHint(self):
        return QSize(self.W, self.H)

    def isChecked(self) -> bool:
        return self._on

    def setChecked(self, on: bool):
        on = bool(on)
        if on == self._on:
            return
        self._on = on
        self._wake()
        self.update()
        self.toggled.emit(on)

    def toggle(self):
        self.setChecked(not self._on)

    def setEnabled(self, on):              # noqa: N802
        super().setEnabled(on)
        self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
        self.update()

    # ------------------------------------------------------------ 物理
    def _target(self) -> float:
        return self.OPEN_X if self._on else self.SHUT_X

    def _step(self):
        now = time.monotonic()
        dt = min(0.05, max(0.001, now - self._last))
        self._last = now

        if self._drag_at is None:
            # 弹簧回位
            acc = (self.STIFF * (self._target() - self._x) - self.DAMP * self._vx) / self.MASS
            self._vx += acc * dt
            self._x += self._vx * dt
            if abs(self._target() - self._x) < 0.05 and abs(self._vx) < 0.5:
                self._x = self._target()
                self._vx = 0.0
        # 速度平滑 → 拉长（原组件用 spring 收速度，这里用一阶低通，效果接近）
        self._sv += (self._vx - self._sv) * min(1.0, 18.0 * dt)
        # 悬停膨胀：缓动到 0/1
        tgt = 1.0 if self.underMouse() else 0.0
        self._hot += (tgt - self._hot) * min(1.0, 14.0 * dt)
        self.update()
        # 彻底静止 → 停表（有交互时会 _wake 重新启动）
        if (self._drag_at is None and abs(self._target() - self._x) < 0.05
                and abs(self._vx) < 0.5 and abs(self._hot - tgt) < 0.002):
            self._x = self._target()
            self._vx = 0.0
            self._hot = tgt
            self._timer.stop()

    # ------------------------------------------------------------ 交互
    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self.isEnabled():
            return
        self._wake()
        self._drag_at = ev.position().x()
        self._grab = None
        self._moved = False
        try:
            self.grabMouse()
        except Exception:                  # noqa: BLE001
            pass

    def mouseMoveEvent(self, ev):
        if self._drag_at is None:
            return
        self._wake()
        at = ev.position().x()
        if self._grab is None:
            self._grab = at - self._x
        nx = max(self.SHUT_X, min(self.OPEN_X, at - self._grab))
        if abs(nx - self._x) > 2.0:        # 2px 以内算抖动，不算拖动
            self._moved = True
        self._vx = (nx - self._x) * 60.0
        self._x = nx
        # 只有真的在拖动时才按中线切换；否则「刚点完、弹簧还在跑」时
        # 一次鼠标移动就会把状态又翻回去（表现为“自己快速开关一下”）
        if self._moved:
            past = nx > self.MID_X
            if past != self._on:
                self._on = past
                self.toggled.emit(past)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag_at is None:
            return
        self._drag_at = None
        self._grab = None
        try:
            self.releaseMouse()
        except Exception:                  # noqa: BLE001
            pass
        if not self._moved:                # 没移动 = 单击
            self.toggle()
        self.update()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.toggle()
            return
        super().keyPressEvent(ev)

    def enterEvent(self, ev):
        super().enterEvent(ev)
        self._wake()
        self.update()

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        self._wake()
        self.update()

    # ------------------------------------------------------------ 画
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(0.45)
        ink = QColor(theme.TEXT)
        slab = QColor(theme.FIELD)
        t = 1.0 if self._on else 0.0

        # 轨：关 = 浅面，开 = 墨色；始终是胶囊
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(slab, ink, t))
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), self.H / 2.0, self.H / 2.0)

        # 拇指：关 = 墨色混浅 19%，开 = 浅面
        thumb_off = _mix(slab, ink, 0.19)   # color-mix(fill-on 19%, fill-slab)
        p.setBrush(_mix(thumb_off, slab, t))

        speed = abs(self._sv)
        lengthen = 1.0 + min(0.4, speed / self.VEL_DIV) * self.STRETCH
        swell = 1.0 + self.SWELL * max(0.0, min(1.0, self._hot))
        sx = lengthen * swell
        sy = swell / lengthen
        cx = self._x + self.THUMB / 2.0
        cy = self.H / 2.0
        w = self.THUMB * sx
        h = self.THUMB * sy
        p.drawEllipse(QRectF(cx - w / 2.0, cy - h / 2.0, w, h))
