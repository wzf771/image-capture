# -*- coding: utf-8 -*-
"""MagnifyingDock —— Bencho「Magnifying dock」的 Qt 移植（MIT，bencho.dev/licence）。

原组件是 React + CSS 变量；这里是同一套**行为**的 QPainter 重写：

  · 放大是**按距离衰减**的（raised cosine），不是只放大鼠标下面那一个；
  · 事件挂在整条 bar 上（不是每个 item 各自 onMouseEnter），索引由「离指针最近的
    那个 item 中心」量出来 —— 触摸沿 dock 滑过时也能连续响应；
  · 放大只作用于 glyph，不作用于按钮本身，圆点与标签保持自己的尺寸和位置；
  · 全 dock 只有**一个**会移动的 tooltip，滑到指针所在项、宽度过渡到新词；
  · 唯一的常驻标记是活动项下面的小圆点。

── 令牌映射（原 CSS 读 --fill-on / --pane / --ink …，本项目没有 CSS 变量）──
原组件的变量都是「同一个东西的不同叫法」，这里逐条对到项目已有值；项目里没有对应物
的（玻璃那组 --g-*）就地定义在本组件，不外泄成全局：

    --pane        → CARD 加一点透明（项目「面」的颜色）
    --pane-edge   → theme.LINE
    --ink         → theme.TEXT
    --ink-rgb     → "33,30,24"（--ink 的三个裸数字，rgba() 要用）
    --on-ink      → "#FFFFFF"
    --fill-on     → theme.TEXT（tooltip 底 = 深色墨）
    --fill-slab   → "#FFFFFF"（tooltip 字）
    --font-ui     → theme.FONT（项目正文字体）
    --shadow-rgb  → "33,30,24"
    --try-edge    → theme.LINE（只在对比板上用，这里保持同一个值）
    --g-blur / --g-sat / --g-bright / --g-edge-* / --g-lift / --g-spec
                  → 项目没有玻璃材质，按组件自己的观感就地定义（见下面的 TOKENS）

Qt 没有 backdrop-filter，玻璃用「半透明面 + 顶部高光 + 柔和投影」近似；
数值来自原 CSS 注释里那三段（rim / spec / lift），不是随手挑的。
"""
from __future__ import annotations

import math

from PySide6.QtCore import (QByteArray, QEasingCurve, QPointF, QRectF, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                           QPen)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui import theme

# ── 令牌（见模块头注释里的映射表）─────────────────────────────
TOKENS = {
    # 「面」不用纯白：项目里没有白卡，面板底是 #F0EEE9、控件底是 #E8E5DE，
    # 取两者之间再亮一点，dock 才像是这块界面里的东西
    "pane": QColor(250, 247, 242, 245),
    "pane_edge": QColor(33, 30, 24, 22),         # theme.LINE
    "ink": QColor("#000000"),                   # 常态图标：次级文字色
    "ink_strong": QColor("#000000"),            # 近处 / 活动项：正文色
    "ink_rgb": "33,30,24",                       # --ink 的裸数字
    "on_ink": QColor("#FFFFFF"),
    "fill_on": QColor(theme.PRIMARY),            # tooltip 底：强调色
    "fill_slab": QColor("#FFFFFF"),              # tooltip 字
    "dot": QColor(theme.PRIMARY),                # 活动圆点：强调色
    "danger": QColor("#B4533F"),                 # 备用（未使用）
    "danger_soft": QColor("#C08B7E"),
    "toggle": QColor("#2E7D78"),                 # 收起 / 展开：青绿，醒目又不与琥珀抢
    "toggle_soft": QColor("#7FAFAA"),
    "font_ui": theme.FONT,                       # 项目正文字体
    # 玻璃组：项目没有对应材质，就地定义（不泄漏成全局样式）
    "g_blur": 18, "g_sat": 130, "g_bright": 104,
    "g_edge_hi": 0.55, "g_edge_lo": 0.10, "g_edge_far": 0.18,
    "g_lift": 0.16, "g_spec": 0.65,
    "shadow_rgb": "33,30,24",
    "try_edge": QColor(33, 30, 24, 30),
}

# ── 代码里自带的五个图标（Lucide，MIT）；之后逐个替换 ──────────
_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='{c}' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
        "{body}</svg>")

