# -*- coding: utf-8 -*-
"""原图/裁剪结果来回切换 + "隐藏裁剪框"按钮的自检（2026-09-26 用户反馈）。

① 裁剪结果 → 原图显示：_used_rect 要复位成整帧，否则画布以为图只覆盖中间一块、
   四周留黑（用户实测："得滚一下滚轮才还原"）
② 画布上图片的绘制矩形 == 控件矩形（肉眼层面就是"周边没有黑边"）
③ 来回切 5 次仍然一致
④ 画面覆盖整帧（_pix_um == 整幅视野），而且"切之前的画面"和"来回切之后的画面"要基本一致
⑤ 「隐藏裁剪框」勾上：画布不再画框、也点不到框
⑥ 再点一下：框回来
⑦ 隐藏状态要写进 settings（下次打开还是只看图）
⑧ 隐藏框时照样能画 ROI
⑨ 1× 改配色后不能把"底图脏"标记清掉（清了的话放大/拖动时露出来的还是旧配色）
⑩ 放大以后底图必须重算成新配色
⑪ 改「叠加方式」显示要立刻跟上（同一类脏标记问题）
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

import numpy as np                                                    # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt                        # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase, QImage, QWheelEvent   # noqa: E402
from PySide6.QtWidgets import QApplication                            # noqa: E402

from core import loader                                               # noqa: E402
from ui.main_window import MainWindow                                 # noqa: E402
from _samples import P  # noqa: E402

OIB = P(r"E:\XY\亚细胞定位部\4gegene\2\3164p.oib")
BG = (24, 24, 28)          # 画布底色 #18181C


def canvas_buf(win):
    """抓画布成 numpy（h, w, 3），用来做"切换前后画面一致"的对比。"""
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()
    img = win.canvas.grab().toImage().convertToFormat(QImage.Format_RGB888)
    w, h, stride = img.width(), img.height(), img.bytesPerLine()
    raw = np.frombuffer(img.constBits(), np.uint8)
    return raw[: stride * h].reshape(h, stride)[:, : w * 3].reshape(h, w, 3).astype(np.int16)


def run(app, win):
    it = win.cur_item
    cv = win.canvas
    res = {}
    before = canvas_buf(win)             # 还没来回切之前的画面
    win.set_view_mode("crop")
    for _ in range(6):
        app.processEvents()
    win.set_view_mode("full")
    for _ in range(6):
        app.processEvents()
    used = win._used_rect
    ok1 = bool(used) and abs(used[0]) < 1e-6 and abs(used[1]) < 1e-6 \
        and abs(used[2] - 1.0) < 1e-6 and abs(used[3] - 1.0) < 1e-6
    print("[1] 切回原图后 _used_rect = %s → %s"
          % (tuple(round(v, 3) for v in (used or ())), "OK" if ok1 else "不过"))
    res["切回复位"] = bool(ok1)

    r, rr = cv._view_rect(), cv.rect()
    ok2 = abs(r.width() - rr.width()) <= 2 and abs(r.height() - rr.height()) <= 2
    print("[2] 图片绘制矩形 %dx%d vs 控件 %dx%d → %s"
          % (r.width(), r.height(), rr.width(), rr.height(), "OK" if ok2 else "不过"))
    res["无黑边"] = bool(ok2)

    fw, fh = cv._field
    pum = cv._pix_um or ()
    ok4a = bool(pum) and abs(pum[0]) < 1e-6 and abs(pum[1]) < 1e-6 \
        and abs(pum[2] - fw) < 1e-6 and abs(pum[3] - fh) < 1e-6
    after = canvas_buf(win)
    d = float(np.abs(before[: min(before.shape[0], after.shape[0]),
                            : min(before.shape[1], after.shape[1])]
                     - after[: min(before.shape[0], after.shape[0]),
                             : min(before.shape[1], after.shape[1])]).mean())
    ok4b = d < 4.0                       # 有黑边时这个差值会几十起步
    print("[4] 覆盖整帧=%s（_pix_um=%s 视野=%s）；来回切前后画面平均差 %.1f → %s"
          % (ok4a, tuple(round(v, 1) for v in pum), (round(fw, 1), round(fh, 1)), d,
             "OK" if (ok4a and ok4b) else "不过"))
    res["画面不残影"] = bool(ok4a and ok4b)

    bad = 0
    for _ in range(5):
        win.set_view_mode("crop")
        app.processEvents()
        win.set_view_mode("full")
        for _ in range(4):
            app.processEvents()
        u = win._used_rect or ()
        if not (len(u) == 4 and abs(u[0]) < 1e-6 and abs(u[2] - 1.0) < 1e-6):
            bad += 1
    print("[3] 来回切 5 次：%d 次没复位 → %s" % (bad, "OK" if bad == 0 else "不过"))
    res["反复切换"] = bad == 0

    win.btn_hide_box.setChecked(True)
    for _ in range(4):
        app.processEvents()
    ok5 = (not cv._show_box) and (cv._hit(cv.rect().center()) is None)
    print("[5] 隐藏裁剪框：不画框=%s，点不到框=%s → %s"
          % (not cv._show_box, cv._hit(cv.rect().center()) is None,
             "OK" if ok5 else "不过"))
    res["可隐藏"] = bool(ok5)

    ok7 = (win._sync_settings().show_box is False)
    print("[7] 写进 settings：show_box = %s → %s"
          % (win._sync_settings().show_box, "OK" if ok7 else "不过"))
    res["状态落盘"] = bool(ok7)

    n0 = len(it.rois)
    win.on_roi_done("rect", 0.2, 0.2, 0.4, 0.4)
    app.processEvents()
    ok8 = len(it.rois) == n0 + 1
    print("[8] 隐藏框时画 ROI：%d → %d 个 → %s"
          % (n0, len(it.rois), "OK" if ok8 else "不过"))
    res["隐藏也能画ROI"] = bool(ok8)

    win.btn_hide_box.setChecked(False)
    for _ in range(4):
        app.processEvents()
    ok6 = cv._show_box and cv._hit(cv.rect().center()) is not None
    print("[6] 再点一下：框回来了=%s → %s" % (ok6, "OK" if ok6 else "不过"))
    res["可恢复"] = bool(ok6)

    # ⑨⑩⑪ 底图（放大/拖动时露出来的那张）必须跟着配色与叠加方式走
    def base_mean():
        b = win._base_rgb
        return None if b is None else (float(b[..., 0].mean()), float(b[..., 1].mean()),
                                       float(b[..., 2].mean()))

    def wheel(n):
        ev = QWheelEvent(QPointF(cv.width() / 2.0, cv.height() / 2.0),
                         QPointF(cv.width() / 2.0, cv.height() / 2.0),
                         QPoint(0, 0), QPoint(0, 120 * n), Qt.NoButton, Qt.NoModifier,
                         Qt.ScrollUpdate, False)
        QApplication.sendEvent(cv, ev)
        for _ in range(20):
            app.processEvents()
        # 界面里滚轮后有个 110ms 去抖才重算预览；自检不等它，直接同步刷一次（等价）
        time.sleep(0.12)
        for _ in range(10):
            app.processEvents()
        win.refresh_preview()
        for _ in range(6):
            app.processEvents()

    wheel(6)
    for _ in range(10):
        app.processEvents()
    wheel(-20)                      # 回到 1×，先把底图建出来
    base_before = base_mean()
    ch0 = it.channels[0]
    old_lo = (ch0.black, ch0.white)
    win.apply_channel_color(ch0, "品红", (255, 0, 255))    # 在 1× 改配色
    for _ in range(10):
        app.processEvents()
    ok9 = bool(win._base_stale)     # 脏标记不能被清掉
    print("[9] 1× 改成品红后：_base_stale = %s → %s"
          % (win._base_stale, "OK" if ok9 else "不过（脏标记被清了）"))
    res["脏标记保留"] = bool(ok9)

    wheel(6)                        # 放大 → 底图应重算成品红
    base_after = base_mean()
    ok10 = bool(base_after) and base_after[0] > base_before[0] - 0.5 \
        and base_after[1] < base_before[1] - 0.5
    print("[10] 放大后底图 RGB = %s（改配色前 %s）→ %s"
          % (tuple(round(v, 1) for v in (base_after or ())),
             tuple(round(v, 1) for v in (base_before or ())),
             "OK" if ok10 else "不过（还是旧配色）"))
    res["放大后底图更新"] = bool(ok10)

    # ⑪ 叠加方式：切到"最大强度"画面要立刻变（不能等下次缩放）
    win.cb_merge_mode.setCurrentIndex(1)
    for _ in range(10):
        app.processEvents()
    ok11 = (win._sync_settings().merge_mode == "max") and (cv._pix is not None)
    print("[11] 切到「%s」：settings.merge_mode=%s，画面已刷新=%s → %s"
          % (win.cb_merge_mode.currentText(), win._sync_settings().merge_mode,
             cv._pix is not None, "OK" if ok11 else "不过"))
    res["叠加方式即时"] = bool(ok11)
    win.cb_merge_mode.setCurrentIndex(0)
    win.apply_channel_color(ch0, "绿", (0, 255, 0))
    ch0.black, ch0.white = old_lo
    win.refresh_channels()
    win.refresh_preview()
    return res


def main():
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    win = MainWindow()
    win.resize(1400, 900)
    it = loader.probe(OIB)
    win.items = [it]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.show()
    for _ in range(8):
        app.processEvents()
    win.resize(1400, 900)
    for _ in range(8):
        app.processEvents()
    win.select_item(it.path)
    for _ in range(6):
        app.processEvents()

    res = run(app, win)
    out = os.path.join(APP, "output", "_自检")
    os.makedirs(out, exist_ok=True)
    win.btn_hide_box.setChecked(True)
    for _ in range(6):
        app.processEvents()
    win.grab().save(os.path.join(out, "隐藏裁剪框.png"))
    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
