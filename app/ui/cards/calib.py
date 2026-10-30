# -*- coding: utf-8 -*-
"""右栏功能卡片：标定

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

    # ---- 标定
    c = card("标定", "µm/像素", module=True)
    win.lbl_calib = QLabel("未载入")
    win.lbl_calib.setObjectName("muted")
    win.lbl_calib.setWordWrap(True)
    c.body.addWidget(win.lbl_calib)
    # 画线标定：只有图片格式（png/tif/jpg/bmp）才显示，下机文件自带标定
    win.cal_tool = QWidget()
    ctl = QVBoxLayout(win.cal_tool)
    ctl.setContentsMargins(0, 0, 0, 0)
    ctl.setSpacing(6)
    win.btn_line = BrutalButton("在图上画线", compact=True)
    win.btn_line.setCheckable(True)
    win.btn_line.setToolTip("点一下进入画线：在图上对着标尺点两个点")
    win.btn_line.toggled.connect(win.on_line_mode)
    ctl.addWidget(win.btn_line)
    # 自动识别跑完后才出现：一键把识别到的线段预填进画线模式（规格书 5.4.6）
    win.btn_detect_fix = BrutalButton("识别不对，手动框", compact=True)
    win.btn_detect_fix.setToolTip("把识别到的线段预填进来，拖两端微调即可")
    win.btn_detect_fix.clicked.connect(win.on_detect_fix)
    win.btn_detect_fix.setVisible(False)
    ctl.addWidget(win.btn_detect_fix)
    # 多候选待确认（规格书 5.4.5）：只有候选之间差得太多时才出现
    win.cand_box = QWidget()
    cand_lay = QVBoxLayout(win.cand_box)
    cand_lay.setContentsMargins(0, 0, 0, 0)
    cand_lay.setSpacing(4)
    win.lbl_cand = QLabel("识别到多条候选标尺线")
    win.lbl_cand.setObjectName("muted")
    win.lbl_cand.setWordWrap(True)
    cand_lay.addWidget(win.lbl_cand)
    win.cand_lay = cand_lay
    win.cand_box.setVisible(False)
    ctl.addWidget(win.cand_box)
    win.field_line_um = FloatField("这条线代表 (µm)", decimals=2, minimum=0.0001,
                                    maximum=100000.0, allow_empty=True,
                                    value=win.settings.__dict__.get("line_um") or None)
    win.field_line_um.setToolTip("先画线，再填这条线代表多少微米，然后点下面两个按钮")
    ctl.addWidget(win.field_line_um)
    win.lbl_line = QLabel("还没画线")
    win.lbl_line.setObjectName("muted")
    ctl.addWidget(win.lbl_line)
    row_line = QHBoxLayout()
    row_line.setSpacing(6)
    b_g = BrutalButton("应用到本组", compact=True)
    b_g.clicked.connect(lambda: win.apply_line_calib(False))
    b_a = BrutalButton("应用到所有", compact=True)
    b_a.setToolTip("所有图片格式的图都用这个标定（下机文件不动）")
    b_a.clicked.connect(lambda: win.apply_line_calib(True))
    row_line.addWidget(b_g)
    row_line.addWidget(b_a)
    ctl.addLayout(row_line)
    c.body.addWidget(win.cal_tool)
    return c
