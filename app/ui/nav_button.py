# -*- coding: utf-8 -*-
"""顶栏那两个切换按钮（左栏 / 右栏）专用样式。

效果照搬 Uiverse 那个按钮：深蓝底 + 悬停时黄色块从右往左扫过、文字变深蓝并轻微回弹。
Qt 的样式表不支持过渡动画，所以这里自己画。
"""
import math

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton

BASE_ON = QColor("#5B5BD6")      # 面板展开：主色
BASE_OFF = QColor("#FFFFFF")     # 面板收起：白底
FILL = QColor("#5B5BD6")         # 悬停扫过的主色
TEXT_ON = QColor("#FFFFFF")
TEXT_OFF = QColor("#8A8AA3")
TEXT_HOVER = QColor("#FFFFFF")


def _mix(a: QColor, b: QColor, t):
    t = min(max(t, 0.0), 1.0)
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class NavButton(QPushButton):
    """顶栏用的圆角按钮：深蓝底，悬停时黄色从右往左扫过。"""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setMinimumWidth(112)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(11.0, self.font().pointSizeF() + 2.5))
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3.5)
        self.setFont(f)
        self._p = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(400)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._on_value)
        try:                                     # 轻微投影，跟 CSS 的 box-shadow 对应
            fx = QGraphicsDropShadowEffect(self)
            fx.setBlurRadius(18)
            fx.setOffset(0, 5)
            fx.setColor(QColor(0, 0, 0, 60))
            self.setGraphicsEffect(fx)
        except Exception:                        # noqa: BLE001
            pass

    # ---------------------------------------------------------- 动画
    def _on_value(self, value):
        self._p = float(value)
        self.update()

    def _animate_to(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._p)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def enterEvent(self, ev):
        self._animate_to(1.0)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._animate_to(0.0)
        super().leaveEvent(ev)

    def sizeHint(self):
        s = super().sizeHint()
        return s.expandedTo(self.minimumSize())

    # ---------------------------------------------------------- 绘制
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 5.0
        base = BASE_ON if self.isChecked() else BASE_OFF
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(r, radius, radius)
        if not self.isChecked():                 # 收起态：白底 + 浅描边
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor("#E8E8F2"))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if self._p > 0.001:                      # 主色从右往左扫入
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)
            p.save()
            p.setClipPath(path)
            w = r.width() * self._p
            p.setBrush(FILL)
            p.drawRect(QRectF(r.right() - w, r.top(), w, r.height()))
            p.restore()
        rest = TEXT_ON if self.isChecked() else TEXT_OFF
        text_col = _mix(rest, TEXT_HOVER, self._p)
        scale = 1.0 - 0.05 * math.sin(math.pi * min(max(self._p, 0.0), 1.0))
        p.save()
        c = r.center()
        p.translate(c)
        p.scale(scale, scale)
        p.translate(-c)
        p.setPen(text_col)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.restore()
