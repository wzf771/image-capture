# -*- coding: utf-8 -*-
"""右栏功能卡片：裁剪视野

从 main_window.py 拆出来（2026-09-22），只搬不改逻辑。
`build(win)` 负责搭界面并把控件挂到 win 上；动作处理仍在 MainWindow 里。
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

import paths
from core.model import CHANNEL_COLORS, FONTS, color_name
from ui.card import ClickLabel, card
from ui.cards._helpers import cap, pair, plab, stack
from ui.flow import FlowLayout
from ui.widgets import (BrutalButton, FlipSwitch, FloatField, RangeSlider, RingDot,
                        Switch, ToggleSwitch)


def build(win):

    # ---- 裁剪视野
    c = card("裁剪视野", "每组独立", module=True)
    win.f_w = FloatField("宽 (µm)", decimals=1, minimum=0.5, maximum=5000.0,
                          value=win.settings.crop_w)
    win.f_w.setToolTip("裁剪框宽度，单位微米")
    win.f_w.valueChanged.connect(win.on_crop_changed)
    win.f_h = FloatField("高 (µm)", decimals=1, minimum=0.5, maximum=5000.0,
                          value=win.settings.crop_h)
    win.f_h.setToolTip("裁剪框高度，单位微米")
    win.f_h.valueChanged.connect(win.on_crop_changed)
    win.chk_lock = QCheckBox("锁定 1:1 方框")
    win.chk_lock.setChecked(win.settings.lock_1to1)
    win.chk_lock.toggled.connect(win.on_lock_toggled)
    wh = QHBoxLayout()
    wh.setSpacing(8)
    wh.addWidget(win.f_w, 1)
    wh.addWidget(win.f_h, 1)
    c.body.addLayout(wh)
    chips = QWidget()
    cw = FlowLayout(chips, spacing=6)
    win.pill_lock = BrutalButton("1:1", compact=True)
    win.pill_lock.setCheckable(True)
    win.pill_lock.setChecked(win.chk_lock.isChecked())
    win.pill_lock.setToolTip("锁成正方形：改宽，高跟着变")
    win.pill_lock.clicked.connect(lambda: win.on_pill_lock(True))
    cw.addWidget(win.pill_lock)
    win.pill_free = BrutalButton("自由比例", compact=True)
    win.pill_free.setCheckable(True)
    win.pill_free.setChecked(not win.chk_lock.isChecked())
    win.pill_free.setToolTip("宽高各调各的，不限比例（长条形视野用这个）")
    win.pill_free.clicked.connect(lambda: win.on_pill_lock(False))
    cw.addWidget(win.pill_free)
    win.cb_tosmall = QComboBox()
    win.cb_tosmall.addItems(["补边", "跳过", "收缩"])
    win.cb_tosmall.setCurrentIndex(["pad", "skip", "shrink"].index(win.settings.too_small))
    win.cb_tosmall.currentIndexChanged.connect(win.on_any_setting)
    win.cb_tosmall.setToolTip("原图比裁剪框还小的时候怎么办")
    win.pill_tosmall = BrutalButton("视野不足：补边", compact=True)
    win.pill_tosmall.clicked.connect(win.on_pill_tosmall)
    cw.addWidget(win.pill_tosmall)
    c.body.addWidget(chips)
    b_all = BrutalButton("一键应用到所有组", compact=True)
    b_all.setToolTip("把当前这组的裁剪框大小套到所有组（位置各组自己调整，放不下就靠边）")
    b_all.clicked.connect(win.apply_box_to_all)
    c.body.addWidget(b_all)
    return c