ICONS = {
    # 右栏五个标签（用户提供，Lucide，MIT）
    "crop": ("<path d='M8 3H5a2 2 0 0 0-2 2v3'/><path d='M21 8V5a2 2 0 0 0-2-2h-3'/>"
             "<path d='M3 16v3a2 2 0 0 0 2 2h3'/><path d='M16 21h3a2 2 0 0 0 2-2v-3'/>"),
    "ruler": ("<path d='M10 15v-3'/><path d='M14 15v-3'/><path d='M18 15v-3'/>"
              "<path d='M2 8V4'/><path d='M22 6H2'/><path d='M22 8V4'/><path d='M6 15v-3'/>"
              "<rect x='2' y='12' width='20' height='8' rx='2'/>"),
    "channel": ("<path d='M10 5h11'/><path d='M10 12h11'/><path d='M10 19h11'/>"
                "<path d='m3 10 3-3-3-3'/><path d='m3 20 3-3-3-3'/>"),
    "process": ("<path d='M16 12v4'/><path d='M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2'/>"
                "<path d='M17 6a2 2 0 011.414.586l3 3A2 2 0 0122 11v8a2 2 0 01-2 2H4a2 2 0 01-2-2v-8"
                "a2 2 0 01.586-1.414l3-3A2 2 0 017 6z'/><path d='M2 14h20'/><path d='M8 12v4'/>"),
    "measure": ("<rect width='8' height='4' x='8' y='2' rx='1'/>"
                "<path d='M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-.5'/>"
                "<path d='M16 4h2a2 2 0 0 1 1.73 1'/><path d='M8 18h1'/>"
                "<path d='M21.378 12.626a1 1 0 0 0-3.004-3.004l-4.01 4.012a2 2 0 0 0-.506.854"
                "l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506z'/>"),
    # 视图切换三个按钮（用户提供，Lucide，MIT）
    "scissors": ("<circle cx='6' cy='6' r='3'/><path d='M8.12 8.12 12 12'/>"
                 "<path d='M20 4 8.12 15.88'/><circle cx='6' cy='18' r='3'/>"
                 "<path d='M14.8 14.8 20 20'/>"),
    "scan_barcode": ("<path d='M3 7V5a2 2 0 0 1 2-2h2'/><path d='M17 3h2a2 2 0 0 1 2 2v2'/>"
                     "<path d='M21 17v2a2 2 0 0 1-2 2h-2'/><path d='M7 21H5a2 2 0 0 1-2-2v-2'/>"
                     "<path d='M8 7v10'/><path d='M12 7v10'/><path d='M17 7v10'/>"),
    "dashed_x": ("<path d='M14 21h1'/><path d='M14 3h1'/><path d='M19 3a2 2 0 012 2'/>"
                 "<path d='M21 14v1'/><path d='M21 19a2 2 0 01-2 2'/><path d='M21 9v1'/>"
                 "<path d='M3 14v1'/><path d='M3 9v1'/><path d='M5 21a2 2 0 01-2-2'/>"
                 "<path d='M5 3a2 2 0 00-2 2'/><path d='m9 15 6-6'/><path d='M9 21h1'/>"
                 "<path d='M9 3h1'/><path d='m9 9 6 6'/>"),
    "circle_play": ("<circle cx='12' cy='12' r='10'/>"
                    "<path d='M9 9.003a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718"
                    "l-4.997 2.997A1 1 0 0 1 9 14.996z'/>"),
    # 收起 / 展开：Lucide circle-chevron-right / -left
    "chev_right": "<circle cx='12' cy='12' r='10'/><path d='m10 8 4 4-4 4'/>",
    "chev_left": "<circle cx='12' cy='12' r='10'/><path d='m14 16-4-4 4-4'/>",
}


def paint_svg(painter: QPainter, icon_key: str, rect: QRectF, color: QColor):
    """按 24×24 viewBox 把一个 Lucide 图标画进 rect（其他地方也能复用）。"""
    svg = _SVG.format(c=color.name(), body=ICONS.get(icon_key) or next(iter(ICONS.values())))
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if r.isValid():
        r.render(painter, rect)


