# -*- coding: utf-8 -*-
"""界面级自检：右栏「通道与颜色」的条数，必须等于 loader 修正后的通道数。

用户实测 bug（2026-09-23）：蔡司 Snap-14700 导入后右栏一直挂着两路
（FITC-T1 + EGFP-T2），缩略图和主图却已经是合并后的一路 ——
原因是通道卡画在**解码之前**，loader 在第一次 `load_stack()` 里做的
「合并原始版+处理版」「隐藏全黑通道」修正，界面没有收到通知。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                      # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from core import loader                                             # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402

FILES = [p for p in os.environ.get("IMAGECAPTURE_SAMPLES_CZI", "").split(";") if p]


def main():
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    if not FILES:
        print("没有 CZI/LIF 样本：设置 IMAGECAPTURE_SAMPLES_CZI 后重跑。跳过。")
        return 0
    win = MainWindow()
    win.resize(1460, 940)
    win.items = [loader.probe(p) for p in FILES if os.path.exists(p)]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.show()
    app.processEvents()
    win.resize(1460, 940)
    app.processEvents()

    ok = True
    for it in list(win.items):
        win.select_item(it.path)            # 走真实流程：probe → 选中 → 预览解码
        app.processEvents()
        rows = win.chan_layout.count()
        n = len(it.channels or [])
        rgb = n > 0 and all(c.role == "rgb" for c in it.channels)
        # 顶上那行"… µm/px · 宽×高 · N 通道"也是按通道表算的，一起查
        import re
        m = re.search(r"·\s*(\d+)\s*通道", win.lbl_group_info.text())
        head_n = int(m.group(1)) if m else -1
        good = ((rows == 1) if rgb else (rows == n)) and head_n == n
        ok = ok and good and n >= 1
        print("  %-42s 通道表 %d 路 %-24s 界面 %d 行 · 顶行写 %d 通道  %s"
              % (it.name[:42], n, str([c.name for c in (it.channels or [])])[:24],
                 rows, head_n, "OK" if good else "不过"))
    print()
    print("结论:", "全部通过" if ok else "有未通过项")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
