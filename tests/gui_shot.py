# -*- coding: utf-8 -*-
"""离屏跑一遍界面并截图，用来检查排版（不需要人盯着屏幕）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"          # 自检不要动用户的参数文件
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                 # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402
from PySide6.QtCore import QElapsedTimer                       # noqa: E402

import paths                                                   # noqa: E402
from core import loader, render                                # noqa: E402
from ui.main_window import CardFrame, ClickLabel, MainWindow   # noqa: E402
from _samples import P  # noqa: E402

FILES = [
    P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\2a-1.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\2a-2.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\汇总\原始数据\kongzai.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\6.4\ER1.oib"),
    P(r"E:\XY\亚细胞定位部\3.31构载体两个\6.4\ER\LiveStop.oib"),
    P(r"E:\XY\相分离部\6.3\6.3\frap\3-6\FRAPR1.oib"),
]

# 额外样本（可选）：IMAGECAPTURE_EXTRA_SAMPLES 用 ; 分隔
EXTRA = [x for x in os.environ.get("IMAGECAPTURE_EXTRA_SAMPLES", "").split(";") if x]
FILES = FILES + EXTRA


def wait(ms):
    """等动画跑完（展开 / 收起现在是滑出来的）。"""
    clock = QElapsedTimer()
    clock.start()
    while clock.elapsed() < ms:
        QApplication.processEvents()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(paths.OUTPUT_DIR, "_自检")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv[:1])
    # 离屏渲染时 Qt 可能找不到字体，显式加载一份系统字体
    for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1460, 940)          # 模拟 150% 缩放的笔记本屏可用区域
    items = []
    for p in FILES:
        if os.path.exists(p):
            items.append(loader.probe(p))
    win.items = items
    win._regroup()
    for it in items:
        try:
            win._thumbs[it.path] = render.make_thumb(it, 256)
        except Exception as exc:                        # noqa: BLE001
            print("缩略图失败", it.name, exc)
    win.refresh_groups()
    win.refresh_strip()
    win.refresh_preview()
    win.refresh_manifest()
    win.show()
    app.processEvents()
    app.processEvents()
    win.resize(1460, 940)
    app.processEvents()
    app.processEvents()
    for btn, holder in ((win.btn_left, win.left_holder), (win.btn_right, win.right_holder)):
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)
        holder.setVisible(True)
    app.processEvents()
    path = os.path.join(out, "界面.png")
    win.grab().save(path)
    print("已保存", path, "组数", len(win.groups), "图片数", len(items))
    win.btn_right.setChecked(False)
    app.processEvents()
    app.processEvents()
    p0 = os.path.join(out, "界面_收起右栏.png")
    win.grab().save(p0)
    print("已保存", p0)
    win.btn_right.setChecked(True)
    app.processEvents()
    # 折叠几张卡片 + 收起左栏，看看小屏时的样子
    for c in win.findChildren(CardFrame):
        if getattr(c, "title", "") == "新标尺":
            c.toggle()
    wait(520)
    win.btn_left.setChecked(False)
    app.processEvents()
    app.processEvents()
    p1 = os.path.join(out, "界面_折叠卡片.png")
    win.grab().save(p1)
    print("已保存", p1)
    win.btn_left.setChecked(True)
    for c in win.findChildren(CardFrame):
        if getattr(c, "title", "") == "新标尺":
            c.toggle()
    wait(520)
    if win.groups:
        win.select_group(win.groups[-1].gid)
        app.processEvents()
        p2 = os.path.join(out, "界面_时间序列.png")
        win.grab().save(p2)
        print("已保存", p2)
    win.set_view_mode("crop")
    app.processEvents()
    p3 = os.path.join(out, "界面_裁剪结果.png")
    win.grab().save(p3)
    print("已保存", p3)


if __name__ == "__main__":
    main()
