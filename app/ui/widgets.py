# -*- coding: utf-8 -*-
"""自定义控件：双端拖动的区间条、胶囊开关、软底字段。"""
import math

from PySide6.QtCore import (QByteArray, QEasingCurve, QPointF, QRect, QRectF, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGradient,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QTransform)
from PySide6.QtWidgets import (QCheckBox, QFrame, QGraphicsDropShadowEffect, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QWidget)

try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:                                    # noqa: BLE001
    QSvgRenderer = None

ACCENT = QColor("#5B5BD6")
TRACK = QColor("#EDEEF5")


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """两个颜色按 t 线性插值（连 alpha 一起）。"""
    t = max(0.0, min(1.0, float(t)))
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t),
                  int(a.alpha() + (b.alpha() - a.alpha()) * t))


class MiniSwitch(QCheckBox):
    """细杆圆点开关（照 Uiverse 的 .toggle 复刻，2026-09-23 用户指定为全局唯一样式）。

    尺寸就按原稿来：整体 40×20，底槽 34×14（左上各内缩 3px、圆角 8），圆点 20×20 ——
    关：白点带 3px 柔影停在左边；开：变 #4f2edc 并右移 20px（translateX(20px)）。
    底槽 关=#9a9999 / 开=#947ada；圆点位置 0.2s cubic-bezier(0.8,0.4,0.3,1.25)（末端回弹），
    底色 0.15s 渐变；打开时还有一圈 56px 的紫涟漪扩散淡出（原稿的 span:before）。
    **整块都能点** —— 用户反馈过"只有最左边那点能触发"。
    """

    W, H = 40, 20
    KNOB = 20.0
    TRACK_OFF = QColor("#9a9999")
    TRACK_ON = QColor("#947ada")
    KNOB_OFF = QColor("#FFFFFF")
    KNOB_ON = QColor("#4f2edc")
    WAVE = QColor(79, 46, 220, 128)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.W, self.H)
        self.setToolTip("点一下开 / 关")
        self._p = 1.0 if self.isChecked() else 0.0
        self._wave = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(200)
        curve = QEasingCurve()
        curve.setType(QEasingCurve.BezierSpline)
        curve.addCubicBezierSegment(QPointF(0.8, 0.4), QPointF(0.3, 1.25), QPointF(1.0, 1.0))
        self._anim.setEasingCurve(curve)
        self._anim.valueChanged.connect(self._tick)
        self._wave_anim = QVariantAnimation(self)
        self._wave_anim.setDuration(400)
        self._wave_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._wave_anim.valueChanged.connect(self._tick_wave)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self):
        return QSize(self.W, self.H)

    def hitButton(self, pos):
        """整块都能点（QCheckBox 默认只有指示器那一小块能点）。"""
        return self.rect().contains(pos)

    # -------------------------------------------------- 动画
    def _tick(self, value):
        self._p = float(value)
        self.update()

    def _tick_wave(self, value):
        self._wave = float(value)
        self.update()

    def _on_toggled(self, on):
        target = 1.0 if on else 0.0
        self._anim.stop()
        if not self.isVisible():                  # 初始化设值别演一遍动画
            self._p = target
            self.update()
        else:
            self._anim.setStartValue(float(self._p))
            self._anim.setEndValue(target)
            self._anim.start()
        if on and self.isVisible():               # 打开时来一圈涟漪
            self._wave_anim.stop()
            self._wave = 0.0
            self._wave_anim.setStartValue(0.0)
            self._wave_anim.setEndValue(1.0)
            self._wave_anim.start()

    # -------------------------------------------------- 画
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        t = max(0.0, min(1.0, self._p))
        cx = self.KNOB * t + self.KNOB / 2.0      # 圆点中心：从左 10px 走到 30px
        cy = self.H / 2.0
        if 0.0 < self._wave < 1.0:                # 涟漪：56px 紫圈扩散 + 淡出
            grow = 56.0 * self._wave
            a = int(self.WAVE.alpha() * (1.0 - self._wave))
            if a > 0 and grow > 1.0:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.WAVE.red(), self.WAVE.green(), self.WAVE.blue(), a))
                p.drawEllipse(QRectF(cx - grow / 2.0, cy - grow / 2.0, grow, grow))
        # 底槽 34×14（圆角 8）
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(self.TRACK_OFF, self.TRACK_ON, t))
        p.drawRoundedRect(QRectF(3.0, 3.0, 34.0, 14.0), 8.0, 8.0)
        # 圆点：先铺柔影再盖本体（0 3px 8px 的 box-shadow 手绘近似）
        base = QColor(154, 153, 153, 70) if t < 0.5 else QColor(79, 46, 220, 50)
        for dy, k in ((3.0, 0.45), (2.0, 0.7), (1.0, 1.0)):
            c = QColor(base)
            c.setAlpha(int(base.alpha() * k))
            p.setBrush(c)
            p.drawEllipse(QRectF(cx - self.KNOB / 2.0, cy - self.KNOB / 2.0 + dy,
                                 self.KNOB, self.KNOB))
        p.setBrush(_mix(self.KNOB_OFF, self.KNOB_ON, t))
        p.drawEllipse(QRectF(cx - self.KNOB / 2.0, cy - self.KNOB / 2.0, self.KNOB, self.KNOB))


