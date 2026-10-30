# -*- coding: utf-8 -*-
"""卡片标题左边那个小锁的接线自检（2026-09-26 用户指定，替代原来的空心圆环）。

查这几件事：
  ① 8 个位置全都有锁：右栏 7 张卡（裁剪视野/新标尺/Z 投影/处理/ROI 与测量/
     通道与颜色/标定）+ 中间「组内图片」
  ② 大小跟原来的 RingDot 一样（20×20）
  ③ 初始状态跟卡片展开状态一致（展开=紫+开锁，收起=灰+闭锁）
  ④ 点锁一次 → 卡片正好开合一次（不能翻两下：锁自己吃点击，别又冒泡到标题行）
  ⑤ 点标题行 → 锁跟着变
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtCore import Qt                                        # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase                       # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402

from ui.main_window import MainWindow, CardFrame                     # noqa: E402
from ui.widgets import LockDot                                       # noqa: E402

WANT = ["裁剪视野", "新标尺", "Z 投影", "处理", "ROI 与测量", "通道与颜色", "标定", "组内图片"]


def _click(widget):
    """真按一下（press+release），而不是 widget.click()，这样能验出双重触发。"""
    try:
        from PySide6.QtTest import QTest
        QTest.mouseClick(widget, Qt.LeftButton)
    except Exception:                                                # noqa: BLE001
        widget.pos()
        widget.click()


def main():
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    for _ in range(8):
        app.processEvents()
    res = {}

    cards = {getattr(c, "title", ""): c for c in win.findChildren(CardFrame)}
    dots = {}
    for title in WANT:
        c = cards.get(title)
        dots[title] = None if c is None else c.findChild(LockDot)
    miss = [t for t in WANT if dots[t] is None]
    print("[1] 8 个位置的小锁：%s" % ("齐全" if not miss else "缺 " + "、".join(miss)))
    res["位置齐全"] = not miss

    sizes = {t: (d.width(), d.height()) for t, d in dots.items() if d is not None}
    ok2 = all(s == (20, 20) for s in sizes.values())
    print("[2] 尺寸（原小圈是 20×20）：%s → %s"
          % ("、".join("%s %dx%d" % (t, w, h) for t, (w, h) in sizes.items()),
             "OK" if ok2 else "不过"))
    res["尺寸一致"] = bool(ok2)

    bad = []
    for t, d in dots.items():
        if d is None:
            continue
        if bool(d.isChecked()) != bool(cards[t].want_open):
            bad.append(t)
    print("[3] 初始状态与卡片一致：%s → %s"
          % ("（展开 " + "、".join(t for t in WANT if dots[t] and dots[t].isChecked()) + "）",
             "OK" if not bad else "不一致：" + "、".join(bad)))
    res["初始一致"] = not bad

    # ④ 点锁一次 = 开合一次
    t = "新标尺"
    card, dot = cards[t], dots[t]
    before = bool(card.want_open)
    _click(dot)
    for _ in range(4):
        app.processEvents()
    after = bool(card.want_open)
    ok4 = after != before
    print("[4] 点一下「%s」的锁：卡片 %s → %s（正好翻一次）→ %s"
          % (t, "展开" if before else "收起", "展开" if after else "收起",
             "OK" if ok4 else "不过（翻了两次或没反应）"))
    res["点锁开合"] = bool(ok4)

    # ⑤ 点标题行 → 锁跟着变
    card.head.clicked.emit()                 # 模拟点标题那一行
    for _ in range(4):
        app.processEvents()
    ok5 = bool(dot.isChecked()) == bool(card.want_open) and bool(card.want_open) != after
    print("[5] 点标题行：卡片 %s，锁 %s → %s"
          % ("展开" if card.want_open else "收起",
             "紫+开锁" if dot.isChecked() else "灰+闭锁", "OK" if ok5 else "不过"))
    res["标题联动"] = bool(ok5)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
