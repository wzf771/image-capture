# -*- coding: utf-8 -*-
"""右栏卡片通用的小部件助手（从 _build_right 的闭包里搬出来）。"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)


def plab(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    return lab


def cap(text):
    """浮在输入框上方的那种小标签。"""
    lab = QLabel(text)
    lab.setObjectName("fieldLab")
    from ui import theme
    f = theme.ui_font(theme.SIZE_CAP, weight=QFont.DemiBold)
    lab.setFont(f)
    lab.setStyleSheet("color:#000000;")
    return lab


def stack(label, widget, height=30):
    """小标签在上、控件在下（跟 FloatField 一个排法）。"""
    box = QVBoxLayout()
    box.setSpacing(4)
    box.addWidget(cap(label))
    widget.setFixedHeight(height)
    box.addWidget(widget)
    return box


def pair(label, widget, stretch=1):
    h = QHBoxLayout()
    h.setSpacing(6)
    h.addWidget(plab(label))
    h.addWidget(widget, stretch)
    return h


def cell(text, widget, height=30):
    """一格：小标签在上、控件在下，间距统一 4px。

    FloatField 自带浮动标签（46px 高、间距不同），这里把它关掉、改用外置标签，
    这样它和下拉框 / 数字框长得完全一样。
    """
    if hasattr(widget, "lab") and hasattr(widget.lab, "setVisible"):
        widget.lab.hide()
    widget.setFixedHeight(height)
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(cap(text))
    lay.addWidget(widget)
    return box


def two_col(w1, w2, text1, text2, hspace=8):
    """同一行、两列等宽。"""
    box = QWidget()
    g = QGridLayout(box)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(hspace)
    g.setVerticalSpacing(0)
    g.addWidget(cell(text1, w1), 0, 0)
    g.addWidget(cell(text2, w2), 0, 1)
    g.setColumnStretch(0, 1)
    g.setColumnStretch(1, 1)
    return box


def button_grid(buttons, cols=3, hspace=6, vspace=6):
    """按钮排成等宽的网格（不是流式换行）。"""
    from PySide6.QtWidgets import QSizePolicy
    box = QWidget()
    g = QGridLayout(box)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(hspace)
    g.setVerticalSpacing(vspace)
    for i, b in enumerate(buttons):
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        g.addWidget(b, i // cols, i % cols)
    for c in range(cols):
        g.setColumnStretch(c, 1)
    return box
