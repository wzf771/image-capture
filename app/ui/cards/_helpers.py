# -*- coding: utf-8 -*-
"""右栏卡片通用的小部件助手（从 _build_right 的闭包里搬出来）。"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout


def plab(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    return lab


def cap(text):
    """浮在输入框上方的那种小标签。"""
    lab = QLabel(text)
    lab.setObjectName("fieldLab")
    f = QFont(lab.font())
    f.setPixelSize(10)
    f.setWeight(QFont.DemiBold)
    lab.setFont(f)
    lab.setStyleSheet("color:#5B5BD6;")
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
