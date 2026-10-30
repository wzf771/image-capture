# -*- coding: utf-8 -*-
"""右栏功能卡片：通道与颜色

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

    # ---- 通道与颜色
    c = card("通道与颜色", "只影响显示", module=True)
    # 多通道叠加方式（2026-09-26）：加法 = 完全叠加（弱通道不会被吃掉，默认）；
    # 最大强度 = 老行为。给个开关是为了万一加法不合适能一键切回去。
    win.cb_merge_mode = QComboBox()
    win.cb_merge_mode.setObjectName("field")
    win.cb_merge_mode.addItems(["完全叠加（加法）", "最大强度（旧）"])
    win.cb_merge_mode.setCurrentIndex(
        0 if str(getattr(win.settings, "merge_mode", "add")).lower() != "max" else 1)
    win.cb_merge_mode.setToolTip(
        "加法：每个通道的信息都留下，重叠区叠成混合色（红+绿=黄），重叠很亮时会顶到白\n"
        "最大强度：旧算法，谁亮谁覆盖 —— 某路在 R/G/B 三路都弱时会被整路吃掉")
    win.cb_merge_mode.currentIndexChanged.connect(win.on_merge_mode)
    c.body.addLayout(pair("叠加方式", win.cb_merge_mode))
    # 逐帧归一化（P0-4 3.25.3）：只有时间序列才显示这一组控件
    win.range_tool = QWidget()
    rt = QVBoxLayout(win.range_tool)
    rt.setContentsMargins(0, 0, 0, 0)
    rt.setSpacing(5)
    win.cb_range_mode = QComboBox()
    win.cb_range_mode.setObjectName("field")
    win.cb_range_mode.addItems(["统一区间（现状）", "逐帧自动", "按参考帧"])
    win.cb_range_mode.setToolTip("时间序列的光漂白：后段会越来越黑，这里可以逐帧修正显示区间")
    win.cb_range_mode.currentIndexChanged.connect(win.on_range_mode)
    rt.addLayout(pair("区间模式", win.cb_range_mode))
    win.ed_p_lo = FloatField("黑点分位", decimals=1, minimum=0.0, maximum=100.0,
                             allow_empty=True, value=55.0)
    win.ed_p_hi = FloatField("白点分位", decimals=1, minimum=0.0, maximum=100.0,
                             allow_empty=True, value=99.8)
    for w in (win.ed_p_lo, win.ed_p_hi):
        w.setToolTip("算逐帧区间用的分位数，默认 55 / 99.8（与自动区间一致）")
        w.valueChanged.connect(win.on_range_pct)
    rt.addLayout(pair("分位", win.ed_p_lo))
    rt.addLayout(pair("", win.ed_p_hi))
    win.sp_ref = QSpinBox()
    win.sp_ref.setObjectName("field")
    win.sp_ref.setRange(1, 1)
    win.sp_ref.setToolTip("只有「按参考帧」用得上：以这一帧的区间宽度为基准")
    win.sp_ref.valueChanged.connect(win.on_range_ref)
    rt.addLayout(pair("参考帧", win.sp_ref))
    win.lbl_range_warn = QLabel("")
    win.lbl_range_warn.setObjectName("muted")
    win.lbl_range_warn.setWordWrap(True)
    rt.addWidget(win.lbl_range_warn)
    win.range_tool.setVisible(False)
    c.body.addWidget(win.range_tool)
    win.chan_layout = QVBoxLayout()
    win.chan_layout.setSpacing(5)
    c.body.addLayout(win.chan_layout)
    return c
