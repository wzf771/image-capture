# -*- coding: utf-8 -*-
"""右栏功能卡片集合（2026-09-22 从 main_window.py 拆分）。

每张卡片一个模块，每个模块提供 `build(win) -> QFrame`：

    crop    裁剪视野
    ruler   新标尺
    channel 通道与颜色
    calib   标定

（export 导出内容 已于 2026-09-23 整块移除：那批控件搬进了 ui/export_dialog.py
 的导出弹窗 —— 点 Download 先选图片、再选导出内容。）

约定：**只搬不改逻辑**。动作处理函数（on_xxx）暂时仍留在 MainWindow 上，
后续再按卡片逐步搬进来；这样每一步都能单独验证。
"""
