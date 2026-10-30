# -*- coding: utf-8 -*-
"""导入按钮：照 Uiverse 的 .cssbuttons-io-button 做的（紫色圆角 + 右侧白色箭头方格）。

悬停时白色方格横向撑满整条按钮、箭头右移一点；按下时方格轻微缩小。
"""
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QPushButton

BG = QColor("#5B5BD6")
INNER = QColor(74, 74, 194, 110)          # inset 阴影用的深靛蓝
ICON_BG = QColor("#ffffff")
ICON_INK = QColor("#5B5BD6")
ICON_SHADOW = QColor(91, 91, 214)
TEXT = QColor("#ffffff")

EM = 14.0                                 # 对应 CSS 的 1em（font-size）


class ImportButton(QPushButton):
    """导入相关功能合并成一个按钮。"""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("io")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(int(EM * 2.8))
        f = QFont(self.font())
        f.setPixelSize(int(EM))
        f.setWeight(QFont.Medium)
        f.setLetterSpacing(QFont.AbsoluteSpacing, EM * 0.05)
        self.setFont(f)
        self._p = 0.0
        self._press = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(120)
        self._press_anim.valueChanged.connect(self._on_press)

    def sizeHint(self):
        w = self.fontMetrics().horizontalAdvance(self.text()) + EM * (1.2 + 3.3)
        base = super().sizeHint()
        return QSize(max(int(w), base.width()), int(EM * 2.8))

    # ---------------------------------------------------------- 动画
    def _on_value(self, v):
        self._p = float(v)
        self.update()

    def _on_press(self, v):
        self._press = float(v)
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

    def mousePressEvent(self, ev):
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(1.0)
        self._press_anim.start()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(0.0)
        self._press_anim.start()
        super().mouseReleaseEvent(ev)

    # ---------------------------------------------------------- 绘制
    def _icon_rect(self, r):
        full_w = EM * 2.2
        target_w = r.width() - EM * 0.6
        w = full_w + (target_w - full_w) * self._p
        scale = 1.0 - 0.05 * self._press
        h = EM * 2.2 * scale
        right = r.right() - EM * 0.3
        return QRectF(right - w, r.center().y() - h / 2.0, w, h)

    def _arrow_path(self, rect):
        size = min(EM * 1.1, rect.height() * 0.72)
        cx = rect.center().x() + self._p * EM * 0.1
        cy = rect.center().y()
        s = size / 24.0

        def P(x, y):
            return QPointF(cx + (x - 12.0) * s, cy + (y - 12.0) * s)

        path = QPainterPath()
        path.moveTo(P(16.172, 11.0))
        path.lineTo(P(10.808, 5.636))
        path.lineTo(P(12.222, 4.222))
        path.lineTo(P(20.0, 12.0))
        path.lineTo(P(12.222, 19.778))
        path.lineTo(P(10.808, 18.364))
        path.lineTo(P(16.172, 13.0))
        path.lineTo(P(4.0, 13.0))
        path.lineTo(P(4.0, 11.0))
        path.closeSubpath()
        return path

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = EM * 0.9
        p.setPen(Qt.NoPen)
        p.setBrush(BG)
        p.drawRoundedRect(r, radius, radius)
        p.setBrush(Qt.NoBrush)
        p.setPen(INNER)
        pen_w = max(2.0, EM * 0.22)
        inner = r.adjusted(pen_w / 2.0, pen_w / 2.0, -pen_w / 2.0, -pen_w / 2.0)
        p.drawRoundedRect(inner, radius * 0.9, radius * 0.9)
        p.setPen(TEXT)
        p.setFont(self.font())
        text_rect = QRectF(r.left() + EM * 1.2, r.top(),
                           max(1.0, r.width() - EM * 1.2 - EM * 2.6), r.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        ir = self._icon_rect(r)
        p.setPen(Qt.NoPen)
        for i in range(5, 0, -1):
            alpha = int(ICON_SHADOW.alpha() * 0.06 * i)
            p.setBrush(QColor(ICON_SHADOW.red(), ICON_SHADOW.green(), ICON_SHADOW.blue(), alpha))
            spread = EM * 0.06 * i
            p.drawRoundedRect(ir.adjusted(-spread + EM * 0.1, -spread + EM * 0.1,
                                          spread + EM * 0.1, spread + EM * 0.1),
                              EM * 0.7 + spread * 0.4, EM * 0.7 + spread * 0.4)
        p.setBrush(ICON_BG)
        p.drawRoundedRect(ir, EM * 0.7, EM * 0.7)
        p.setBrush(ICON_INK)
        p.drawPath(self._arrow_path(ir))
