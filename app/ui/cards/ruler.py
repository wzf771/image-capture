# -*- coding: utf-8 -*-
"""右栏功能卡片：新标尺

从 main_window.py 拆出来（2026-09-22），只搬不改逻辑。
`build(win)` 负责搭界面并把控件挂到 win 上；动作处理仍在 MainWindow 里。
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
                               QWidget)

import paths
from core.model import CHANNEL_COLORS, FONTS, color_name
from ui.card import ClickLabel, card
from ui.cards._helpers import cap, pair, plab, stack
from ui.flow import FlowLayout
from ui.widgets import (BrutalButton, FlipSwitch, FloatField, RangeSlider, RingDot,
                        Switch, ToggleSwitch)


def _cell(text, widget):
    """一格：小标签在上、控件在下，间距统一 4px（FloatField 用外置标签，避免自带间距）。"""
    if isinstance(widget, FloatField):
        widget.lab.hide()
        widget.setFixedHeight(30)
    else:
        widget.setFixedHeight(30)
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(cap(text))
    lay.addWidget(widget)
    return box


def build(win):

    # ---- 新标尺（常开：成品上一定画标尺）
    c = card("新标尺", "自动取整值", module=True)
    body = c.body_widget

    # 长度：直接填数字；留空 = 自动（取 1 / 2 / 5 ×10ⁿ 的整值）
    win.field_len = FloatField(
        "长度 (µm)", decimals=2, minimum=0.0, maximum=10000.0, allow_empty=True,
        value=(win.settings.bar_length if win.settings.bar_length > 0 else None))
    win.field_len.setToolTip("填一个数字 = 标尺就这么长；留空 = 自动取整值")
    win.field_len.valueChanged.connect(win.on_any_setting)
    win.cb_pos = QComboBox()
    win.cb_pos.setObjectName("field")
    win.cb_pos.addItems(["右下角", "左下角", "右上角", "左上角", "自定义（图上拖）"])
    keys = ["br", "bl", "tr", "tl", "custom"]
    win.cb_pos.setCurrentIndex(keys.index(win.settings.bar_position)
                                if win.settings.bar_position in keys else 0)
    win.cb_pos.currentIndexChanged.connect(win.on_bar_position_changed)

    win.chk_text = QCheckBox(body)
    win.chk_text.setChecked(win.settings.bar_text)
    win.chk_text.toggled.connect(win.on_any_setting)
    win.chk_text.hide()
    win.chk_unit = QCheckBox(body)
    win.chk_unit.setChecked(win.settings.bar_show_unit)
    win.chk_unit.toggled.connect(win.on_any_setting)
    win.chk_unit.hide()

    win.cb_ticks = QComboBox()
    win.cb_ticks.addItems(["两端+6 等分", "只画两端", "不画刻度"])
    win.cb_ticks.setCurrentIndex(["ends6", "ends", "none"].index(win.settings.bar_ticks))
    win.cb_ticks.currentIndexChanged.connect(win.on_any_setting)

    win.cb_font = QComboBox()
    win.cb_font.setObjectName("field")
    win.cb_font.addItems(list(FONTS.keys()))
    if win.settings.bar_font in FONTS:
        win.cb_font.setCurrentText(win.settings.bar_font)
    win.cb_font.currentIndexChanged.connect(win.on_any_setting)

    win.field_size = FloatField(
        "字号 (%)", decimals=0, minimum=0.0, maximum=40.0, allow_empty=True,
        value=(win.settings.bar_font_size if win.settings.bar_font_size > 0 else None))
    win.field_size.setToolTip(
        "标尺文字大小，填的是「占成品宽度的百分比」；留空 = 默认 15.5%\n"
        "每张图按自己的成品尺寸单独算，所以各组标尺看起来一样大")
    win.field_size.valueChanged.connect(win.on_any_setting)

    win.field_thick = FloatField(
        "粗细 (%)", decimals=0, minimum=0.0, maximum=30.0, allow_empty=True,
        value=(win.settings.bar_thickness if win.settings.bar_thickness > 0 else None))
    win.field_thick.setToolTip(
        "标尺线粗细，占成品宽度的百分比；留空 = 默认 5%\n"
        "每张图按自己的成品尺寸单独算")
    win.field_thick.valueChanged.connect(win.on_any_setting)

    win.field_margin = FloatField(
        "边距 (%)", decimals=0, minimum=0.0, maximum=40.0, allow_empty=True,
        value=(win.settings.bar_margin if win.settings.bar_margin > 0 else None))
    win.field_margin.setToolTip("标尺离图边的距离，占成品宽度的百分比；留空 = 默认 15%")
    win.field_margin.valueChanged.connect(win.on_any_setting)

    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(10)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)

    # 长度：整行
    grid.addWidget(_cell("长度 (µm)", win.field_len), 0, 0, 1, 2)

    # 位置：整行（下拉 + 复位）
    pos_row = QHBoxLayout()
    pos_row.setSpacing(8)
    pos_row.addWidget(win.cb_pos, 1)
    b_reset_pos = BrutalButton("复位", compact=True)
    b_reset_pos.setToolTip("把标尺放回右下角默认位置")
    b_reset_pos.clicked.connect(win.reset_bar_position)
    pos_row.addWidget(b_reset_pos, 0)
    pos_box = QWidget()
    pos_lay = QVBoxLayout(pos_box)
    pos_lay.setContentsMargins(0, 0, 0, 0)
    pos_lay.setSpacing(4)
    pos_lay.addWidget(cap("位置"))
    pos_lay.addLayout(pos_row)
    win.cb_pos.setFixedHeight(30)
    grid.addWidget(pos_box, 1, 0, 1, 2)

    # 字体 / 字号 —— 同一行、两列等宽
    grid.addWidget(_cell("字体", win.cb_font), 2, 0)
    grid.addWidget(_cell("字号 (%)", win.field_size), 2, 1)

    win.field_tgap = FloatField(
        "文字距 (px)", decimals=0, minimum=0.0, maximum=200.0, allow_empty=True,
        value=(getattr(win.settings, "bar_text_offset", 0) or None))
    win.field_tgap.setToolTip("标尺文字离标尺线的距离；留空 = 按字号自动")
    win.field_tgap.valueChanged.connect(win.on_any_setting)

    # 粗细 / 边距 —— 同一行、两列等宽（与上一行同列对齐）
    grid.addWidget(_cell("粗细 (%)", win.field_thick), 3, 0)
    grid.addWidget(_cell("边距 (%)", win.field_margin), 3, 1)
    grid.addWidget(_cell("文字距 (px)", win.field_tgap), 4, 0, 1, 2)
    c.body.addLayout(grid)

    win.chk_bar_png = QCheckBox(body)
    win.chk_bar_png.setChecked(win.settings.bar_extra_png)
    win.chk_bar_png.setToolTip("只有标尺、背景透明；丢进 AI 里放大也不会糊")
    win.chk_bar_png.toggled.connect(win.on_any_setting)
    win.chk_bar_png.hide()
    win.cb_zoom = QComboBox()
    win.cb_zoom.addItems(["1×（原像素）", "2×", "4×"])
    win.cb_zoom.setCurrentIndex({1: 0, 2: 1, 4: 2}.get(int(win.settings.export_zoom), 0))
    win.cb_zoom.setToolTip("图片放大导出，标尺按放大后的分辨率重新高清绘制")
    win.cb_zoom.currentIndexChanged.connect(win.on_any_setting)
    win.cb_color = QComboBox()
    win.cb_color.addItems(["自动", "白色", "黑色", "自定义"])
    win.cb_color.setToolTip("自动 = 背景深就画白、背景亮就画黑")
    win.cb_color.setCurrentIndex(0 if win.settings.bar_color == "auto" else
                                  1 if win.settings.bar_color == "white" else
                                  2 if win.settings.bar_color == "black" else 3)
    win._custom_color = (win.settings.bar_color
                          if win.settings.bar_color.startswith("#") else "#ffffff")
    win.cb_color.currentIndexChanged.connect(win.on_any_setting)
    # 一排小按钮：颜色 / 刻度 / 带 µm / 显示文字 / 透明 PNG / 导出放大
    win.pill_color = BrutalButton("颜色：自动", compact=True)
    win.pill_color.setToolTip("标尺颜色；选「自定义」可以自己挑")
    win.pill_color.clicked.connect(win.on_pill_color)
    win.pill_ticks = BrutalButton("刻度", compact=True)
    win.pill_ticks.clicked.connect(win.on_pill_ticks)
    win.pill_unit = BrutalButton("带 µm", compact=True)
    win.pill_unit.setCheckable(True)
    win.pill_unit.toggled.connect(win.on_pill_unit)
    win.pill_text = BrutalButton("显示文字", compact=True)
    win.pill_text.setCheckable(True)
    win.pill_text.toggled.connect(win.on_pill_text)
    win.pill_png = BrutalButton("透明标尺 PNG", compact=True)
    win.pill_png.setCheckable(True)
    win.pill_png.setToolTip("另外导出一张只有标尺的透明图")
    win.pill_png.toggled.connect(win.on_pill_png)
    win.pill_zoom = BrutalButton("导出放大 1×", compact=True)
    win.pill_zoom.clicked.connect(win.on_pill_zoom)

    pills = QWidget()
    pg = QGridLayout(pills)
    pg.setContentsMargins(0, 2, 0, 0)
    pg.setHorizontalSpacing(6)
    pg.setVerticalSpacing(6)
    order = (win.pill_color, win.pill_ticks, win.pill_unit, win.pill_text,
             win.pill_png, win.pill_zoom)
    for i, b in enumerate(order):
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        pg.addWidget(b, i // 3, i % 3)
    for col in range(3):
        pg.setColumnStretch(col, 1)
    c.body.addWidget(pills)
    return c
