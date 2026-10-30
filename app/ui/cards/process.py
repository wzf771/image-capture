# -*- coding: utf-8 -*-
"""右栏功能卡片：处理（通道配准 / 背景扣除 / 漂移校正）—— 规格书 P1-7。

为什么单独一张卡片：这三步都会**改变像素值**，用户必须能一眼看到
"现在到底开了哪几步、参数是多少"，并且能一键关掉对比。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QSpinBox,
                               QVBoxLayout, QWidget)

from ui.card import card
from ui.cards._helpers import pair, plab
from ui.widgets import BrutalButton, FlipSwitch


def build(win):
    c = card("处理", "会改像素值", module=True)
    win.proc_tool = QWidget()
    lay = QVBoxLayout(win.proc_tool)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)

    # ---- 通道配准
    win.sw_reg = FlipSwitch()
    win.sw_reg.setToolTip("把各个荧光通道按平移对齐（只做平移；共聚焦的通道失配主要是平移）")
    win.sw_reg.toggled.connect(win.on_proc_changed)
    lay.addLayout(win._switch_row(win.sw_reg, "通道配准（XY 平移）"))
    win.cb_reg_ref = QComboBox()
    win.cb_reg_ref.setObjectName("field")
    win.cb_reg_ref.currentIndexChanged.connect(win.on_proc_changed)
    lay.addLayout(pair("参考通道", win.cb_reg_ref))
    win.btn_reg_calc = BrutalButton("重新计算位移", compact=True)
    win.btn_reg_calc.clicked.connect(win.recalc_register)
    lay.addWidget(win.btn_reg_calc)
    win.reg_rows = QVBoxLayout()
    win.reg_rows.setSpacing(2)
    lay.addLayout(win.reg_rows)

    # ---- 背景扣除
    win.sw_bg = FlipSwitch()
    win.sw_bg.setToolTip("按百分位/常量扣背景；**保留负值**，不 clip 到 0")
    win.sw_bg.toggled.connect(win.on_proc_changed)
    lay.addLayout(win._switch_row(win.sw_bg, "背景扣除"))
    win.cb_bg_mode = QComboBox()
    win.cb_bg_mode.setObjectName("field")
    win.cb_bg_mode.addItems(["百分位扣除", "常量扣除"])
    win.cb_bg_mode.currentIndexChanged.connect(win.on_proc_changed)
    lay.addLayout(pair("方法", win.cb_bg_mode))
    win.sp_bg_p = QDoubleSpinBox()
    win.sp_bg_p.setObjectName("field")
    win.sp_bg_p.setRange(0.1, 99.0)
    win.sp_bg_p.setSingleStep(0.5)
    win.sp_bg_p.setValue(5.0)
    win.sp_bg_p.setToolTip("百分位扣除：取这个分位数当背景（共聚焦默认 5%）")
    win.sp_bg_p.valueChanged.connect(win.on_proc_changed)
    lay.addLayout(pair("百分位", win.sp_bg_p))
    win.sp_bg_c = QDoubleSpinBox()
    win.sp_bg_c.setObjectName("field")
    win.sp_bg_c.setRange(0.0, 65535.0)
    win.sp_bg_c.setDecimals(1)
    win.sp_bg_c.setValue(0.0)
    win.sp_bg_c.setToolTip("常量扣除：直接减这个值（有明确暗电流时用）")
    win.sp_bg_c.valueChanged.connect(win.on_proc_changed)
    lay.addLayout(pair("常量", win.sp_bg_c))

    # ---- 漂移校正
    win.sw_drift = FlipSwitch()
    win.sw_drift.setToolTip("时间序列：逐帧相对参考帧对齐，锁住样品漂移")
    win.sw_drift.toggled.connect(win.on_proc_changed)
    lay.addLayout(win._switch_row(win.sw_drift, "时间序列漂移校正"))
    win.sp_drift_ref = QSpinBox()
    win.sp_drift_ref.setObjectName("field")
    win.sp_drift_ref.setRange(1, 1)
    win.sp_drift_ref.valueChanged.connect(win.on_proc_changed)
    lay.addLayout(pair("参考帧", win.sp_drift_ref))
    win.btn_drift_calc = BrutalButton("重新计算漂移", compact=True)
    win.btn_drift_calc.clicked.connect(win.recalc_drift)
    lay.addWidget(win.btn_drift_calc)

    win.btn_overlay = BrutalButton("存一张叠加检查图", compact=True)
    win.btn_overlay.setToolTip("参考通道用绿、目标通道用品红：错位会变成彩边，肉眼即可判断")
    win.btn_overlay.clicked.connect(win.save_overlay_check)
    lay.addWidget(win.btn_overlay)

    # 去卷积（P1-8）已按用户要求移除（2026-09-22）：
    # 本软件定位是"统一下机数据 → 统一裁剪导出"，不做会改变像素强度的算法处理。
    win.lbl_proc = QLabel("")
    win.lbl_proc.setObjectName("muted")
    win.lbl_proc.setWordWrap(True)
    lay.addWidget(win.lbl_proc)
    win.proc_tool.setVisible(False)
    c.body.addWidget(win.proc_tool)
    return c
