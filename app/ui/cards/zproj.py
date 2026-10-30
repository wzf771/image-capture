# -*- coding: utf-8 -*-
"""右栏功能卡片：Z 投影（P1-5）。

只有多层 Z 的图才启用；投影结果作为"当前显示的那一帧"，
XY 标定不变 → 裁剪框 / 标尺 / 导出流程照旧。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout,
                               QWidget)

from ui.card import card
from ui.cards._helpers import pair, plab
from ui.widgets import BrutalButton, FloatField


def build(win):
    c = card("Z 投影", "多层 Z 才用", module=True)
    win.zp_tool = QWidget()
    lay = QVBoxLayout(win.zp_tool)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    win.cb_proj = QComboBox()
    win.cb_proj.setObjectName("field")
    win.cb_proj.addItems(["不投影（看单层）", "MIP 最大强度", "Sum 求和",
                          "Mean 平均", "SD 标准差"])
    win.cb_proj.setToolTip("把一段 Z 层压成一张二维图；XY 标定不变，裁剪框与标尺照旧")
    win.cb_proj.currentIndexChanged.connect(win.on_proj_changed)
    lay.addLayout(pair("模式", win.cb_proj))
    win.cb_proj_range = QComboBox()
    win.cb_proj_range.setObjectName("field")
    win.cb_proj_range.addItems(["全部层", "当前层 ± n", "手动起止层"])
    win.cb_proj_range.currentIndexChanged.connect(win.on_proj_range_changed)
    lay.addLayout(pair("范围", win.cb_proj_range))
    win.sp_proj_n = QSpinBox()
    win.sp_proj_n.setObjectName("field")
    win.sp_proj_n.setRange(0, 999)
    win.sp_proj_n.setValue(3)
    win.sp_proj_n.setToolTip("「当前层 ± n」的 n：跟着 Z 滑条走")
    win.sp_proj_n.valueChanged.connect(win.on_proj_changed)
    win.sp_proj_from = QSpinBox()
    win.sp_proj_to = QSpinBox()
    for w in (win.sp_proj_from, win.sp_proj_to):
        w.setObjectName("field")
        w.setRange(1, 9999)
        w.valueChanged.connect(win.on_proj_changed)
    lay.addLayout(pair("±n", win.sp_proj_n))
    lay.addLayout(pair("起止层", win.sp_proj_from))
    lay.addLayout(pair("", win.sp_proj_to))
    win.lbl_proj_hint = QLabel("")
    win.lbl_proj_hint.setObjectName("muted")
    win.lbl_proj_hint.setWordWrap(True)
    lay.addWidget(win.lbl_proj_hint)
    win.btn_ortho = BrutalButton("打开正交视图（XZ / YZ 剖面）", compact=True)
    win.btn_ortho.setToolTip("沿一条取样线看 Z 方向的剖面；横线 = XZ，竖线 = YZ")
    win.btn_ortho.clicked.connect(win.open_ortho)
    lay.addWidget(win.btn_ortho)
    win.zp_tool.setVisible(False)
    c.body.addWidget(win.zp_tool)
    return c