class DockTip(QWidget):
    """窗口级浮层：dock 上方的悬停文字。挂在主窗口上，所以能画到 dock 的矩形外面。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._text = ""

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(TOKENS["fill_on"])
        p.drawRoundedRect(QRectF(self.rect()), self.height() / 2, self.height() / 2)
        p.setPen(TOKENS["fill_slab"])
        p.setFont(theme.ui_font(theme.SIZE_CAP))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)

    def show_for(self, text, anchor_x: float, bar_top: float):
        fm = QFontMetrics(theme.ui_font(theme.SIZE_CAP))
        w = fm.horizontalAdvance(text) + 22
        h = 22
        self._text = text
        self.resize(int(w), h)
        self.move(int(anchor_x - w / 2), int(bar_top - h - 2))
        if not self.isVisible():
            self.show()
        self.raise_()
        self.update()


class MagnifyingDock(QWidget):
    """距离衰减放大的 dock。点击发 `activated(key)`。"""

    activated = Signal(str)

    def __init__(self, parent=None, items=None, magnify=1.30, spread=2, lift=7,
                 labels=True, fill=True,
                 item=40, gap=10, pad_x=10, pad_y=8, tip_h=22, tip_gap=2,
                 radius=22):
        super().__init__(parent)
        # items: [(key, label, icon_key), ...]
        self._items = list(items or [])
        self._magnify = float(magnify)
        self._spread = int(spread)
        self._lift = float(lift)
        self._labels = bool(labels)
        self._fill = bool(fill)
        self._tip = None
        self._item = int(item)
        self._gap = int(gap)
        self._pad_x = int(pad_x)
        self._pad_y = int(pad_y)
        self._tip_h = int(tip_h)
        self._tip_gap = int(tip_gap)
        self._radius = int(radius)

        self._active = 0
        self._hover_i = None
        self._pos = 0.0
        self._amp = 0.0
        self._src = self._dst = 0.0
        self._amp_src = self._amp_dst = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFixedHeight(self._bar_h())
        if self._fill:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            self.setFixedWidth(self.sizeHint().width())

    # ------------------------------------------------------------ 尺寸
    def _bar_h(self) -> int:
        return self._item + 2 * self._pad_y

    def sizeHint(self) -> QSize:
        w = 2 * self._pad_x + len(self._items) * self._item + \
            max(0, len(self._items) - 1) * self._gap
        return QSize(w, self._bar_h())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _bar_rect(self) -> QRectF:
        return QRectF(0, 0, self.width(), self._bar_h())

    def _item_x(self, i: int) -> float:
        """铺满时只拉开间距（图标与格子大小不变），否则按固定 gap 排。"""
        if self._fill and len(self._items) > 1:
            span = max(0.0, self.width() - 2 * self._pad_x - self._item)
            return self._pad_x + i * span / (len(self._items) - 1)
        return self._pad_x + i * (self._item + self._gap)

    def set_active(self, key: str | None = None, index: int | None = None):
        if index is None and key is not None:
            index = next((i for i, it in enumerate(self._items) if it[0] == key), None)
        if index is not None and 0 <= index < len(self._items):
            self._active = index
            self.update()

    def active_key(self):
        return self._items[self._active][0] if self._items else None

    # ------------------------------------------------------------ 交互
    def _at(self, x: float):
        """离指针最近的 item（原组件就是量出来的，不是按索引算的）。"""
        if not self._items:
            return None
        best, gap = 0, 1e9
        for i in range(len(self._items)):
            c = self._item_x(i) + self._item / 2.0
            d = abs(x - c)
            if d < gap:
                gap, best = d, i
        return best

    def _tip_to(self, i):
        """把浮层挪到第 i 个格子上方（None = 收起）。"""
        if not self._labels:
            return
        if i is None:
            if self._tip is not None:
                self._tip.hide()
            return
        win = self.window()
        if self._tip is None or self._tip.parent() is not win:
            self._tip = DockTip(win)
        bar = self._bar_rect()
        x = self._item_x(i) + self._item / 2.0
        gx = self.mapTo(win, QPointF(x, 0)).x()
        gy = self.mapTo(win, QPointF(0, bar.top())).y()
        self._tip.show_for(self._items[i][1], gx, gy)

    def _to(self, i):
        self._tip_to(i if i is not None else None)
        if i is None:
            self._amp_src, self._amp_dst = self._amp, 0.0
            self._src, self._dst = self._pos, self._pos
        else:
            self._src, self._dst = self._pos, float(i)
            self._amp_src, self._amp_dst = self._amp, 1.0
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_anim(self, t):
        t = float(t)
        self._pos = self._src + (self._dst - self._src) * t
        self._amp = self._amp_src + (self._amp_dst - self._amp_src) * t
        self.update()

    def mouseMoveEvent(self, ev):
        i = self._at(ev.position().x())
        if i != self._hover_i:
            self._hover_i = i
            self._to(i)
        super().mouseMoveEvent(ev)

    def enterEvent(self, ev):
        self._hover_i = self._at(ev.position().x())
        self._to(self._hover_i)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover_i = None
        self._to(None)
        if self._tip is not None:
            self._tip.hide()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        i = self._at(ev.position().x())
        if i is not None and ev.button() == Qt.LeftButton:
            self._active = i
            self.update()
            self.activated.emit(self._items[i][0])
        super().mousePressEvent(ev)

    # ------------------------------------------------------------ 曲线
    def _falloff(self, d: float) -> float:
        """raised cosine，越过 reach 归零（原组件注释里说明的那条曲线）。"""
        if d > self._spread:
            return 0.0
        return (1.0 + math.cos(math.pi * d / (self._spread + 1))) / 2.0

    # ------------------------------------------------------------ 画
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        bar = self._bar_rect()
        r = min(self._radius, bar.height() / 2.0)

        # —— 玻璃面：面 + 1px rim + 顶部高光 + 柔和投影（原 CSS 的三层厚度）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(33, 30, 24, int(255 * TOKENS["g_lift"] * 0.22)))
        p.drawRoundedRect(bar.adjusted(-1, 1, 1, 4), r, r)
        p.setBrush(TOKENS["pane"])
        p.drawRoundedRect(bar, r, r)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(TOKENS["pane_edge"], 1.0))
        p.drawRoundedRect(bar.adjusted(0.5, 0.5, -0.5, -0.5), r - 0.5, r - 0.5)
        clip = QPainterPath()
        clip.addRoundedRect(bar.adjusted(1, 1, -1, -1), r - 1, r - 1)
        p.save()
        p.setClipPath(clip)
        p.setPen(QPen(QColor(255, 255, 255, int(255 * TOKENS["g_edge_hi"])), 1.0))
        p.drawLine(QPointF(bar.left() + 6, bar.top() + 1.2),
                   QPointF(bar.right() - 6, bar.top() + 1.2))
        p.restore()

        # —— 每个 item：只有 glyph 放大 + 抬起
        base_top = bar.top() + self._pad_y
        for i, item in enumerate(self._items):
            key, label, icon = item[0], item[1], item[2]
            tone = item[3] if len(item) > 3 else "ink"
            d = 99.0 if self._amp <= 0.02 else abs(i - self._pos)
            f = self._falloff(d) * self._amp
            scale = 1.0 + (self._magnify - 1.0) * f
            lift = self._lift * f
            x = self._item_x(i)

            # 不透明度：远处 0.42 → 相邻 0.66 → 指针正下方 1.0（原 CSS 的三档，连续插值）
            if d <= 1.0:
                op = 1.0 - 0.34 * max(0.0, d)
            elif d <= 2.0:
                op = 0.66 - 0.24 * (d - 1.0)
            else:
                op = 0.42
            tinted = tone in ("red", "toggle")
            if i == self._active and not tinted:
                op = 1.0
            elif tinted:
                op = 1.0 if d <= 1.0 else 0.88

            p.setOpacity(op)
            if tone == "toggle":
                glyph_color = TOKENS["toggle"]
            elif tone == "red":
                glyph_color = TOKENS["danger"] if d <= 1.0 else TOKENS["danger_soft"]
            else:
                glyph_color = TOKENS["ink_strong"] if (d <= 1.0 or i == self._active) else TOKENS["ink"]
            svg = _SVG.format(c=glyph_color.name(), body=ICONS.get(icon) or next(iter(ICONS.values())))
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            side = 15.0 * scale
            cx = x + self._item / 2.0
            cy = base_top + self._item / 2.0 - lift
            renderer.render(p, QRectF(cx - side / 2, cy - side / 2, side, side))

            if i == self._active and tone not in ("red", "toggle"):   # 活动圆点
                p.setOpacity(0.55)
                p.setPen(Qt.NoPen)
                p.setBrush(TOKENS["dot"])
                p.drawEllipse(QPointF(cx, base_top + self._item - 4), 1.5, 1.5)

        p.setOpacity(1.0)