class Switch(MiniSwitch):
    """旧名字（历史代码 import 过），外观已统一到 MiniSwitch。"""


class FlipSwitch(MiniSwitch):
    """旧名字（导出内容 / 处理卡在用），外观已统一到 MiniSwitch。"""


class RangeSlider(QWidget):
    """一根药丸横条、两端各一个把手：左端=黑点，右端=白点。

    外形照用户给的那段 custom-loader：整条是圆角药丸 + 2px 描边，
    里面的填充块再内缩 2px、圆角跟着走；颜色换成软件主色。
    """
    valuesChanged = Signal(int, int)

    TRACK_H = 22          # 药丸高度
    BORDER = 2            # 描边粗细
    INSET = 2             # 填充块离描边内侧的距离
    KNOB = 14             # 两端把手直径（跟填充块一样高）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min = 0
        self._max = 255
        self._lo = 0
        self._hi = 255
        self._drag = None
        self.setMinimumHeight(self.TRACK_H + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("拖动两端改黑点/白点；滚轮微调离指针最近的那一端")

    def setRange(self, minimum, maximum):
        self._min = int(minimum)
        self._max = max(self._min + 1, int(maximum))
        self.setValues(self._lo, self._hi)
        self.update()

    def setValues(self, low, high, emit=False):
        lo = int(round(low))
        hi = int(round(high))
        lo = max(self._min, min(lo, self._max - 1))
        hi = max(lo + 1, min(hi, self._max))
        changed = (lo, hi) != (self._lo, self._hi)
        self._lo, self._hi = lo, hi
        self.update()
        if emit and changed:
            self.valuesChanged.emit(lo, hi)

    def values(self):
        return self._lo, self._hi

    def range_limits(self):
        return self._min, self._max

    def _track(self):
        pad = 2
        top = (self.height() - self.TRACK_H) // 2
        return QRect(pad, top, max(10, self.width() - 2 * pad), self.TRACK_H)

    def _span(self):
        """可拖区间：收进药丸两端圆头里，把手不会跑到外框外面。"""
        t = self._track()
        cap = self.TRACK_H / 2.0
        return float(t.left()) + cap, float(t.left() + t.width()) - cap

    def _x_of(self, value):
        a, b = self._span()
        frac = (value - self._min) / float(max(1, self._max - self._min))
        return int(round(a + frac * (b - a)))

    def _value_of(self, x):
        a, b = self._span()
        frac = (x - a) / float(max(1.0, b - a))
        return self._min + frac * (self._max - self._min)

    def _pick(self, x):
        return "lo" if abs(x - self._x_of(self._lo)) <= abs(x - self._x_of(self._hi)) else "hi"

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        self._drag = self._pick(ev.position().x())
        self._apply(ev.position().x())

    def mouseMoveEvent(self, ev):
        if self._drag:
            self._apply(ev.position().x())

    def mouseReleaseEvent(self, _ev):
        if self._drag:
            self._drag = None
            self.valuesChanged.emit(self._lo, self._hi)

    def _apply(self, x):
        v = self._value_of(x)
        if self._drag == "lo":
            self.setValues(v, self._hi)
        else:
            self.setValues(self._lo, v)
        self.valuesChanged.emit(self._lo, self._hi)

    def wheelEvent(self, ev):
        step = max(1, int((self._max - self._min) * 0.01)) * (1 if ev.angleDelta().y() > 0 else -1)
        if self._pick(ev.position().x()) == "lo":
            self.setValues(self._lo + step, self._hi, emit=True)
        else:
            self.setValues(self._lo, self._hi + step, emit=True)
        ev.accept()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        t = QRectF(self._track())
        radius = t.height() / 2.0
        # 轨道：白底 + 2px 主色描边，整条是药丸
        p.setPen(QPen(ACCENT, self.BORDER))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(t.adjusted(1.0, 1.0, -1.0, -1.0), radius, radius)
        x0, x1 = self._x_of(self._lo), self._x_of(self._hi)
        # 填充块：从描边内侧再缩 2px，圆角跟着药丸走
        inset = 1.0 + self.BORDER / 2.0 + self.INSET
        fill = QRectF(t.left() + inset, t.top() + inset,
                      max(0.0, float(x1 - x0)), t.height() - inset * 2.0)
        if fill.width() > 0.5:
            fr = fill.height() / 2.0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(fill, fr, fr)
        # 两端把手
        for x in (x0, x1):
            p.setBrush(QColor("#FFFFFF"))
            p.setPen(QPen(QColor(ACCENT), 2))
            half = self.KNOB / 2.0
            p.drawEllipse(QRectF(x - half, t.center().y() - half, self.KNOB, self.KNOB))


class BrutalButton(QPushButton):
    """深灰立体按钮（照 Uiverse 的 .button 复刻，2026-09-23 起是全局唯一按钮样式）。

    Qt 没有 box-shadow，原稿那串影子只能自己画：
      · `0 0 0 1px rgba(0,0,0,.7)`              外圈 1px 深色描边
      · `0 1px 0 0 rgba(255,255,255,.1) inset`  顶边一条白高光
      · `0 -1px 0 0 rgba(0,0,0,.7) inset`       底边一条深色内阴影
      · `0 1px 2px 1px rgba(0,0,0,.6)`          外投影（几层 alpha 叠出来）
    常态 #424242、悬停 #353535、按下 #181818（内阴影同时反过来）。
    勾选态（1:1 / 颜色：自动 这类胶囊）沿用主色填充 —— 不然看不出选没选中。
    白字 600、圆角 2（都是原稿值）。
    """

    BG = QColor("#424242")
    BG_HOVER = QColor("#353535")
    BG_DOWN = QColor("#181818")
    BG_CHECKED = QColor("#5B5BD6")
    BG_CHECKED_HOVER = QColor("#4E4EC4")
    BG_OFF = QColor("#6E6E78")        # 禁用
    TEXT = QColor("#FFFFFF")
    RADIUS = 2.0
    RESERVE = 4                       # 四周给外投影留的位置

    def __init__(self, text="", parent=None, compact=False):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        f = self.font()
        f.setBold(True)
        f.setWeight(QFont.DemiBold)               # 原稿 font-weight: 600
        self._compact = bool(compact)
        if self._compact:
            f.setPixelSize(12)
        self.setFont(f)
        self._hover = False
        self._down = False

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        if self._compact:
            return QSize(max(54, fm.horizontalAdvance(self.text()) + 30),
                         max(28, fm.height() + 13))
        return QSize(max(76, fm.horizontalAdvance(self.text()) + 34),
                     max(32, fm.height() + 17))

    def enterEvent(self, ev):
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._down = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        self._down = True
        self.update()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._down = False
        self.update()
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rr = float(self.RESERVE)
        body = QRectF(rr, rr, max(1.0, self.width() - 2 * rr),
                      max(1.0, self.height() - 2 * rr))
        if not self.isEnabled():
            bg = self.BG_OFF
        elif self._down:
            bg = self.BG_DOWN
        elif self.isChecked():
            bg = self.BG_CHECKED_HOVER if self._hover else self.BG_CHECKED
        else:
            bg = self.BG_HOVER if self._hover else self.BG
        # 外投影 0 1px 2px 1px rgba(0,0,0,.6)：由外向内叠三层，越靠外越淡
        p.setPen(Qt.NoPen)
        for grow, alpha in ((2.0, 40), (1.5, 55), (0.0, 70)):
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(body.adjusted(-grow, -grow + 1.0, grow, grow + 1.0),
                              self.RADIUS + grow, self.RADIUS + grow)
        # 本体 + 1px 深色描边
        p.setBrush(bg)
        p.setPen(QPen(QColor(0, 0, 0, 179), 1.0))
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
        # 内阴影：常态顶亮底暗；按下反过来（0 0 0 1px rgba(0,0,0,.7) inset）
        top = QColor(0, 0, 0, 90) if self._down else QColor(255, 255, 255, 26)
        bot = QColor(255, 255, 255, 12) if self._down else QColor(0, 0, 0, 179)
        x0, x1 = body.left() + self.RADIUS + 1.0, body.right() - self.RADIUS - 1.0
        p.setPen(QPen(top, 1.0))
        p.drawLine(QPointF(x0, body.top() + 1.0), QPointF(x1, body.top() + 1.0))
        p.setPen(QPen(bot, 1.0))
        p.drawLine(QPointF(x0, body.bottom() - 1.0), QPointF(x1, body.bottom() - 1.0))
        # 文字：白字居中
        p.setPen(self.TEXT if self.isEnabled() else QColor(255, 255, 255, 120))
        p.setFont(self.font())
        p.drawText(body, Qt.AlignCenter, self.text())


class SweepButton(BrutalButton):
    """左栏那几个按钮（新建组 / 清空 / 自动识别标尺）。

    以前是"浅灰底 + 悬停时深色从左扫满"，2026-09-23 用户要求所有按钮统一到
    新的深灰立体样式，于是这里直接继承 BrutalButton，那套扫过动效一并去掉；
    只保留原来稍大一号的字号，免得左栏按钮比别处小一圈。
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent, compact=False)
        f = self.font()
        f.setPixelSize(13)
        self.setFont(f)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(max(84, fm.horizontalAdvance(self.text()) + 38),
                     max(34, fm.height() + 22))


ICON_PLANET = (
    "M5 13c0-5.088 2.903-9.436 7-11.182C16.097 3.564 19 7.912 19 13c0 .823-.076 1.626-.22 "
    "2.403l1.94 1.832a.5.5 0 0 1 .095.603l-2.495 4.575a.5.5 0 0 1-.793.114l-2.234-2.234a1 1 "
    "0 0 0-.707-.293H9.414a1 1 0 0 0-.707.293l-2.234 2.234a.5.5 0 0 1-.793-.114l-2.495-4.575a"
    ".5.5 0 0 1 .095-.603l1.94-1.832C5.077 14.626 5 13.823 5 13zm1.476 6.696l.817-.817A3 3 0 0 "
    "1 9.414 18h5.172a3 3 0 0 1 2.121.879l.817.817.982-1.8-1.1-1.04a2 2 0 0 1-.593-1.82c.124-"
    ".664.187-1.345.187-2.036 0-3.87-1.995-7.3-5-8.96C8.995 5.7 7 9.13 7 13c0 .691.063 1.372."
    "187 2.037a2 2 0 0 1-.593 1.82l-1.1 1.039.982 1.8zM12 13a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"
)


class IconSlideButton(QPushButton):
    """图标 + 文字的深色渐变按钮。

    悬停：图标右移 5px 并从 30° 转到 90°，文字右移 7px，
    缓动 0.5s cubic-bezier(0.76, 0, 0.24, 1)，跟给的代码一致。
    """

    GRAD = ("#0F0C29", "#302B63", "#24243E")
    PAD_L, ICON, GAP, PAD_R = 12, 18, 4, 12

    def __init__(self, text="Download", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        f = self.font()
        f.setPixelSize(13)
        f.setWeight(QFont.Medium)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.65)      # 0.05em
        self.setFont(f)
        self._t = 0.0
        self._icon = self._render_icon()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(500)
        curve = QEasingCurve()
        curve.setType(QEasingCurve.BezierSpline)
        curve.addCubicBezierSegment(QPointF(0.76, 0.0), QPointF(0.24, 1.0), QPointF(1.0, 1.0))
        self._anim.setEasingCurve(curve)
        self._anim.valueChanged.connect(self._on_tick)

    # -------------------------------------------------- 图标
    @staticmethod
    def _render_icon(size=18, scale=4):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        if QSvgRenderer is not None:
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                   '<path fill="#FFFFFF" d="%s"/></svg>' % ICON_PLANET)
            r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            r.render(p)
            p.end()
        return pm

    # -------------------------------------------------- 动画
    def _on_tick(self, value):
        self._t = float(value)
        self.update()

    def _slide_to(self, target):
        self._anim.stop()
        self._anim.setStartValue(float(self._t))
        self._anim.setEndValue(float(target))
        self._anim.start()

    def enterEvent(self, ev):
        self._slide_to(1.0)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._slide_to(0.0)
        super().leaveEvent(ev)

    # -------------------------------------------------- 画
    def sizeHint(self):
        fm = QFontMetrics(self.font())
        w = self.PAD_L + self.ICON + self.GAP + fm.horizontalAdvance(self.text()) + self.PAD_R + 8
        h = max(self.ICON, fm.height()) + 2 * 10
        return QSize(int(w), int(h))

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect())
        g = QLinearGradient(0.0, 0.0, max(1.0, r.width()), 0.0)   # 深色渐变底
        g.setColorAt(0.0, QColor(self.GRAD[0]))
        g.setColorAt(0.5, QColor(self.GRAD[1]))
        g.setColorAt(1.0, QColor(self.GRAD[2]))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 16, 16)
        if not self.isEnabled():
            p.setOpacity(0.45)
        t = self._t
        fm = QFontMetrics(self.font())
        cy = r.center().y()
        # 图标：右移 5px，30° → 90°
        ic = float(self.ICON)
        cx = self.PAD_L + ic / 2.0 + 5.0 * t
        p.save()
        p.translate(cx, cy)
        p.rotate(30.0 + 60.0 * t)
        p.drawPixmap(QRectF(-ic / 2.0, -ic / 2.0, ic, ic), self._icon, QRectF(self._icon.rect()))
        p.restore()
        # 文字：右移 7px
        p.setPen(QColor("#FFFFFF"))
        tx = self.PAD_L + ic + self.GAP + 7.0 * t
        p.drawText(QRectF(tx, r.top(), max(10.0, r.right() - tx), r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())


class ToggleSwitch(MiniSwitch):
    """旧名字（组内裁剪框位置一致 / 导出清单等处在用），外观已统一到 MiniSwitch。"""


class LoaderBar(QWidget):
    """导出进度条：浅底 + 1px 蓝边，里面填蓝色 45° 斜条纹。

    样式照给的那段 loaderBar：宽 160/0.707 ≈ 226、高 10、外圆角 10、内圆角 5，
    #F9F9F9 底 + #006DFE 边，条纹 30px #0031F2 + 10px #006DFE 循环。
    宽度跟随真实导出进度（那段 CSS 是无限空转，这里改成有意义地走）。
    """

    W, H = 226, 10
    BG = QColor("#F9F9F9")
    EDGE = QColor("#006DFE")
    DARK = QColor("#0031F2")
    LIGHT = QColor("#006DFE")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setToolTip("导出进度")
        self._value = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.valueChanged.connect(self._on_tick)

    def _on_tick(self, value):
        self._value = float(value)
        self.update()

    # -------------------------------------------------- QProgressBar 那套接口
    def setValue(self, value):
        target = max(0.0, min(100.0, float(value)))
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(target)
        self._anim.start()

    def value(self):
        return int(round(self._value))

    def setRange(self, _a, _b):
        pass

    def setTextVisible(self, _on):
        pass

    def reset(self):
        self._anim.stop()
        self._value = 0.0
        self.update()

    # -------------------------------------------------- 画
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        radius = r.height() / 2.0
        p.setPen(QPen(self.EDGE, 1))
        p.setBrush(self.BG)
        p.drawRoundedRect(r, radius, radius)
        w = (self.width() - 2.0) * max(0.0, min(1.0, self._value / 100.0))
        if w <= 0.5:
            return
        period = 40.0 / (2 ** 0.5)          # 40px 一个循环，沿 45° 轴
        g = QLinearGradient(r.left(), r.top(), r.left() + period, r.top() + period)
        g.setSpread(QGradient.RepeatSpread)
        g.setColorAt(0.0, self.DARK)
        g.setColorAt(0.75, self.DARK)
        g.setColorAt(0.75, self.LIGHT)
        g.setColorAt(1.0, self.LIGHT)
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(r.left(), r.top(), w, r.height()), radius, radius)
        p.restore()


class RingDot(QWidget):
    """收音机那种空心圆环：收起时粉色，展开时白色（压在渐变底上）。"""

    def __init__(self, color="#A98BE8", parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self._color = QColor(color)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(1.5, 1.5, self.width() - 3.0, self.height() - 3.0)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._color, 2))
        p.drawEllipse(r)


class LockDot(QCheckBox):
    """卡片标题左边的小锁（照 Uiverse 的 lock 开关复刻，2026-09-26 用户指定）。

    原稿是 45×45 的圆角方块：灰底 `rgb(80,80,80)`，里面一把白锁；勾上变紫底
    `rgb(167,71,245)`，锁梁绕右侧转 `rotateY(150deg)` 打开并 `translateX(3px)`；
    按下整块缩到 0.9；所有过渡都是 `all 0.3s`。

    尺寸：整块等比缩到 `BOX`（默认 20，跟它替换掉的 `RingDot` 完全同大），
    比例全部写在 45×45 的设计坐标里，画之前统一 scale —— 以后想改大小只动 BOX。
    勾选态 = 卡片展开（点它跟点标题行一个效果）。
    """

    DESIGN = 45.0               # 原稿尺寸，所有比例都按它算
    BOX = 20.0                  # 实际显示大小（跟原来的小圈一样）
    RADIUS = 15.0               # .lock-label 圆角
    BG_OFF = QColor(80, 80, 80)
    BG_ON = QColor(167, 71, 245)
    TILT = -10.0                # .lock-wrapper 恒定的 -10°
    SW, SH = 14.0, 9.0          # .shackle 的宽 / 高
    STROKE = 3.0                # 锁梁线宽（原稿 3px 边框）
    BODY = 15.0                 # .lock-body 宽度
    FLIP = 150.0                # 勾上时锁梁转的角度
    SHIFT = 3.0                 # 勾上时的 translateX
    # lock-body 那个 SVG 的路径（28×28，evenodd 挖出锁孔）
    KEYHOLE = ("M0 5C0 2.23858 2.23858 0 5 0H23C25.7614 0 28 2.23858 28 5V23C28 25.7614 "
               "25.7614 28 23 28H5C2.23858 28 0 25.7614 0 23V5ZM16 13.2361C16.6137 12.6868 "
               "17 11.8885 17 11C17 9.34315 15.6569 8 14 8C12.3431 8 11 9.34315 11 11C11 "
               "11.8885 11.3863 12.6868 12 13.2361V18C12 19.1046 12.8954 20 14 20C15.1046 "
               "20 16 19.1046 16 18V13.2361Z")

    _body_cache = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(self.BOX), int(self.BOX))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点一下展开 / 收起")
        self._t = 1.0 if self.isChecked() else 0.0        # 0=关（灰）→1=开（紫）
        self._press = 0.0                                 # :active 的 0.9 缩放
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(300)                       # 原稿 all 0.3s
        curve = QEasingCurve()
        curve.setType(QEasingCurve.BezierSpline)
        curve.addCubicBezierSegment(QPointF(0.25, 0.1), QPointF(0.25, 1.0), QPointF(1.0, 1.0))
        self._anim.setEasingCurve(curve)
        self._anim.valueChanged.connect(self._tick)
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(300)
        self._press_anim.setEasingCurve(curve)
        self._press_anim.valueChanged.connect(self._tick_press)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self):
        return QSize(int(self.BOX), int(self.BOX))

    def hitButton(self, pos):
        """整块都能点（QCheckBox 默认只有指示器那一小块能点）。"""
        return self.rect().contains(pos)

    # -------------------------------------------------- 动画
    def _tick(self, value):
        self._t = float(value)
        self.update()

    def _tick_press(self, value):
        self._press = float(value)
        self.update()

    def _on_toggled(self, on):
        self._to(1.0 if on else 0.0)

    def _to(self, target, animate=True):
        target = float(target)
        self._anim.stop()
        if (not animate) or (not self.isVisible()):     # 建界面时设初值，别演一遍动画
            self._t = target
            self.update()
            return
        self._anim.setStartValue(float(self._t))
        self._anim.setEndValue(target)
        self._anim.start()

    def set_on(self, on, animate=True):
        """由外部（卡片展开/收起）直接对齐状态。

        注意不能只靠 toggled 信号：`card.py` 里是挡着信号设的勾选态（防递归），
        只发信号的写法会让这 8 个锁一直停在初始样子（实测踩过）。
        """
        on = bool(on)
        if self.isChecked() != on:
            self.blockSignals(True)
            self.setChecked(on)
            self.blockSignals(False)
        self._to(1.0 if on else 0.0, animate=animate)

    def _press_to(self, value):
        self._press_anim.stop()
        if not self.isVisible():
            self._press = float(value)
            return
        self._press_anim.setStartValue(float(self._press))
        self._press_anim.setEndValue(float(value))
        self._press_anim.start()

    def mousePressEvent(self, ev):
        self._press_to(1.0)                     # .lock-label:active → scale(0.9)
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._press_to(0.0)
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev):
        self._press_to(0.0)
        super().leaveEvent(ev)

    # -------------------------------------------------- 画
    def _make_body(self, px):
        pm = QPixmap(int(px), int(px))
        pm.fill(Qt.transparent)
        if QSvgRenderer is not None:
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28">'
                   '<path fill-rule="evenodd" clip-rule="evenodd" fill="#FFFFFF" d="%s"/>'
                   '</svg>' % self.KEYHOLE)
            r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            r.render(p)
            p.end()
        return pm

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        d = self.DESIGN
        s = (float(self.width()) / d) * (1.0 - 0.1 * self._press)
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.scale(s, s)
        p.translate(-d / 2.0, -d / 2.0)
        # 圆角方底（0.3s 颜色过渡）
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(self.BG_OFF, self.BG_ON, self._t))
        p.drawRoundedRect(QRectF(0.0, 0.0, d, d), self.RADIUS, self.RADIUS)
        # wrapper：整体 -10°
        p.save()
        p.translate(d / 2.0, d / 2.0)
        p.rotate(self.TILT)
        p.translate(-d / 2.0, -d / 2.0)
        ox = (d - self.BODY) / 2.0                        # 15
        oy = (d - (self.SH + self.BODY)) / 2.0            # 10.5
        # 锁体（SVG，白）
        if LockDot._body_cache is None:
            LockDot._body_cache = self._make_body(self.BODY * 8.0)
        p.drawPixmap(QRectF(ox, oy + self.SH, self.BODY, self.BODY),
                     LockDot._body_cache, QRectF(LockDot._body_cache.rect()))
        # 锁梁：倒 U（描边 3，圆角半圆）
        w, h, st = self.SW, self.SH, self.STROKE
        rr = (w - st) / 2.0
        sx = ox + (self.BODY - w) / 2.0                   # 在锁体宽度里居中
        cy = oy + st / 2.0 + rr
        path = QPainterPath()
        path.moveTo(sx + st / 2.0, oy + h)
        path.lineTo(sx + st / 2.0, cy)
        path.arcTo(QRectF(sx + st / 2.0, cy - rr, 2.0 * rr, 2.0 * rr), 180.0, -180.0)
        path.lineTo(sx + w - st / 2.0, oy + h)
        ca = math.cos(math.radians(self.FLIP * self._t))  # rotateY → 横向 cos 投影
        if abs(ca - 1.0) > 1e-4:
            # CSS 是 `rotateY(150deg) translateX(3px)` + `origin: right`：
            # 先按元素本地坐标平移 3px，再绕**原来的**右边缘做横向投影。
            # （实测：把 3px 并进旋转原点会多偏 8 个设计单位，锁梁会跑出方块）
            px = sx + w                                   # transform-origin: right
            tr = QTransform()
            tr.translate(px, 0.0)
            tr.scale(ca, 1.0)
            tr.translate(-px, 0.0)
            tr.translate(self.SHIFT * self._t, 0.0)
            p.setTransform(tr, True)                      # setTransform(tr, True) = 先应用 tr
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#FFFFFF"), st, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
        p.drawPath(path)
        p.restore()


class HeadRow(QFrame):
    """模块标题那一行：整行都能点开 / 收起。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modHead")
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class SoftField(QPushButton):
    """软底只读字段（点一下弹菜单），长得跟示意图里的圆角输入框一样。"""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("softField")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(34)


class _FieldEdit(QLineEdit):
    """带焦点通知的输入框，用来驱动标签浮上浮下。"""

    focusChanged = Signal(bool)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.focusChanged.emit(True)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.focusChanged.emit(False)


class FloatField(QWidget):
    """浅灰圆角输入框 + 会浮上去的小标签（照用户给的 formField 样式做）。

    - 框里有内容 / 正在输入时：标签浮到框上方，变小
    - 框里是空的：标签贴在框里当占位文字
    - 允许留空的字段（比如标尺长度、字号），留空 = 自动（值按 0 算）
    """

    valueChanged = Signal(float)

    def __init__(self, label="", decimals=1, minimum=0.0, maximum=1000000.0,
                 value=None, allow_empty=False, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(46)
        self._decimals = int(decimals)
        self._min = float(minimum)
        self._max = float(maximum)
        self._allow_empty = bool(allow_empty or value is None)
        self._value = 0.0
        self.edit = _FieldEdit(self)
        self.edit.setObjectName("field")
        self.lab = QLabel(label, self)
        self.lab.setObjectName("fieldLab")
        self.lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._f_rest = QFont(self.font())
        self._f_rest.setPixelSize(12)
        self._f_float = QFont(self.font())
        self._f_float.setPixelSize(10)
        self._f_float.setWeight(QFont.DemiBold)
        self.edit.textChanged.connect(lambda _t: self._place())
        self.edit.focusChanged.connect(lambda _on: self._place())
        self.edit.editingFinished.connect(self._commit)
        if value is not None:
            self.setValue(float(value), emit=False)
        self._place()

    # -------------------------------------------------- 布局
    def resizeEvent(self, _ev):
        self._place()

    def mousePressEvent(self, _ev):
        self.edit.setFocus()

    def _place(self):
        box_h = 30
        top = max(0, self.height() - box_h)
        self.edit.setGeometry(0, top, self.width(), box_h)
        floating = bool(self.edit.text().strip()) or self.edit.hasFocus()
        if floating:
            self.lab.setFont(self._f_float)
            self.lab.setStyleSheet("color:#5B5BD6;")
            self.lab.adjustSize()
            self.lab.move(6, max(0, top - self.lab.height() - 4))
        else:
            self.lab.setFont(self._f_rest)
            self.lab.setStyleSheet("color:#8A8AA3;")
            self.lab.adjustSize()
            self.lab.move(14, top + (box_h - self.lab.height()) // 2)

    # -------------------------------------------------- 数值
    def text(self):
        return self.edit.text().strip()

    def is_empty(self):
        return not self.text()

    def value(self):
        """留空时按 0 返回（对长度/字号来说 0 就是「自动」）。"""
        return 0.0 if self.is_empty() else self._value

    def fmt(self, v):
        return ("%%.%df" % self._decimals) % float(v)

    def setValue(self, v, emit=True):
        v = max(self._min, min(self._max, float(v)))
        self._value = v
        self.edit.setText(self.fmt(v))
        self._place()
        if emit and not self.signalsBlocked():
            self.valueChanged.emit(v)

    def clearValue(self):
        """清空 = 自动。"""
        self._value = 0.0
        self.edit.setText("")
        self._place()
        if not self.signalsBlocked():
            self.valueChanged.emit(0.0)

    @staticmethod
    def _parse(raw):
        keep = "".join(ch for ch in (raw or "") if ch.isdigit() or ch in ".-")
        if not keep or keep in ("-", ".", "-."):
            return None
        try:
            return float(keep)
        except ValueError:
            return None

    def _commit(self):
        raw = self.text()
        v = self._parse(raw)
        if v is None:
            if self._allow_empty and not raw:
                self.clearValue()
            else:
                self.edit.setText(self.fmt(self._value))     # 不接受空 → 还原
                self._place()
            return
        v = max(self._min, min(self._max, v))
        changed = abs(v - self._value) > 1e-9
        self._value = v
        self.edit.setText(self.fmt(v))
        self._place()
        if changed and not self.signalsBlocked():
            self.valueChanged.emit(v)
