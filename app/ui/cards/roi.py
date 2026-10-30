# -*- coding: utf-8 -*-
"""右栏功能卡片：ROI 与测量（P1-6）。

铁律：统计只读**原始位深**数据（`loader.load_stack`，链开着就是链后重建），
显示区间 / 配色 / 屏幕锐化一律不参与。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget)

from ui.card import card
from ui.cards._helpers import pair
from ui.widgets import BrutalButton


def build(win):
    c = card("ROI 与测量", "只读原始数据", module=True)
    win.roi_tool = QWidget()
    lay = QVBoxLayout(win.roi_tool)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    tools = QHBoxLayout()
    tools.setSpacing(5)
    # 2026-09-28 用户要求：工具点一次就一直能画（不用每画一个再点一次），
    # 所以四个按钮都是可勾选的；勾中 = 该工具 armed，再点一次（或按 Esc）退出。
    win._roi_tool_buttons = {}
    for text, kind, tip in (("矩形", "rect", "拖一个矩形 ROI"),
                            ("椭圆", "ellipse", "拖一个椭圆 ROI"),
                            ("直线", "line", "拖一条直线：线剖面/长度"),
                            ("点", "point", "在图上点一个取样点（默认取半径 3 px 的小圆均值）")):
        b = BrutalButton(text, compact=True)
        b.setCheckable(True)
        b.setToolTip(tip + "\n点一次就一直能画；再点这个按钮或按 Esc 退出")
        b.clicked.connect(lambda _ck=False, k=kind: win.on_roi_tool(k))
        win._roi_tool_buttons[kind] = b
        tools.addWidget(b)
    lay.addLayout(tools)
    # 2026-09-28：右栏不再一个个列 ROI（用户要求），改成图上右键编辑 —— 这里不再建列表
    # 线剖面宽度（垂直 ±n 像素平均，抗噪）与粒子面积下限
    win.sp_prof_w = QSpinBox()
    win.sp_prof_w.setObjectName("field")
    win.sp_prof_w.setRange(0, 8)
    win.sp_prof_w.setValue(0)
    win.sp_prof_w.setToolTip("线剖面宽度：沿线两侧各取 n 像素平均（0 = 只取线本身）")
    lay.addLayout(pair("剖面宽度 ±n", win.sp_prof_w))
    win.sp_particle_min = QSpinBox()
    win.sp_particle_min.setObjectName("field")
    win.sp_particle_min.setRange(1, 100000)
    win.sp_particle_min.setValue(4)
    win.sp_particle_min.setToolTip("粒子面积下限（像素）：小于它的当噪点丢掉")
    lay.addLayout(pair("粒子面积下限", win.sp_particle_min))
    # 2026-09-26：原来"测量表/剖面/共定位/粒子"4 个按钮各自弹一个窗，合成一个面板
    for text, slot, tip in (
            ("测量…", lambda: win.roi_measure(),
             "一个面板里看强度 / 线剖面 / 共定位 / 粒子（可选 ROI、通道、帧）"),
            ("套用到本组每张", lambda: win.apply_rois_to_group(),
             "把当前图的 ROI 按相同相对位置复制到本组其它图（时间序列/重复孔常用）"),
            ("导出全部 CSV", lambda: win.roi_export_csv(), "所有 ROI 的结果（Excel 不乱码）")):
        b = BrutalButton(text, compact=True)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        lay.addWidget(b)
    win.lbl_roi = QLabel("")
    win.lbl_roi.setObjectName("muted")
    win.lbl_roi.setWordWrap(True)
    win.lbl_roi.setToolTip(
        "图上可以直接点选 / 拖动 / 拖四角缩放 ROI\n"
        "右键某个 ROI：改名 / 设为背景 / 点的大小 / 复制到本组 / 删除\n"
        "Delete = 删除选中的，Esc = 退出画图工具")
    lay.addWidget(win.lbl_roi)
    c.body.addWidget(win.roi_tool)
    return c
