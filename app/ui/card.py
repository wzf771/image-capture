# -*- coding: utf-8 -*-
"""卡片外壳与动画控件：功能模块（右栏那几张卡）的公共底座。

从 main_window.py 拆出来（2026-09-22），只搬不改逻辑。
"""
from __future__ import annotations

import math

from PySide6.QtCore import (QElapsedTimer, QObject, QRect, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QSizePolicy, QVBoxLayout, QWidget)

from ui import theme
from ui.widgets import HeadRow, LockDot


class ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, _ev):
        self.clicked.emit()


class CardFrame(QFrame):
    """功能模块外框。

    收起 = 白色圆角行 + 常驻柔光（照单选卡那个样式）；
    展开 = 浅灰卡片，鼠标移上去边线变蓝 + 阴影。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shadow = None
        self._kind = None
        self._profile = "soft"
        self._suspended = False

    def set_hover(self, on):
        """悬停态用属性标记，而不是 QSS 的 :hover ——
        滑动时鼠标压在卡片上，:hover 会跟着每帧的几何变化闪。"""
        if bool(self.property("hover")) == bool(on):
            return
        self.setProperty("hover", bool(on))
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    def _set_shadow(self, kind):
        if kind == self._kind:
            return
        if self._shadow is not None:
            self.setGraphicsEffect(None)
            self._shadow = None
        self._kind = kind
        if kind is None:
            return
        eff = QGraphicsDropShadowEffect(self)
        if kind == "soft":                       # box-shadow: 0 2px 5px rgba(0,0,0,.1)
            eff.setBlurRadius(8)
            eff.setOffset(0, 2)
            eff.setColor(QColor(0, 0, 0, 32))
        else:
            eff.setBlurRadius(18)
            eff.setOffset(0, 4)
            eff.setColor(QColor(0, 0, 0, 60))
        self._shadow = eff
        self.setGraphicsEffect(eff)

    def apply_state(self, expanded, hovering=False):
        self._profile = "hover" if expanded else "soft"
        if expanded:
            self._set_shadow("hover" if hovering else None)
        else:
            self._set_shadow("soft")

    def enterEvent(self, ev):
        if SlideAnim.busy():                 # 滑动中不改状态，免得一帧一变地闪
            super().enterEvent(ev)
            return
        self.set_hover(True)
        if self._profile == "hover":
            self._set_shadow("hover")
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        if SlideAnim.busy():
            super().leaveEvent(ev)
            return
        self.set_hover(False)
        if self._profile == "hover":
            self._set_shadow(None)
        super().leaveEvent(ev)


class SlideHolder(QWidget):
    """只干一件事：把里面的内容裁掉多余的部分。

    里面的内容始终保持自己完整的高度（内部布局不会被压缩），
    没被显示出来的部分直接裁掉即可 —— 不然收缩时里面的控件会被挤着上下乱跑。
    """

    def __init__(self, inner, parent=None):
        super().__init__(parent)
        self.inner = inner
        inner.setParent(self)
        inner.move(0, 0)
        self.settled = True                  # 完全展开且静止时，才报出最小高度
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def sizeHint(self):
        h = self.inner.sizeHint()
        return QSize(self.width() or h.width(), h.height())

    def minimumSizeHint(self):
        # 滑动过程中必须允许被压到 0，否则布局不让它收缩
        return self.inner.minimumSizeHint() if self.settled else QSize(0, 0)

    def resizeEvent(self, _ev):
        h = max(self.height(), self.inner.sizeHint().height())
        self.inner.setGeometry(0, 0, self.width(), h)


class SlideAnim(QObject):
    """展开 / 收起用的高度动画。

    帧率跟屏幕刷新率对齐（最多 60fps）：推得比屏幕快反而会让合成器丢帧，
    看起来一顿一顿的。缓动用 InOutSine，起步和收尾都轻，单帧位移小。
    """

    _active = 0                      # 正在滑的卡片数：滑动期间先别碰阴影特效

    @classmethod
    def busy(cls):
        return cls._active > 0

    def __init__(self, body, duration=420, interval=None, parent=None):
        super().__init__(parent)
        self.body = body
        self.duration = duration
        if interval is None:
            interval = 16
            scr = QApplication.primaryScreen()
            if scr is not None:
                hz = float(scr.refreshRate() or 60.0)
                if 30.0 <= hz <= 240.0:
                    interval = max(16, int(round(1000.0 / hz)))     # 最多 60fps
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._step)
        self._clock = QElapsedTimer()
        self._from = 0.0
        self._to = 0.0
        self._last = -1
        self._counted = False
        self._on_done = None

    def running(self):
        return self._timer.isActive()

    def start(self, frm, to, on_done=None):
        self._timer.stop()
        if not self._counted:
            SlideAnim._active += 1
            self._counted = True
        self._from, self._to = float(frm), float(to)
        self._last = -1
        self._on_done = on_done
        self._clock.restart()
        self._apply(self._from)
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _release(self):
        if self._counted:
            SlideAnim._active = max(0, SlideAnim._active - 1)
            self._counted = False

    def _apply(self, value):
        h = int(round(value))
        if h != self._last:              # 高度没变的帧不用重新布局，省一帧的活儿
            self._last = h
            self.body.setMaximumHeight(h)

    def _step(self):
        t = min(1.0, self._clock.elapsed() / float(self.duration))
        e = 0.5 - 0.5 * math.cos(math.pi * t)          # InOutSine
        self._apply(self._from + (self._to - self._from) * e)
        if t >= 1.0:
            self._timer.stop()
            self._release()
            if self._on_done is not None:
                self._on_done()


def card(title, hint="", collapsible=True, header_widget=None, module=False):
    """一个圆角卡片；点标题那一行可以收起 / 展开内容。"""
    box = CardFrame()
    box.setObjectName("module" if module else "card")
    box.title = title
    outer = QVBoxLayout(box)
    head = None
    dot = None
    if module:
        # 功能模块：标题那一行是「圆环 + 文字」，收起时整张卡就是这一行
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = HeadRow()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 7, 12, 7)
        hl.setSpacing(9)
        dot = LockDot()          # 小锁（2026-09-26 用户指定，替代原来的空心圆环）
        dot.setToolTip("点一下展开 / 收起")
        hl.addWidget(dot)
        lab = QLabel(title)
        lab.setObjectName("cardTitle")
        hl.addWidget(lab)
        if header_widget is not None:
            hl.addSpacing(2)
            hl.addWidget(header_widget)
        hl.addStretch(1)
        if hint:
            h = QLabel(hint)
            h.setObjectName("cardHint")
            hl.addWidget(h)
        outer.addWidget(head)
    else:
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)
        hl = QHBoxLayout()
        lab = ClickLabel(("▼ " if collapsible else "") + title)
        lab.setObjectName("cardTitle")
        if collapsible:
            lab.setCursor(Qt.PointingHandCursor)
            lab.setToolTip("点一下收起 / 展开")
        hl.addWidget(lab)
        if header_widget is not None:
            hl.addSpacing(2)
            hl.addWidget(header_widget)
        hl.addStretch(1)
        if hint:
            h = QLabel(hint)
            h.setObjectName("cardHint")
            hl.addWidget(h)
        outer.addLayout(hl)
    body = QWidget()
    lay = QVBoxLayout(body)
    if module:
        lay.setContentsMargins(12, 8, 12, 12)
    else:
        lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    holder = SlideHolder(body)               # 收缩时只裁剪，不压缩里面的内容
    outer.addWidget(holder)
    box.body = lay
    box.body_widget = body
    box.holder = holder
    box.head = head

    def set_expanded(on):
        box.setProperty("expanded", bool(on))
        if dot is not None:
            # 小锁的勾选态 = 卡片展开：紫底 + 锁梁打开（原来的圆环只在换颜色）
            dot.set_on(bool(on))
        targets = [box] + ([head] + head.findChildren(QWidget) if head is not None else [])
        for w in targets:                # 属性变了，样式要重新套一遍
            w.style().unpolish(w)
            w.style().polish(w)
        box.apply_state(bool(on), box.underMouse())
        box.update()

    # 展开 / 收起：直接切换，不做下滑动画
    box.want_open = True

    def set_open(on):
        """直接设定展开/收起（不播动画）。

        建界面时用它摆默认排布：用户要求"打开软件时只展开「裁剪视野」与
        「通道与颜色」"，见 main_window._build_right()。
        """
        on = bool(on)
        box.want_open = on
        if not module:
            lab.setText(("▼ " if on else "▶ ") + title)
        holder.settled = True
        holder.setMaximumHeight(16777215 if on else 0)
        holder.updateGeometry()
        set_expanded(on)
        box.set_hover(box.underMouse())
        if callable(getattr(box, "on_settled", None)):
            box.on_settled()

    def toggle():
        set_open(not box.want_open)

    if module:
        if collapsible:
            head.clicked.connect(toggle)
            if dot is not None:
                # 点小锁跟点标题行一个效果（锁自己吃掉了点击，所以要显式接上）
                dot.toggled.connect(lambda _on: toggle())
    elif collapsible:
        lab.clicked.connect(toggle)
    box.toggle = toggle
    box.set_open = set_open
    set_expanded(True)
    return box
